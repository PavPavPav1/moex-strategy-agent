import json

from moex_agent.backtest import run_backtest
from moex_agent.diagnostics import build_diagnostics


def test_diagnostics_explain_underperformance(spec, candles):
    result = run_backtest(spec, candles)
    result["diagnostics"] = build_diagnostics(result)
    assert result["diagnostics"]["yearly"]
    assert result["diagnostics"]["limitations"]
    assert all("evidence" in item for item in result["diagnostics"]["weaknesses"])


def test_real_demo_crosscheck_is_pass():
    from pathlib import Path
    report = Path(__file__).parents[1] / "reports" / "demo_sber" / "crosscheck.json"
    if report.exists():
        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload["status"] == "PASS"
        assert payload["sessions_compared"] == 510
