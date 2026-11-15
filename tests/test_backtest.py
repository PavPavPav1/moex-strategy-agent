from datetime import date

from moex_agent.backtest import run_backtest
from moex_agent.models import Candle, StrategySpec
from moex_agent.validation import crosscheck, independent_backtest


def test_independent_implementations_match(spec, candles):
    result = run_backtest(spec, candles)
    check = crosscheck(spec, candles, result)
    assert check["status"] == "PASS"
    assert check["sessions_compared"] == len(candles)
    assert check["max_abs_equity_difference_rub"] <= 0.01
    assert check["primary_trades"] == len(result["trades"])


def test_crosscheck_detects_changed_equity(spec, candles):
    result = run_backtest(spec, candles)
    result["equity"][20]["equity"] += 1_000
    assert crosscheck(spec, candles, result)["status"] == "FAIL"


def test_signal_executes_at_next_open_not_signal_close():
    days = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"]
    closes = [100, 110, 120, 90, 80, 80]
    opens = [100, 105, 115, 130, 80, 81]
    rows = [Candle(tradedate=day, open=op, close=close, high=max(op, close) + 1, low=min(op, close) - 1, volume=100) for day, op, close in zip(days, opens, closes)]
    strategy = StrategySpec(ticker="SBER", date_from="2024-01-01", date_to="2024-01-06", fast_window=2, slow_window=3, initial_capital_rub=100_000, fee_bps=0)
    result = run_backtest(strategy, rows)
    trade = result["trades"][0]
    assert trade["entry_date"] == "2024-01-04"
    assert trade["entry_price_rub"] == 130
    assert trade["exit_date"] == "2024-01-05"
    assert trade["exit_price_rub"] == 80


def test_open_position_is_liquidated_at_end(spec, candles):
    strategy = spec.model_copy(update={"fast_window": 2, "slow_window": 3})
    result = run_backtest(strategy, candles[:10])
    assert result["trades"][-1]["exit_reason"] == "end_of_data"
    assert result["equity"][-1]["position"] == 0
    assert result["equity"][-1]["equity"] == __import__("pytest").approx(result["metrics"]["final_equity_rub"], abs=0.01)


def test_commission_reduces_return(spec, candles):
    free = run_backtest(spec.model_copy(update={"fee_bps": 0}), candles)
    paid = run_backtest(spec.model_copy(update={"fee_bps": 20}), candles)
    assert paid["metrics"]["final_equity_rub"] < free["metrics"]["final_equity_rub"]
    assert paid["metrics"]["total_fees_rub"] > 0


def test_independent_returns_dataframe(spec, candles):
    frame, trades = independent_backtest(spec, candles)
    assert list(frame.columns) == ["date", "equity", "position"]
    assert len(frame) == len(candles)
    assert len(trades) >= 1
