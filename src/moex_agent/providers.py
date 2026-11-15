import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from .models import AgentSession, DISCLAIMER


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]
    call_id: str


@dataclass
class ProviderResponse:
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None


class ProviderError(Exception):
    pass


class ScriptedProvider:
    def __init__(self, user_text: str):
        self.user_text = user_text

    def respond(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], session: AgentSession) -> ProviderResponse:
        last_tool = next((message for message in reversed(messages) if message.get("role") == "tool"), None)
        if last_tool:
            try:
                payload = json.loads(last_tool["content"])
            except ValueError:
                payload = {}
            if "error" in payload and last_tool.get("name") == "backtest_moex_strategy" and session.result is None:
                error = payload["error"]
                return ProviderResponse(content=(
                    f"Бэктест не выполнен: {error['message']}. {error['hint']}. "
                    "Я не подставлял выдуманные котировки или метрики."
                ))
        if session.strategy is None:
            return ProviderResponse(tool_calls=[ToolCall("formalize_strategy", {"text": self.user_text}, "call_formalize")])
        if session.result is None:
            return ProviderResponse(tool_calls=[ToolCall("backtest_moex_strategy", {}, "call_backtest")])
        if session.news is None and not (last_tool and last_tool.get("name") == "link_price_moves_to_news"):
            return ProviderResponse(tool_calls=[ToolCall("link_price_moves_to_news", {"top_n": 5, "window_days": 1}, "call_news")])
        result = session.result
        metrics = result["metrics"]
        benchmark = result["buy_hold"]
        news_note = ""
        if session.news:
            news_note = f" Новости: совпадения найдены для {session.news['matched_moves']} из 5 движений; причинность не утверждается."
        return ProviderResponse(content=(
            f"Готово. {result['strategy']['ticker']} SMA {result['strategy']['fast_window']}/{result['strategy']['slow_window']}: "
            f"доходность {metrics['total_return_pct']:+.2f}%, buy & hold {benchmark['total_return_pct']:+.2f}%, "
            f"максимальная просадка {metrics['max_drawdown_pct']:.2f}%, закрытых сделок {metrics['closed_trades']}. "
            f"Независимая сверка: {result['crosscheck']['status']}, расхождение капитала ≤ "
            f"{result['crosscheck']['max_abs_equity_difference_rub']} ₽.{news_note}\n\n"
            f"Отчёт: {session.run_dir / 'report.html'}\n\n{DISCLAIMER}"
        ))


class OpenAICompatibleProvider:
    def __init__(self, config: Dict[str, Any]):
        self.base_url = config["base_url"]
        self.model = config["model"]
        self.temperature = float(config.get("temperature", 0))
        self.api_key = os.environ.get(config.get("api_key_env", "LLM_API_KEY"), "")
        if not self.api_key:
            raise ProviderError(f"Не задана переменная {config.get('api_key_env', 'LLM_API_KEY')}")
        self.http = requests.Session()

    def respond(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], session: AgentSession) -> ProviderResponse:
        try:
            response = self.http.post(
                self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "temperature": self.temperature,
                    "stream": False,
                },
                timeout=45,
            )
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            raise ProviderError("LLM-провайдер вернул ошибку или непонятный ответ") from exc
        calls = []
        for raw in message.get("tool_calls") or []:
            try:
                arguments = json.loads(raw["function"].get("arguments") or "{}")
                calls.append(ToolCall(raw["function"]["name"], arguments, raw.get("id", str(uuid.uuid4()))))
            except (KeyError, ValueError, TypeError) as exc:
                raise ProviderError("Не удалось разобрать tool_call провайдера") from exc
        return ProviderResponse(content=message.get("content"), tool_calls=calls)
