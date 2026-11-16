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


class PromiseAfterFormalization:
    def respond(self, messages, tools, session):
        if session.strategy is None:
            return ProviderResponse(tool_calls=[ToolCall('formalize_strategy', {'text': DEMO_STRATEGY}, 'formalize')])
        return ProviderResponse(content='Попробую снова загрузить исторические данные.')


def test_text_promise_cannot_skip_backtest_and_exhausted_retries_stop(tmp_path, candles):
    executor = ToolExecutor(runtime_for(tmp_path, candles), attempts=2,
                            faults={'backtest_moex_strategy': ['timeout', 'timeout']})
    progress = []
    agent = StrategyAgent({'provider': 'scripted', 'model': 'test'}, executor, DEMO_STRATEGY,
                          lambda event, fields: progress.append(event))
    agent.provider = PromiseAfterFormalization()
    response = agent.run()
    assert 'Бэктест не выполнен' in response
    assert 'Попробую' not in response
    assert progress.count('tool_retry') == 1
    summary = json.loads((tmp_path / 'run_summary.json').read_text())
    assert summary['status'] == 'failed'
    assert summary['report'] is None


def test_retry_after_timeout_does_not_overlap_workers(tmp_path, candles):
    executor = ToolExecutor(runtime_for(tmp_path, candles), attempts=2, timeout_seconds=0.01)
    active = []
    def slow(args, runtime):
        active.append(1)
        assert len(active) == 1
        time.sleep(0.04)
        active.pop()
        return {'status': 'ok'}
    executor.contracts['formalize_strategy'].handler = slow
    result = executor.execute('formalize_strategy', {'text': DEMO_STRATEGY})
    assert result['error']['type'] == 'timeout'
    assert active == []


def test_cli_exhausted_retry_is_failure_not_recovered(tmp_path, candles, monkeypatch, capsys):
    import pytest
    from moex_agent import cli
    executor = ToolExecutor(runtime_for(tmp_path, candles), attempts=2,
                            faults={'backtest_moex_strategy': ['timeout', 'timeout']})
    agent = StrategyAgent({'provider': 'scripted', 'model': 'test'}, executor, DEMO_STRATEGY)
    # Old successful events must not affect this invocation's retry summary.
    executor._log('tool_result', 2, tool='backtest_moex_strategy')
    monkeypatch.setattr(cli, '_build_agent', lambda args: agent)
    monkeypatch.setattr('sys.argv', ['moex-agent', 'demo', '--cache-only'])
    with pytest.raises(SystemExit) as error:
        cli.main()
    output = capsys.readouterr().out
    assert error.value.code == 1
    assert 'не восстановлено' in output
    assert '→ восстановлено' not in output
    assert 'подтверждён успешный результат' not in output


def test_model_cannot_drop_unsupported_original_condition(tmp_path, candles):
    executor = ToolExecutor(runtime_for(tmp_path, candles))
    agent = StrategyAgent({'provider': 'scripted'}, executor, DEMO_STRATEGY + ' Фильтр RSI(14) < 30.')
    # Simulate a model that removes the RSI filter from the tool arguments.
    agent.provider = RepeatingProvider()
    response = agent.run()
    assert 'Неподдерживаемый' in response
    assert executor.runtime.session.strategy is None
    assert executor.runtime.session.result is None
    assert not (tmp_path / 'report.html').exists()


def test_crosscheck_failure_blocks_html(tmp_path, candles, monkeypatch):
    import moex_agent.tools as tool_module
    runtime = runtime_for(tmp_path, candles)
    executor = ToolExecutor(runtime)
    executor.execute('formalize_strategy', {'text': DEMO_STRATEGY})
    monkeypatch.setattr(tool_module, 'crosscheck', lambda *args: {'status': 'FAIL'})
    result = executor.execute('backtest_moex_strategy', {})
    assert result['error']['type'] == 'crosscheck_failed'
    assert runtime.session.result is None
    assert not (tmp_path / 'report.html').exists()


def test_model_cannot_reverse_original_signal(tmp_path, candles):
    executor = ToolExecutor(runtime_for(tmp_path, candles))
    agent = StrategyAgent({'provider': 'scripted'}, executor,
                          'SBER 2024-01-01 2025-12-31. Покупай когда SMA(20) ниже SMA(50).')
    agent.provider = RepeatingProvider()
    response = agent.run()
    assert 'отличается' in response
    assert not (tmp_path / 'report.html').exists()


def test_step_results_print_in_order_before_provider_outage(tmp_path, candles, capsys):
    from moex_agent.cli import _show_tool_event
    from moex_agent.providers import ProviderError
    runtime = runtime_for(tmp_path, candles)
    executor = ToolExecutor(runtime)
    scripted = __import__('moex_agent.providers', fromlist=['ScriptedProvider']).ScriptedProvider(DEMO_STRATEGY)
    class OutageAfterBacktest:
        def respond(self, messages, tools, session):
            if session.result is not None:
                output = capsys.readouterr().out
                assert output.index('[1/3]') < output.index('[2/3]') < output.index('HTML-отчёт:')
                assert 'Сделок:' in output
                raise ProviderError('таймаут тестового провайдера')
            return scripted.respond(messages, tools, session)
    agent = StrategyAgent({'provider': 'scripted'}, executor, DEMO_STRATEGY,
                          lambda event, fields: _show_tool_event(event, fields, runtime.session))
    agent.provider = OutageAfterBacktest()
    response = agent.run()
    assert 'Расчёт и HTML сохранены' in response
    assert 'Шаг 3/3 (новости) не выполнен' in response
    assert str(tmp_path / 'report.html') in response
    summary = json.loads((tmp_path / 'run_summary.json').read_text())
    assert summary['status'] == 'completed_with_warnings'
    assert (tmp_path / 'report.html').exists()


def test_news_step_prints_source_and_matches(tmp_path, candles, capsys):
    from moex_agent.cli import _show_tool_event
    runtime = runtime_for(tmp_path, candles)
    runtime.session.news = FakeNews().match([], 'SBER', 5, 1)
    _show_tool_event('tool_call', {'tool': 'link_price_moves_to_news'}, runtime.session)
    _show_tool_event('tool_result', {'tool': 'link_price_moves_to_news'}, runtime.session)
    output = capsys.readouterr().out
    assert '[3/3]' in output
    assert 'движений с совпадениями: 0' in output
    assert 'Источник: test' in output
    assert 'HTML-отчёт обновлён' in output
