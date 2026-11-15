from pathlib import Path
import csv
import json
import math

from PIL import Image, ImageDraw, ImageFont
from matplotlib import get_data_path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "presentation"
REPORT = ROOT / "reports" / "demo_sber"
W, H = 1920, 1080

BG = "#0B1220"
PANEL = "#121D30"
PANEL_2 = "#17243A"
WHITE = "#F7F9FC"
TEXT = "#E8EDF5"
MUTED = "#9BAAC0"
PURPLE = "#9B8AFB"
TEAL = "#35D0BA"
RED = "#FB7185"
AMBER = "#F8C15C"
BLUE = "#69A9FF"
BORDER = "#2A3850"

FONT_DIR = Path(get_data_path()) / "fonts" / "ttf"
FONT_REGULAR = str(FONT_DIR / "DejaVuSans.ttf")
FONT_BOLD = str(FONT_DIR / "DejaVuSans-Bold.ttf")
FONT_MONO = str(FONT_DIR / "DejaVuSansMono.ttf")


def font(size, bold=False, mono=False):
    return ImageFont.truetype(FONT_MONO if mono else (FONT_BOLD if bold else FONT_REGULAR), size)


def wrap(draw, text, fnt, width):
    lines = []
    for paragraph in str(text).split("\n"):
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split()
        line = words[0]
        for word in words[1:]:
            candidate = line + " " + word
            if draw.textlength(candidate, font=fnt) <= width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def text(draw, xy, value, size, color=TEXT, bold=False, width=None, spacing=1.22, mono=False, anchor=None):
    fnt = font(size, bold, mono)
    x, y = xy
    if width is None:
        draw.text((x, y), str(value), font=fnt, fill=color, anchor=anchor)
        return y + size * spacing
    lines = wrap(draw, str(value), fnt, width)
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=color)
        y += int(size * spacing)
    return y


def rect(draw, box, fill=PANEL, radius=24, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pill(draw, xy, label, color=PURPLE, dark=BG, size=22):
    x, y = xy
    fnt = font(size, True)
    tw = draw.textlength(label, font=fnt)
    rect(draw, (x, y, x + tw + 36, y + 44), fill=color, radius=22)
    draw.text((x + 18, y + 8), label, font=fnt, fill=dark)
    return x + tw + 48


def base_slide(number, section, title_value=None, subtitle=None):
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    for x in range(0, W, 80):
        draw.line((x, 0, x, H), fill="#10192A", width=1)
    for y in range(0, H, 80):
        draw.line((0, y, W, y), fill="#10192A", width=1)
    draw.ellipse((1530, -350, 2150, 270), fill="#182343")
    draw.ellipse((-250, 900, 250, 1400), fill="#112B32")
    text(draw, (80, 46), f"{number:02d}  /  {section.upper()}", 20, PURPLE, True)
    draw.line((80, 88, 1840, 88), fill=BORDER, width=2)
    if title_value:
        text(draw, (80, 122), title_value, 50, WHITE, True, width=1680, spacing=1.12)
    if subtitle:
        text(draw, (80, 205), subtitle, 25, MUTED, width=1660)
    text(draw, (80, 1030), "MOEX STRATEGY AGENT  ·  ИССЛЕДОВАНИЕ, НЕ РЕКОМЕНДАЦИЯ", 16, MUTED, True)
    text(draw, (1790, 1028), f"{number:02d}", 18, MUTED, True)
    return image, draw


def card_title(draw, xy, eyebrow, title_value, color=PURPLE):
    x, y = xy
    text(draw, (x, y), eyebrow.upper(), 17, color, True)
    return text(draw, (x, y + 32), title_value, 29, WHITE, True, width=480)


def bullet_list(draw, xy, items, width, size=24, color=TEXT, bullet_color=TEAL, gap=18):
    x, y = xy
    for item in items:
        draw.ellipse((x, y + 11, x + 10, y + 21), fill=bullet_color)
        end = text(draw, (x + 28, y), item, size, color, width=width - 28)
        y = end + gap
    return y


def kpi(draw, box, label, value, note, accent=PURPLE):
    x1, y1, x2, y2 = box
    rect(draw, box, PANEL, 22, BORDER)
    draw.rectangle((x1, y1, x1 + 7, y2), fill=accent)
    text(draw, (x1 + 26, y1 + 22), label.upper(), 17, MUTED, True)
    text(draw, (x1 + 26, y1 + 58), value, 43, accent, True)
    text(draw, (x1 + 26, y1 + 120), note, 19, MUTED, width=x2 - x1 - 48)


def paste_rounded(slide, path, box, radius=24):
    source = Image.open(path).convert("RGB")
    x1, y1, x2, y2 = map(int, box)
    target_size = (x2 - x1, y2 - y1)
    source.thumbnail(target_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", target_size, "white")
    canvas.paste(source, ((target_size[0] - source.width) // 2, (target_size[1] - source.height) // 2))
    mask = Image.new("L", target_size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, target_size[0], target_size[1]), radius=radius, fill=255)
    slide.paste(canvas, (x1, y1), mask)


def arrow(draw, start, end, color=PURPLE, width=4):
    x1, y1 = start
    x2, y2 = end
    draw.line((x1, y1, x2, y2), fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    length = 16
    for offset in (2.55, -2.55):
        draw.line((x2, y2, x2 + length * math.cos(angle + offset), y2 + length * math.sin(angle + offset)), fill=color, width=width)


def slide_01(metrics, check):
    image, draw = base_slide(1, "Учебный проект")
    pill(draw, (80, 145), "MOEX ISS", TEAL)
    pill(draw, (260, 145), "3 ИНСТРУМЕНТА", PURPLE)
    pill(draw, (510, 145), "BACKTEST × 2", BLUE)
    text(draw, (80, 250), "MOEX", 92, WHITE, True)
    text(draw, (80, 350), "Strategy Agent", 92, WHITE, True)
    text(draw, (80, 485), "От описания на естественном языке\nк проверяемому бэктесту", 38, TEXT, width=760, spacing=1.3)
    text(draw, (80, 650), "Котировки · метрики · слабые режимы · новости без причинности", 24, MUTED, width=760)
    rect(draw, (80, 800, 740, 930), PANEL, 24, BORDER)
    text(draw, (112, 828), "ДЕМО SBER · 2024–2025", 20, MUTED, True)
    text(draw, (112, 872), f"{metrics['total_return_pct']:+.2f}%  ·  {check['status']}  ·  510 сессий", 31, TEAL, True)
    rect(draw, (900, 165, 1835, 930), PANEL, 36, BORDER)
    rows = list(csv.DictReader((REPORT / "equity.csv").open()))
    values_strategy = [float(row["equity"]) for row in rows]
    values_benchmark = [float(row["buy_hold"]) for row in rows]
    all_values = values_strategy + values_benchmark
    low, high = min(all_values), max(all_values)
    def points(values):
        result = []
        for index, value in enumerate(values):
            x = 960 + index / (len(values) - 1) * 805
            y = 790 - (value - low) / (high - low) * 510
            result.append((x, y))
        return result
    for i in range(6):
        y = 280 + i * 100
        draw.line((960, y, 1765, y), fill=BORDER, width=1)
    draw.line(points(values_benchmark), fill=TEAL, width=5, joint="curve")
    draw.line(points(values_strategy), fill=PURPLE, width=6, joint="curve")
    text(draw, (960, 210), "ДВЕ КРИВЫЕ. ОДИН ПРОЗРАЧНЫЙ РАСЧЁТ.", 21, MUTED, True)
    pill(draw, (970, 845), "SMA 20 / 50", PURPLE)
    pill(draw, (1250, 845), "BUY & HOLD", TEAL)
    return image


def slide_02():
    image, draw = base_slide(2, "Задача", "Не прогноз, а воспроизводимое исследование", "Пользователь формулирует идею. Агент превращает её в данные, расчёт и проверяемые артефакты.")
    cards = [
        ("01", "Неоднозначность", "«Быстрая SMA выше медленной» — нужно зафиксировать окна, цену сигнала, момент сделки и издержки.", PURPLE),
        ("02", "Риск неверного бэктеста", "Look-ahead, комиссии и закрытие позиции способны изменить вывод сильнее, чем выбор окна.", RED),
        ("03", "Доверие к результату", "Одной красивой кривой мало: нужны buy & hold, слабые режимы и независимая сверка.", TEAL),
    ]
    for i, (num, title_value, body, accent) in enumerate(cards):
        x = 80 + i * 590
        rect(draw, (x, 320, x + 550, 690), PANEL, 28, BORDER)
        text(draw, (x + 32, 348), num, 20, accent, True)
        text(draw, (x + 32, 410), title_value, 32, WHITE, True, width=480)
        text(draw, (x + 32, 480), body, 25, MUTED, width=480)
    rect(draw, (80, 750, 1840, 940), PANEL_2, 28, BORDER)
    text(draw, (112, 782), "РЕЗУЛЬТАТ", 18, TEAL, True)
    text(draw, (112, 830), "HTML-отчёт  +  CSV/JSON  +  trace  +  PDF", 38, WHITE, True)
    text(draw, (112, 892), "Каждое число можно воспроизвести и проверить другой реализацией", 23, MUTED)
    return image


def slide_03():
    image, draw = base_slide(3, "Архитектура", "Три инструмента. Один управляемый цикл.", "Модель выбирает шаг только из разрешённых. Права, лимиты, данные и расчёты контролирует код.")
    rect(draw, (80, 315, 420, 520), PANEL_2, 26, BORDER)
    text(draw, (112, 345), "ЗАПРОС", 18, MUTED, True)
    text(draw, (112, 397), "Естественный\nязык", 34, WHITE, True)
    rect(draw, (600, 290, 1320, 550), PANEL, 28, PURPLE, 2)
    text(draw, (640, 325), "AGENT / HARNESS", 21, PURPLE, True)
    text(draw, (640, 382), "provider + model из конфига", 28, WHITE, True)
    bullet_list(draw, (640, 440), ["≤ 6 шагов", "≤ 2 попыток", "loop guard + trace"], 600, 21, MUTED, TEAL, 8)
    arrow(draw, (420, 418), (600, 418))
    tools = [
        (80, "01", "formalize_strategy", "Текст → StrategySpec\nPydantic + допущения", PURPLE),
        (670, "02", "backtest_moex_strategy", "ISS → сделки + метрики\nнезависимая сверка", TEAL),
        (1260, "03", "link_price_moves_to_news", "Движения → RSS-контекст\nбез причинности", BLUE),
    ]
    for x, num, name, body, accent in tools:
        rect(draw, (x, 650, x + 500, 895), PANEL, 26, BORDER)
        pill(draw, (x + 28, 675), num, accent, BG, 18)
        text(draw, (x + 28, 742), name, 24, WHITE, True, mono=True, width=450)
        text(draw, (x + 28, 800), body, 22, MUTED, width=450)
        arrow(draw, (960, 550), (x + 250, 650), accent, 3)
    return image


def slide_04():
    image, draw = base_slide(4, "Контракты", "Схема видна модели. Гарантии встроены в код.", "Каждая карточка содержит 8 полей: имя, описание, аргументы, не-модельные параметры, результат, ошибки, тип и отказ.")
    rows = [
        ("formalize_strategy", "text: 10…2000", "spec + assumptions", "validation / unsupported", PURPLE),
        ("backtest_moex_strategy", "{ } · состояние сессии", "metrics + 5 trades", "timeout / no data / mismatch", TEAL),
        ("link_price_moves_to_news", "top_n ≤ 10 · days ≤ 3", "≤ 3 ссылки / движение", "feed_error / timeout", BLUE),
    ]
    y = 315
    for name, args, result, errors, accent in rows:
        rect(draw, (80, y, 1290, y + 150), PANEL, 22, BORDER)
        draw.rectangle((80, y, 87, y + 150), fill=accent)
        text(draw, (112, y + 25), name, 24, WHITE, True, mono=True)
        text(draw, (112, y + 80), args, 20, MUTED, mono=True)
        text(draw, (680, y + 27), result, 22, TEXT, True)
        text(draw, (680, y + 79), errors, 19, MUTED)
        y += 172
    rect(draw, (1350, 315, 1840, 838), PANEL_2, 26, BORDER)
    card_title(draw, (1385, 350), "Harness", "Границы")
    bullet_list(draw, (1385, 445), ["Pydantic extra=forbid", "12 000 символов результата", "100 записей / RSS", "только read_only", "ключи — вне репозитория"], 410, 22, MUTED, TEAL, 20)
    rect(draw, (80, 875, 1840, 945), "#152B31", 18, "#28544E")
    text(draw, (110, 895), "Опасных торговых действий нет → подтверждение и идемпотентность не требуются", 23, TEAL, True)
    return image


def slide_05():
    image, draw = base_slide(5, "Формализация", "Свободный текст становится строгой спецификацией", "Неподдерживаемые условия отклоняются. Неуказанные параметры не скрываются, а попадают в список допущений.")
    rect(draw, (80, 310, 835, 805), PANEL, 28, BORDER)
    text(draw, (115, 345), "ЗАПРОС ПОЛЬЗОВАТЕЛЯ", 18, PURPLE, True)
    quote = "SBER, 2024-01-01 — 2025-12-31.\nПокупай, когда SMA(20) > SMA(50).\nКапитал 1 000 000 ₽, комиссия 5 б.п."
    text(draw, (115, 410), quote, 30, WHITE, width=660, spacing=1.5)
    text(draw, (115, 650), "Шорт, плечо, стопы и произвольные индикаторы → понятная ошибка с подсказкой", 22, MUTED, width=660)
    rect(draw, (900, 310, 1840, 805), "#0D1728", 28, BORDER)
    code = '{\n  "ticker": "SBER",\n  "date_from": "2024-01-01",\n  "date_to": "2025-12-31",\n  "fast_window": 20,\n  "slow_window": 50,\n  "initial_capital_rub": 1000000,\n  "fee_bps": 5,\n  "interval": 24\n}'
    text(draw, (940, 350), code, 25, TEAL, mono=True, spacing=1.38)
    rect(draw, (80, 855, 1840, 950), PANEL_2, 22, BORDER)
    text(draw, (112, 881), "ДОПУЩЕНИЕ ПО УМОЛЧАНИЮ", 17, AMBER, True)
    text(draw, (510, 878), "сигнал close(T) → исполнение open(T+1) · long only · целые акции", 24, WHITE, True)
    return image


def slide_06():
    image, draw = base_slide(6, "Методика", "Без подглядывания в будущее", "Одинаковые правила для стратегии и benchmark. Открытая позиция закрывается в конце периода.")
    steps = [
        (100, "T · CLOSE", "Считаем SMA\nтолько по доступным данным", PURPLE),
        (650, "SIGNAL", "fast > slow\nцелевое состояние long", BLUE),
        (1200, "T+1 · OPEN", "Покупка / продажа\n+ комиссия", TEAL),
    ]
    for x, label, body, accent in steps:
        rect(draw, (x, 330, x + 500, 560), PANEL, 26, BORDER)
        text(draw, (x + 30, 360), label, 20, accent, True)
        text(draw, (x + 30, 425), body, 28, WHITE, True, width=440)
    arrow(draw, (600, 445), (650, 445))
    arrow(draw, (1150, 445), (1200, 445))
    rect(draw, (80, 640, 900, 930), PANEL_2, 26, BORDER)
    text(draw, (115, 675), "ДЕНЕЖНЫЙ ЦИКЛ", 18, MUTED, True)
    text(draw, (115, 735), "qty = ⌊cash / (open × (1 + fee))⌋", 27, TEAL, mono=True, width=740)
    text(draw, (115, 805), "equity = cash + shares × close", 27, PURPLE, mono=True)
    rect(draw, (960, 640, 1840, 930), PANEL, 26, BORDER)
    text(draw, (995, 675), "МЕТРИКИ", 18, MUTED, True)
    bullet_list(draw, (995, 730), ["доходность · CAGR · просадка", "волатильность · Sharpe · exposure", "сделки · win rate · profit factor", "сравнение с buy & hold"], 790, 23, TEXT, TEAL, 10)
    return image


def slide_07(metrics, benchmark):
    image, draw = base_slide(7, "Результат", "Снижение риска не дало премии за риск", "SBER · SMA 20/50 · 1 000 000 ₽ · 5 б.п. · 510 торговых сессий")
    paste_rounded(image, REPORT / "equity.png", (80, 290, 1260, 875))
    kpi(draw, (1310, 290, 1570, 480), "SMA", f"{metrics['total_return_pct']:+.2f}%", "976 041 ₽", RED)
    kpi(draw, (1600, 290, 1840, 480), "B&H", f"{benchmark['total_return_pct']:+.2f}%", "1 101 849 ₽", TEAL)
    kpi(draw, (1310, 510, 1570, 700), "Просадка", f"{metrics['max_drawdown_pct']:.2f}%", f"B&H: {benchmark['max_drawdown_pct']:.2f}%", PURPLE)
    kpi(draw, (1600, 510, 1840, 700), "Сделки", str(metrics["closed_trades"]), f"win rate {metrics['win_rate_pct']:.2f}%", AMBER)
    rect(draw, (1310, 730, 1840, 875), PANEL_2, 22, BORDER)
    text(draw, (1340, 758), "ОТСТАВАНИЕ", 17, MUTED, True)
    text(draw, (1340, 804), f"{metrics['excess_return_pp']:.2f} п.п.", 39, RED, True)
    rect(draw, (80, 910, 1840, 970), "#291B2A", 18, "#5B3048")
    text(draw, (112, 929), "Вывод по периоду: волатильность ниже, но 6 из 7 закрытых сделок убыточны", 24, RED, True)
    return image


def slide_08(diagnostics):
    image, draw = base_slide(8, "Диагностика", "Где именно стратегия работает плохо", "Не общие рассуждения, а наблюдения, привязанные к сделкам, годам и метрикам.")
    paste_rounded(image, REPORT / "yearly.png", (80, 315, 950, 810))
    findings = [
        ("12,58 п.п.", "отставание от buy & hold", "SMA не компенсировала пропущенные движения и издержки", RED),
        ("14,29%", "прибыльных сделок", "Пересечения в боковых участках давали повторные потери", AMBER),
        ("−3,61%", "результат 2024 года", "2025: +1,26% — проблема не ограничивается одним годом", PURPLE),
    ]
    y = 315
    for value, label, body, accent in findings:
        rect(draw, (1000, y, 1840, y + 150), PANEL, 22, BORDER)
        text(draw, (1030, y + 25), value, 37, accent, True)
        text(draw, (1250, y + 26), label, 24, WHITE, True)
        text(draw, (1250, y + 73), body, 20, MUTED, width=550)
        y += 172
    rect(draw, (80, 865, 1840, 950), PANEL_2, 20, BORDER)
    text(draw, (112, 889), "Компромисс: просадка SMA −15,52% вместо −32,03% у B&H, но цена вопроса — доходность", 25, TEXT, True)
    return image


def slide_09(check):
    image, draw = base_slide(9, "Верификация", "Независимый бэктест — обязательный gate", "При любом значимом расхождении инструмент возвращает crosscheck_failed и не выдаёт отчёт как достоверный.")
    rect(draw, (80, 330, 620, 650), PANEL, 28, PURPLE, 2)
    text(draw, (115, 365), "РЕАЛИЗАЦИЯ A", 19, PURPLE, True)
    text(draw, (115, 425), "Event-driven", 36, WHITE, True)
    bullet_list(draw, (115, 495), ["скользящие суммы", "сделки день за днём", "cash + shares × close"], 460, 23, MUTED, PURPLE, 14)
    rect(draw, (1300, 330, 1840, 650), PANEL, 28, TEAL, 2)
    text(draw, (1335, 365), "РЕАЛИЗАЦИЯ B", 19, TEAL, True)
    text(draw, (1335, 425), "pandas + NumPy", 34, WHITE, True)
    bullet_list(draw, (1335, 495), ["rolling + shift", "отдельный денежный цикл", "независимые метрики"], 460, 23, MUTED, TEAL, 14)
    arrow(draw, (620, 490), (800, 490), PURPLE)
    arrow(draw, (1300, 490), (1120, 490), TEAL)
    rect(draw, (800, 380, 1120, 600), PANEL_2, 28, BORDER)
    text(draw, (960, 420), "COMPARE", 20, MUTED, True, anchor="ma")
    text(draw, (960, 485), check["status"], 52, TEAL, True, anchor="ma")
    text(draw, (960, 555), "каждая точка + сделка", 19, MUTED, anchor="ma")
    kpis = [("510", "точек капитала"), ("7", "закрытых сделок"), ("0,00 ₽", "расхождение equity"), ("0,00 ₽", "расхождение PnL")]
    for i, (value, label) in enumerate(kpis):
        x = 80 + i * 440
        rect(draw, (x, 740, x + 400, 910), PANEL, 22, BORDER)
        text(draw, (x + 30, 770), value, 42, TEAL, True)
        text(draw, (x + 30, 840), label, 20, MUTED)
    return image


def slide_10():
    image, draw = base_slide(10, "Новости", "Цена ↔ публикация. Совпадение ≠ причина", "Офлайн-демо: небольшая подборка реальных открытых публикаций. Онлайн: RSS с лимитами и обработкой ошибок.")
    cards = [
        ("20.12.2024", "+12,49%", "Рынок акций РФ рванул вверх на решении ЦБ не менять ставку", "Интерфакс · тот же день", TEAL),
        ("11.07.2024", "−6,57%", "Первый день торгов акциями Сбербанка без годовых дивидендов", "Интерфакс · тот же день", RED),
        ("12.02.2025", "+6,78%", "Публикация о динамике акций Сбербанка и разговоре лидеров РФ и США", "ПРАЙМ · тот же день", PURPLE),
    ]
    for i, (day, move, title_value, source, accent) in enumerate(cards):
        x = 80 + i * 590
        rect(draw, (x, 315, x + 550, 750), PANEL, 26, BORDER)
        text(draw, (x + 30, 345), day, 20, MUTED, True)
        text(draw, (x + 30, 398), move, 47, accent, True)
        text(draw, (x + 30, 490), title_value, 26, WHITE, True, width=490)
        text(draw, (x + 30, 675), source, 19, MUTED)
    rect(draw, (80, 810, 1840, 945), "#2B2617", 24, "#665324")
    text(draw, (115, 840), "ГРАНИЦА ВЫВОДА", 18, AMBER, True)
    text(draw, (115, 886), "Только календарное и лексическое совпадение. Причинно-следственная связь не установлена.", 27, WHITE, True)
    return image


def slide_11():
    image, draw = base_slide(11, "Надёжность", "Ошибка показана. Восстановление проверено.", "Демо воспроизводит отказ инструмента, технический повтор и успешное завершение без выдуманных данных.")
    rect(draw, (80, 310, 1130, 820), "#080E18", 26, BORDER)
    text(draw, (115, 345), "TERMINAL · DEMO", 18, MUTED, True, mono=True)
    terminal = "$ moex-agent demo --cache-only \\\n    --fault backtest_moex_strategy=timeout\n\n→ formalize_strategy\n  ✓ успешно\n→ backtest_moex_strategy\n  ! timeout → технический повтор\n  ✓ восстановлено\n→ link_price_moves_to_news\n  ✓ успешно\n\nPASS · report.html готов"
    text(draw, (115, 410), terminal, 22, TEAL, mono=True, spacing=1.4)
    levels = [
        ("01", "Функции", "схемы · расчёты · ошибки"),
        ("02", "Сценарий", "3 вызова → отчёт"),
        ("03", "Отказы", "timeout · cache · loop guard"),
    ]
    y = 310
    for num, title_value, body in levels:
        rect(draw, (1260, y, 1840, y + 145), PANEL, 22, BORDER)
        pill(draw, (1290, y + 25), num, PURPLE, BG, 17)
        text(draw, (1380, y + 24), title_value, 26, WHITE, True)
        text(draw, (1380, y + 75), body, 19, MUTED)
        y += 168
    rect(draw, (1260, 820, 1840, 930), "#15302D", 22, "#2B6159")
    text(draw, (1300, 848), "28 passed", 38, TEAL, True)
    text(draw, (1570, 858), "0 сетевых тестов", 19, MUTED)
    return image


def slide_12():
    image, draw = base_slide(12, "Итог", "Готово к живому демо и защите", "Рабочий агент, проверенные артефакты и честные границы исследования.")
    rect(draw, (80, 305, 790, 855), PANEL, 28, BORDER)
    card_title(draw, (115, 340), "Чек-лист", "9 / 9 закрыто", TEAL)
    bullet_list(draw, (115, 455), ["3 контракта + валидация", "таймаут + повтор + trace", "лимиты шагов и контекста", "провайдер в конфиге", "ключей нет в проекте", "независимая сверка PASS"], 620, 24, TEXT, TEAL, 17)
    rect(draw, (850, 305, 1840, 590), PANEL_2, 28, BORDER)
    text(draw, (885, 340), "ЧТО СДАЁМ", 18, PURPLE, True)
    text(draw, (885, 395), "README · src · tests · data · reports", 28, WHITE, True)
    text(draw, (885, 460), "report.html · crosscheck.json · trace.jsonl", 24, TEXT, mono=True)
    text(draw, (885, 515), "MOEX_Strategy_Agent.pdf", 24, TEXT, mono=True)
    rect(draw, (850, 630, 1840, 855), PANEL, 28, BORDER)
    text(draw, (885, 660), "СЛЕДУЮЩИЙ ШАГ", 18, AMBER, True)
    bullet_list(draw, (885, 715), ["walk-forward + out-of-sample", "дивиденды, налоги, лоты, slippage", "матрица чувствительности параметров"], 900, 23, MUTED, AMBER, 10)
    rect(draw, (80, 900, 1840, 975), "#211C36", 20, "#4A3E77")
    text(draw, (112, 923), "Не инвестиционная рекомендация. Прошлая доходность не гарантирует будущую.", 25, PURPLE, True)
    return image


def build():
    OUT.mkdir(exist_ok=True)
    metrics = json.loads((REPORT / "metrics.json").read_text(encoding="utf-8"))
    check = json.loads((REPORT / "crosscheck.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((REPORT / "diagnostics.json").read_text(encoding="utf-8"))
    slides = [
        slide_01(metrics["metrics"], check),
        slide_02(), slide_03(), slide_04(), slide_05(), slide_06(),
        slide_07(metrics["metrics"], metrics["buy_hold"]),
        slide_08(diagnostics), slide_09(check), slide_10(), slide_11(), slide_12(),
    ]
    slides[0].save(
        OUT / "MOEX_Strategy_Agent.pdf", "PDF", resolution=150,
        save_all=True, append_images=slides[1:],
    )
    print(f"Создан PDF: {len(slides)} слайдов")
    print(OUT / "MOEX_Strategy_Agent.pdf")


if __name__ == "__main__":
    build()
