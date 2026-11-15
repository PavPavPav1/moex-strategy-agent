import json
import time

from moex_agent.agent import StrategyAgent
from moex_agent.cli import DEMO_STRATEGY
from moex_agent.models import AgentSession, DataBundle, DISCLAIMER
from moex_agent.providers import ProviderResponse, ToolCall
from moex_agent.tools import ToolExecutor, ToolRuntime


class FakeMoex:
    def __init__(self, candles):
        self.candles = candles

    def fetch(self, spec):
        return DataBundle(self.candles, "test_iss_snapshot", "https://iss.moex.com/test", fetched_at="2024-01-01T00:00:00+00:00", sha256="abc")


class FakeNews:
    def match(self, moves, ticker, top_n, window_days, cache_only=False):
        return {
            "ticker": ticker, "window_days": window_days, "matches": [], "matched_moves": 0,
            "rss_items_checked": 0, "source": "test", "warning": None, "errors": [],
            "non_causality_notice": "Это не доказательство причины движения.",
        }


def runtime_for(tmp_path, candles):
    return ToolRuntime(AgentSession(tmp_path), FakeMoex(candles), FakeNews(), cache_only=True)


def test_three_clear_read_only_contracts(tmp_path, candles):
    executor = ToolExecutor(runtime_for(tmp_path, candles))
    contracts = executor.export_contracts()
    assert len(contracts) == 3
    assert all(item["type"] == "read_only" for item in contracts)
    assert all(item["not_from_model"] for item in contracts)
    schemas = executor.schemas()
    assert schemas[2]["function"]["parameters"]["properties"]["top_n"]["maximum"] == 10


def test_validation_error_is_regular_result(tmp_path, candles):
    executor = ToolExecutor(runtime_for(tmp_path, candles))
    result = executor.execute("link_price_moves_to_news", {"top_n": 99})
    assert result["error"]["type"] == "validation"
    assert "hint" in result["error"]


def test_missing_state_is_actionable(tmp_path, candles):
    executor = ToolExecutor(runtime_for(tmp_path, candles))
    result = executor.execute("backtest_moex_strategy", {})
    assert result["error"]["type"] == "missing_state"
    assert "formalize_strategy" in result["error"]["hint"]


def test_timeout_is_retried_and_logged(tmp_path, candles):
    executor = ToolExecutor(runtime_for(tmp_path, candles), attempts=2, faults={"formalize_strategy": ["timeout"]})
    result = executor.execute("formalize_strategy", {"text": DEMO_STRATEGY})
    assert result["status"] == "ok"
    events = [json.loads(line) for line in executor.trace_path.read_text(encoding="utf-8").splitlines()]
    assert any(event["event"] == "tool_error" and event["will_retry"] for event in events)
    assert events[-1]["event"] == "tool_result"


def test_permanent_timeout_does_not_crash(tmp_path, candles):
    executor = ToolExecutor(runtime_for(tmp_path, candles), attempts=2, faults={"formalize_strategy": ["timeout", "timeout"]})
    result = executor.execute("formalize_strategy", {"text": DEMO_STRATEGY})
    assert result["error"]["type"] == "timeout"
    assert result["error"]["retryable"] is True


def test_execution_timeout_is_structured(tmp_path, candles):
    executor = ToolExecutor(runtime_for(tmp_path, candles), attempts=1, timeout_seconds=0.01)
    def slow(args, runtime):
        time.sleep(0.1)
        return {"status": "ok"}
    executor.contracts["formalize_strategy"].handler = slow
    result = executor.execute("formalize_strategy", {"text": DEMO_STRATEGY})
    assert result["error"]["type"] == "timeout"


def test_tool_result_size_is_bounded(tmp_path, candles):
    executor = ToolExecutor(runtime_for(tmp_path, candles), max_result_chars=100)
    executor.contracts["formalize_strategy"].handler = lambda args, runtime: {"status": "ok", "large": "x" * 1000}
    result = executor.execute("formalize_strategy", {"text": DEMO_STRATEGY})
    assert result["original_chars"] > 100
    assert "large" not in result


def test_backtest_and_report_integration(tmp_path, candles):
    runtime = runtime_for(tmp_path, candles)
    runtime.session.strategy = __import__("moex_agent.models", fromlist=["StrategySpec"]).StrategySpec(
        ticker="SBER", date_from="2024-01-01", date_to="2024-05-31",
        fast_window=2, slow_window=3, initial_capital_rub=100_000, fee_bps=5,
    )
    executor = ToolExecutor(runtime)
    result = executor.execute("backtest_moex_strategy", {})
    assert result["status"] == "ok"
    assert result["crosscheck"]["status"] == "PASS"
    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert DISCLAIMER in report
    assert "Кривая капитала" in report
    assert (tmp_path / "trades.csv").exists()
    assert (tmp_path / "manifest.json").exists()


class RepeatingProvider:
    def respond(self, messages, tools, session):
        return ProviderResponse(tool_calls=[ToolCall("formalize_strategy", {"text": DEMO_STRATEGY}, "same")])


def test_loop_guard_stops_third_identical_call(tmp_path, candles):
    executor = ToolExecutor(runtime_for(tmp_path, candles))
    agent = StrategyAgent({"provider": "scripted", "model": "test", "max_steps": 6}, executor, DEMO_STRATEGY)
    agent.provider = RepeatingProvider()
    response = agent.run()
    assert "повтор" in response
    events = [json.loads(line) for line in executor.trace_path.read_text(encoding="utf-8").splitlines()]
    assert sum(event["event"] == "tool_result" for event in events) == 2
    assert any(event["event"] == "loop_guard" for event in events)
