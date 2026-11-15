import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .backtest import run_backtest
from .diagnostics import build_diagnostics
from .errors import ServiceTimeout, ToolProblem
from .models import AgentSession, DISCLAIMER
from .moex_client import MOEXClient
from .news import NewsClient
from .strategy_parser import formalize_strategy
from .validation import crosscheck


class FormalizeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=10, max_length=2000, description="Стратегия на русском или английском: тикер, период, SMA, капитал и комиссия")


class BacktestArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top_n: int = Field(default=5, ge=1, le=10, description="Сколько самых резких дневных движений рассмотреть")
    window_days: int = Field(default=1, ge=0, le=3, description="Допустимое расстояние между днём движения и публикацией")


@dataclass
class ToolRuntime:
    session: AgentSession
    moex: MOEXClient
    news: NewsClient
    cache_only: bool = False


@dataclass
class ToolContract:
    name: str
    description: str
    args_model: Type[BaseModel]
    handler: Callable[[BaseModel, ToolRuntime], Dict[str, Any]]
    not_from_model: str
    result_limit: str
    errors: str
    kind: str = "read_only"
    failure_policy: str = "До двух технических повторов только для retryable-ошибок; затем структурированная ошибка"


def formalize_tool(args: FormalizeArgs, runtime: ToolRuntime) -> Dict[str, Any]:
    spec, assumptions = formalize_strategy(args.text)
    runtime.session.strategy = spec
    runtime.session.assumptions = assumptions
    return {
        "status": "ok",
        "strategy": spec.model_dump(mode="json"),
        "assumptions": assumptions,
        "message": "Стратегия формализована. Проверь допущения перед бэктестом.",
    }


def backtest_tool(args: BacktestArgs, runtime: ToolRuntime) -> Dict[str, Any]:
    if runtime.session.strategy is None:
        raise ToolProblem("missing_state", "Сначала нужно формализовать стратегию", "Вызови formalize_strategy")
    spec = runtime.session.strategy
    data = runtime.moex.fetch(spec)
    result = run_backtest(spec, data.candles)
    verification = crosscheck(spec, data.candles, result)
    if verification["status"] != "PASS":
        raise ToolProblem("crosscheck_failed", "Независимые реализации бэктеста разошлись", "Не используй результат до исправления расчёта")
    result["crosscheck"] = verification
    result["diagnostics"] = build_diagnostics(result)
    result["data"] = {
        "source": data.source,
        "source_url": data.source_url,
        "cache_path": data.cache_path,
        "warning": data.warning,
        "fetched_at": data.fetched_at,
        "sha256": data.sha256,
    }
    runtime.session.data = data
    runtime.session.result = result
    from .report import generate_report
    artifacts = generate_report(runtime.session)
    metrics = result["metrics"]
    return {
        "status": "ok",
        "data": result["data"],
        "period": result["period"],
        "metrics": metrics,
        "buy_hold": result["buy_hold"],
        "crosscheck": verification,
        "weaknesses": result["diagnostics"]["weaknesses"],
        "trades_preview": result["trades"][:5],
        "trades_omitted": max(0, len(result["trades"]) - 5),
        "artifacts": artifacts,
        "disclaimer": DISCLAIMER,
    }


def news_tool(args: NewsArgs, runtime: ToolRuntime) -> Dict[str, Any]:
    if runtime.session.result is None:
        raise ToolProblem("missing_state", "Сначала нужен бэктест", "Вызови backtest_moex_strategy")
    result = runtime.session.result
    news = runtime.news.match(
        result["price_moves"], result["strategy"]["ticker"], args.top_n, args.window_days, runtime.cache_only
    )
    runtime.session.news = news
    from .report import generate_report
    artifacts = generate_report(runtime.session)
    return {
        "status": "ok",
        "matched_moves": news["matched_moves"],
        "rss_items_checked": news["rss_items_checked"],
        "source": news["source"],
        "warning": news["warning"],
        "errors": news["errors"],
        "matches": news["matches"],
        "non_causality_notice": news["non_causality_notice"],
        "artifacts": artifacts,
    }


def build_contracts() -> List[ToolContract]:
    return [
        ToolContract(
            name="formalize_strategy",
            description=(
                "Формализует long-only стратегию пересечения двух SMA из естественного языка. "
                "Используй первым для запроса на бэктест. Не используй для произвольных индикаторов, шорта, плеча, стопов. "
                "Возвращает проверенную спецификацию и явные допущения."
            ),
            args_model=FormalizeArgs,
            handler=formalize_tool,
            not_from_model="Правила исполнения, поддерживаемый рынок TQBR и дневной интервал заданы кодом",
            result_limit="1 спецификация и не более 8 допущений",
            errors="validation, unsupported_strategy",
        ),
        ToolContract(
            name="backtest_moex_strategy",
            description=(
                "Загружает дневные свечи MOEX ISS для стратегии из сессии, считает сделки и метрики, сравнивает с buy & hold, "
                "сверяет каждую точку капитала с независимой pandas-реализацией и создаёт отчёт. "
                "Используй только после formalize_strategy. Не выбирай тикер и пути к файлам в этом вызове."
            ),
            args_model=BacktestArgs,
            handler=backtest_tool,
            not_from_model="Спецификация, каталог кэша и отчёта, URL ISS, права и независимая сверка берутся из сессии/конфига",
            result_limit="Метрики, максимум 5 сделок и пути к артефактам; полный CSV остаётся на диске",
            errors="missing_state, validation, not_found, timeout, service_unavailable, insufficient_data, crosscheck_failed",
        ),
        ToolContract(
            name="link_price_moves_to_news",
            description=(
                "Находит публикации из открытых RSS рядом с крупнейшими дневными движениями цены после бэктеста. "
                "Сопоставляет только дату и название компании/тикер. Не используй для вывода о причине движения. "
                "Возвращает ссылки и явное предупреждение об отсутствии доказанной причинности."
            ),
            args_model=NewsArgs,
            handler=news_tool,
            not_from_model="Список доверенных RSS, таймауты, лимит 100 записей на ленту и правила сопоставления заданы кодом",
            result_limit="До 10 движений, до 3 новостей на движение, до 300 RSS-записей всего",
            errors="missing_state, timeout, feed_error, not_found",
            failure_policy="Ошибка одной ленты фиксируется и не отменяет остальные; сетевой сбой может использовать маркированный снапшот",
        ),
    ]


class ToolExecutor:
    def __init__(self, runtime: ToolRuntime, attempts: int = 2, timeout_seconds: int = 45, max_result_chars: int = 12000, faults: Optional[Dict[str, List[str]]] = None):
        self.runtime = runtime
        self.contracts = {contract.name: contract for contract in build_contracts()}
        self.attempts = max(1, min(attempts, 3))
        self.timeout_seconds = timeout_seconds
        self.max_result_chars = max_result_chars
        self.faults = {name: list(values) for name, values in (faults or {}).items()}
        self.trace_path = runtime.session.run_dir / "trace.jsonl"
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)

    def schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": contract.name,
                    "description": contract.description,
                    "parameters": contract.args_model.model_json_schema(),
                },
            }
            for contract in self.contracts.values()
        ]

    def export_contracts(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": contract.name,
                "description": contract.description,
                "arguments": contract.args_model.model_json_schema(),
                "not_from_model": contract.not_from_model,
                "result_and_limit": contract.result_limit,
                "errors": contract.errors,
                "type": contract.kind,
                "failure_policy": contract.failure_policy,
            }
            for contract in self.contracts.values()
        ]

    def _log(self, event: str, step: int, **fields: Any) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, "step": step, **fields}
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _call_with_timeout(self, handler: Callable, args: BaseModel) -> Dict[str, Any]:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(handler, args, self.runtime)
        try:
            return future.result(timeout=self.timeout_seconds)
        except FutureTimeout as exc:
            future.cancel()
            raise ServiceTimeout("Инструмент превысил лимит времени") from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def execute(self, name: str, raw_args: Dict[str, Any], step: int = 0) -> Dict[str, Any]:
        started = time.monotonic()
        contract = self.contracts.get(name)
        if contract is None:
            return ToolProblem("unknown_tool", f"Неизвестный инструмент: {name}", "Выбери инструмент из tools/list").as_dict()
        try:
            args = contract.args_model.model_validate(raw_args)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
            )
            result = ToolProblem("validation", details[:800], "Исправь аргументы по JSON-схеме инструмента").as_dict()
            self._log("tool_error", step, tool=name, args=raw_args, error=result["error"], will_retry=False)
            return result
        for attempt in range(1, self.attempts + 1):
            try:
                queue = self.faults.get(name)
                if queue:
                    kind = queue.pop(0)
                    if kind == "timeout":
                        raise ServiceTimeout(f"{name}: смодированный таймаут")
                    raise ToolProblem(kind, f"{name}: смодированная ошибка {kind}", "Проверь сценарий отказа", kind == "service_unavailable")
                result = self._call_with_timeout(contract.handler, args)
                encoded = json.dumps(result, ensure_ascii=False)
                if len(encoded) > self.max_result_chars:
                    result = {
                        "status": "ok",
                        "summary": "Результат сокращён из-за лимита контекста",
                        "original_chars": len(encoded),
                        "artifacts": result.get("artifacts", {}),
                    }
                self._log("tool_result", step, tool=name, args=raw_args, attempt=attempt, duration_ms=round((time.monotonic() - started) * 1000), result_chars=len(encoded), error=None)
                return result
            except ToolProblem as exc:
                will_retry = exc.retryable and attempt < self.attempts
                self._log("tool_error", step, tool=name, args=raw_args, attempt=attempt, error=exc.as_dict()["error"], will_retry=will_retry)
                if will_retry:
                    time.sleep(0.05 * (2 ** (attempt - 1)))
                    continue
                return exc.as_dict()
            except Exception:
                error = {"type": "internal_error", "message": "Внутренняя ошибка инструмента", "hint": "Посмотри trace и повтори после исправления", "retryable": False}
                self._log("tool_error", step, tool=name, args=raw_args, attempt=attempt, error=error, will_retry=False)
                return {"error": error}
        return {"error": {"type": "internal_error", "message": "Неожиданное завершение вызова", "hint": "Останови цикл", "retryable": False}}
