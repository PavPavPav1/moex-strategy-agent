import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .gigachat_provider import GigaChatProvider
from .providers import OpenAICompatibleProvider, ProviderError, ScriptedProvider, ProviderResponse, ToolCall
from .models import DISCLAIMER
from .tools import ToolExecutor


SYSTEM_PROMPT = """Ты MOEX Strategy Agent. Формализуй только long-only стратегию пересечения SMA и используй доступные инструменты.
Порядок: formalize_strategy → backtest_moex_strategy → link_price_moves_to_news. Не выдумывай данные при ошибке.
Исполнение сигнала и метрики определяет код, а не ты. Объясняй слабые места по метрикам.
Новости связывай с движением только как временное совпадение, никогда не утверждай причинность.
Всегда добавляй, что исследование не является инвестиционной рекомендацией. Не совершай торговых действий.
"""


class StrategyAgent:
    def __init__(self, config: Dict[str, Any], executor: ToolExecutor, user_text: str, event_handler: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.warnings = []
        self.config = config
        self.executor = executor
        self.user_text = user_text
        self.executor.runtime.request_text = user_text
        self.event_handler = event_handler
        self.executor.event_handler = event_handler
        provider_name = config.get("provider", "scripted")
        if provider_name == "scripted":
            self.provider = ScriptedProvider(user_text)
        elif provider_name == "gigachat":
            self.provider = GigaChatProvider(config)
        elif provider_name == "openai_compatible":
            self.provider = OpenAICompatibleProvider(config)
        else:
            raise ValueError(f"Неизвестный provider: {provider_name}")

    def _emit(self, event: str, **fields: Any) -> None:
        if self.event_handler:
            self.event_handler(event, fields)

    def _log_agent(self, event: str, step: int, **fields: Any) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, "step": step, **fields}
        with self.executor.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def run(self) -> str:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self.user_text},
        ]
        max_steps = max(1, min(int(self.config.get("max_steps", 6)), 12))
        recent_calls: List[str] = []
        final = "Лимит шагов исчерпан; цикл остановлен без выдумывания результата."
        for step in range(1, max_steps + 1):
            if not self.config.get("news_enabled", True) and self.executor.runtime.session.result is not None:
                result = self.executor.runtime.session.result
                metrics = result['metrics']
                final = (f"Бэктест {result['strategy']['ticker']} завершён: доходность {metrics['total_return_pct']:+.2f}%, "
                         f"buy & hold {result['buy_hold']['total_return_pct']:+.2f}%, "
                         f"просадка {metrics['max_drawdown_pct']:.2f}%, сделок {metrics['closed_trades']}. "
                         f"Сверка: {result['crosscheck']['status']}.\nПоиск новостей отключён.\n"
                         f"HTML-отчёт: {self.executor.runtime.session.run_dir / 'report.html'}\n\n{DISCLAIMER}")
                break
            try:
                response = self.provider.respond(messages, [schema for schema in self.executor.schemas() if self.config.get("news_enabled", True) or schema["function"]["name"] != "link_price_moves_to_news"], self.executor.runtime.session)
            except ProviderError as exc:
                self.warnings.append(str(exc))
                self._log_agent("provider_error", step, message=str(exc))
                session = self.executor.runtime.session
                if session.result is not None:
                    result = session.result
                    metrics = result['metrics']
                    news_status = "Новости обработаны." if session.news is not None else "Шаг 3/3 (новости) не выполнен."
                    final = (
                        f"Бэктест {result['strategy']['ticker']} завершён: доходность {metrics['total_return_pct']:+.2f}%, "
                        f"buy & hold {result['buy_hold']['total_return_pct']:+.2f}%, "
                        f"просадка {metrics['max_drawdown_pct']:.2f}%, сделок {metrics['closed_trades']}. "
                        f"Сверка: {result['crosscheck']['status']}.\n"
                        f"GigaChat недоступен: {exc}. Расчёт и HTML сохранены. {news_status}\n"
                        f"HTML-отчёт: {session.run_dir / 'report.html'}\n\n{DISCLAIMER}"
                    )
                else:
                    final = f"Модель недоступна: {exc}. Бэктест не выполнен, данные не выдумывались."
                break
            if not response.tool_calls and self.executor.runtime.session.strategy is not None and self.executor.runtime.session.result is None:
                # A text promise is not an executed backtest. Complete the required step.
                response = ProviderResponse(tool_calls=[ToolCall("backtest_moex_strategy", {}, f"required_backtest_{step}")])
            if not response.tool_calls:
                final = response.content or "Модель вернула пустой ответ."
                self._log_agent("final", step, content=final)
                break
            for call in response.tool_calls[:2]:
                if call.name == "link_price_moves_to_news" and not self.config.get("news_enabled", True):
                    self._log_agent("tool_disabled", step, tool=call.name)
                    continue
                signature = json.dumps({"name": call.name, "args": call.arguments}, sort_keys=True, ensure_ascii=False)
                if len(recent_calls) >= 2 and recent_calls[-1] == signature and recent_calls[-2] == signature:
                    final = "Обнаружен повтор одинакового вызова три раза подряд. Цикл остановлен."
                    self._log_agent("loop_guard", step, tool=call.name)
                    self._write_summary(final, "loop_guard")
                    return final
                recent_calls.append(signature)
                messages.append({
                    "role": "assistant", "content": response.content,
                    "tool_calls": [{
                        "id": call.call_id, "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
                    }],
                })
                self._emit("tool_call", tool=call.name, args=call.arguments, step=step)
                result = self.executor.execute(call.name, call.arguments, step)
                if "error" in result:
                    self._emit("tool_error", tool=call.name, error=result["error"])
                    if call.name != "link_price_moves_to_news":
                        error = result["error"]
                        final = (f"Бэктест не выполнен. {error['message']}. {error['hint']}. "
                                 "Технические попытки завершены; восстановление не подтверждено.")
                        self._write_summary(final, "failed")
                        return final
                else:
                    self._emit("tool_result", tool=call.name, result=result)
                messages.append({
                    "role": "tool", "tool_call_id": call.call_id, "name": call.name,
                    "content": json.dumps(result, ensure_ascii=False),
                })
        status = "incomplete"
        if self.executor.runtime.session.result is not None:
            status = "completed_with_warnings" if self.warnings else "completed"
        self._write_summary(final, status)
        return final

    def _write_summary(self, final: str, status: str) -> None:
        session = self.executor.runtime.session
        summary = {
            "status": status,
            "warnings": self.warnings,
            "provider": self.config.get("provider"),
            "model": self.config.get("model"),
            "response": final,
            "run_dir": str(session.run_dir),
            "report": str(session.run_dir / "report.html") if session.result else None,
        }
        (session.run_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
