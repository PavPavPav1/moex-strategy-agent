import re
from datetime import date, datetime
from typing import List, Tuple

from pydantic import ValidationError

from .errors import ToolProblem
from .models import StrategySpec


TICKER_ALIASES = {
    "сбер": "SBER",
    "сбербанк": "SBER",
    "газпром": "GAZP",
    "лукойл": "LKOH",
    "яндекс": "YDEX",
    "тинькофф": "TCS",
    "т-банк": "TCS",
    "роснефть": "ROSN",
    "новатэк": "NOVATEK",
}


def _parse_date(raw: str) -> str:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(raw)


def _extract_ticker(text: str) -> str:
    lowered = text.lower()
    for alias, ticker in TICKER_ALIASES.items():
        if re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", lowered):
            return ticker
    patterns = [
        r"(?:тикер|акци[ия]|бумага|инструмент)\s*[:#-]?\s*([A-Za-z][A-Za-z0-9.-]{0,11})",
        r"\b(SBER|GAZP|LKOH|YDEX|TCS|ROSN|NOVATEK|MGNT|NVTK|PLZL|GMKN)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    raise ToolProblem(
        "validation",
        "Не удалось определить тикер",
        "Укажи тикер MOEX латиницей, например: SBER или GAZP",
    )


def _extract_windows(text: str) -> Tuple[int, int, List[str]]:
    assumptions: List[str] = []
    numbers = [int(value) for value in re.findall(r"SMA\s*\(\s*(\d{1,3})\s*\)", text, re.IGNORECASE)]
    if not numbers:
        numbers = [int(value) for value in re.findall(r"(?:окн[аоу]|период)\s*[:=]?\s*(\d{1,3})", text, re.IGNORECASE)]
    if len(numbers) >= 2:
        fast, slow = numbers[0], numbers[1]
    else:
        fast, slow = 20, 50
        assumptions.append("Окна SMA не указаны однозначно: использованы 20 и 50 дней")
    return fast, slow, assumptions


def _extract_capital(text: str, assumptions: List[str]) -> float:
    match = re.search(r"(?:капитал|депозит|начальн\w*\s+сумм\w*)\D{0,20}([\d\s_]+(?:[.,]\d+)?)", text, re.IGNORECASE)
    if not match:
        assumptions.append("Начальный капитал не указан: использовано 1 000 000 ₽")
        return 1_000_000.0
    return float(match.group(1).replace(" ", "").replace("_", "").replace(",", "."))


def _extract_fee(text: str, assumptions: List[str]) -> float:
    match = re.search(r"(?:комисси\w+|fee)\D{0,15}([\d]+(?:[.,]\d+)?)\s*(?:б\.?\s*п\.?|bps?|процент\w*\s*пункт\w*)", text, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(",", "."))
    percent = re.search(r"(?:комисси\w+|fee)\D{0,15}([\d]+(?:[.,]\d+)?)\s*%", text, re.IGNORECASE)
    if percent:
        return float(percent.group(1).replace(",", ".")) * 100
    assumptions.append("Комиссия не указана: использовано 5 б.п. (0,05%) на каждую операцию")
    return 5.0


def _validate_supported_rules(text: str) -> None:
    hint = "Поддерживается только покупка при SMA fast > SMA slow и выход при fast <= slow; убери дополнительные условия"
    if re.search(r"\b(?:RSI|EMA|MACD|ATR|ADX|VWAP|ROC|CCI|STOCH|WMA)\b|боллиндж|стохаст|экспоненциал|тейк|стоп|stop.?loss|take.?profit", text, re.IGNORECASE):
        raise ToolProblem("unsupported_strategy", "Неподдерживаемый индикатор или условие выхода", hint)
    functions = re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\s*\(", text)
    if any(name.upper() != "SMA" for name in functions):
        raise ToolProblem("unsupported_strategy", "Поддерживается только индикатор SMA", hint)
    # Keep each trading action with its own condition, including condition-first phrasing.
    text = re.sub(r"((?:покуп\w*|прода\w*|купить|buy|sell))\s*,\s*(?=когда|если|при|when|if)", r"\1 ", text, flags=re.IGNORECASE)
    clauses = re.split(r"[,;.!?\n]|\s+(?:и|and)\s+(?=прода|покуп|buy|sell)", text, flags=re.IGNORECASE)
    comparison = re.compile(r"SMA\s*\(\s*(\d+)\s*\)\s*(>=|<=|>|<|≥|≤|выше|ниже|больше|меньше)\s*SMA\s*\(\s*(\d+)\s*\)", re.IGNORECASE)
    for clause in clauses:
        buy = bool(re.search(r"покуп|купить|\bbuy\b", clause, re.IGNORECASE))
        sell = bool(re.search(r"прода|продать|\bsell\b", clause, re.IGNORECASE))
        if not (buy or sell):
            continue
        matches = list(comparison.finditer(clause))
        for match in matches:
            left, operator, right = int(match[1]), match[2].lower(), int(match[3])
            greater = operator in (">", ">=", "≥", "выше", "больше")
            bullish = (left < right) == greater
            # Equality at entry is unsupported; exit on equality is the engine default.
            if buy == sell or (buy and (not bullish or operator in (">=", "<=", "≥", "≤"))) or (sell and bullish):
                raise ToolProblem("unsupported_strategy", "Условие покупки/продажи отличается от поддерживаемой SMA-стратегии", hint)
        if not matches and re.search(r"ниже|меньше|выше|больше|[<>≤≥]", clause, re.IGNORECASE):
            raise ToolProblem("unsupported_strategy", "Неоднозначное условие сигнала; укажи обе SMA с окнами", hint)


def formalize_strategy(text: str) -> Tuple[StrategySpec, List[str]]:
    if not text or not 10 <= len(text.strip()) <= 2000:
        raise ToolProblem(
            "validation",
            "Описание стратегии должно содержать от 10 до 2000 символов",
            "Добавь тикер, период, два окна SMA, капитал и комиссию",
        )
    unsupported_text = re.sub(r"без\s+(?:шорта(?:\s+и\s+плеча)?|плеча)", "", text, flags=re.IGNORECASE)
    if re.search(r"шорт|коротк\w+\s+позици|плеч[оа]|стоп-лосс|тейк-профит", unsupported_text, re.IGNORECASE):
        raise ToolProblem(
            "unsupported_strategy",
            "Эта версия поддерживает только длинную SMA-стратегию без плеча, стопов и шорта",
            "Убери неподдерживаемые условия и задай два окна скользящих средних",
        )
    _validate_supported_rules(text)
    assumptions: List[str] = []
    ticker = _extract_ticker(text)
    fast, slow, window_assumptions = _extract_windows(text)
    assumptions.extend(window_assumptions)
    raw_dates = re.findall(r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}", text)
    if len(raw_dates) >= 2:
        try:
            date_from, date_to = _parse_date(raw_dates[0]), _parse_date(raw_dates[1])
        except ValueError:
            raise ToolProblem("validation", "Некорректная дата", "Используй формат YYYY-MM-DD или DD.MM.YYYY")
    else:
        date_from, date_to = date(2024, 1, 1), date(2025, 12, 31)
        assumptions.append("Период не указан однозначно: использован 2024-01-01 — 2025-12-31")
    capital = _extract_capital(text, assumptions)
    fee = _extract_fee(text, assumptions)
    assumptions.extend([
        "Сигнал по закрытию дня исполняется по открытию следующего торгового дня",
        "Только long: 0% или 100% доступного капитала, целое число акций, без плеча и налогов",
        "Открытая позиция закрывается по цене close последнего дня; дивиденды не учитываются",
    ])
    try:
        spec = StrategySpec(
            ticker=ticker,
            date_from=date_from,
            date_to=date_to,
            fast_window=fast,
            slow_window=slow,
            initial_capital_rub=capital,
            fee_bps=fee,
            interval=24,
        )
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ToolProblem("validation", details, "Проверь окна SMA, даты, капитал и комиссию")
    return spec, assumptions
