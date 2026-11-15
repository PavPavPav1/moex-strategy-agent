import math
from typing import Any, Dict, List, Optional

from .errors import ToolProblem
from .models import Candle, StrategySpec


def _metrics(equity: List[Dict[str, Any]], initial_capital: float, trades: List[Dict[str, Any]], orders: int) -> Dict[str, Any]:
    values = [float(row["equity"]) for row in equity]
    final = values[-1]
    daily_returns = [values[index] / values[index - 1] - 1 for index in range(1, len(values)) if values[index - 1] > 0]
    peak = values[0]
    max_drawdown = 0.0
    peak_date = equity[0]["date"]
    trough_date = equity[0]["date"]
    current_peak_date = peak_date
    underwater = 0
    max_underwater = 0
    for row in equity:
        value = float(row["equity"])
        if value > peak:
            peak = value
            current_peak_date = row["date"]
            underwater = 0
        else:
            underwater += 1
            max_underwater = max(max_underwater, underwater)
        drawdown = value / peak - 1 if peak else 0.0
        if drawdown < max_drawdown:
            max_drawdown = drawdown
            peak_date = current_peak_date
            trough_date = row["date"]
    mean_return = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0
    variance = sum((value - mean_return) ** 2 for value in daily_returns) / (len(daily_returns) - 1) if len(daily_returns) > 1 else 0.0
    volatility = math.sqrt(variance)
    sharpe = mean_return / volatility * math.sqrt(252) if volatility > 1e-12 else None
    elapsed_days = max(1, (__import__("datetime").date.fromisoformat(equity[-1]["date"]) - __import__("datetime").date.fromisoformat(equity[0]["date"])).days)
    cagr = (final / initial_capital) ** (365.25 / elapsed_days) - 1 if final > 0 else -1.0
    wins = [trade for trade in trades if trade["net_pnl_rub"] > 0]
    losses = [trade for trade in trades if trade["net_pnl_rub"] < 0]
    gross_profit = sum(trade["net_pnl_rub"] for trade in wins)
    gross_loss = sum(trade["net_pnl_rub"] for trade in losses)
    return {
        "initial_capital_rub": round(initial_capital, 2),
        "final_equity_rub": round(final, 2),
        "total_return_pct": round((final / initial_capital - 1) * 100, 4),
        "cagr_pct": round(cagr * 100, 4),
        "max_drawdown_pct": round(max_drawdown * 100, 4),
        "max_drawdown_peak": peak_date,
        "max_drawdown_trough": trough_date,
        "max_underwater_days": max_underwater,
        "annualized_volatility_pct": round(volatility * math.sqrt(252) * 100, 4),
        "sharpe_rf0": round(sharpe, 4) if sharpe is not None else None,
        "closed_trades": len(trades),
        "orders": orders,
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else None,
        "profit_factor": round(gross_profit / abs(gross_loss), 4) if gross_loss < 0 else None,
        "avg_trade_return_pct": round(sum(trade["return_pct"] for trade in trades) / len(trades), 4) if trades else None,
        "exposure_pct": round(sum(int(row["position"]) for row in equity) / len(equity) * 100, 2),
        "total_fees_rub": round(sum(trade["fees_rub"] for trade in trades), 2),
    }


def _execute_buy(cash: float, price: float, fee_rate: float) -> Dict[str, float]:
    quantity = int(cash // (price * (1 + fee_rate)))
    gross = quantity * price
    fee = gross * fee_rate
    return {"quantity": quantity, "gross": gross, "fee": fee, "cash_after": cash - gross - fee}


def run_backtest(spec: StrategySpec, candles: List[Candle]) -> Dict[str, Any]:
    if len(candles) < spec.slow_window + 2:
        raise ToolProblem("insufficient_data", "Слишком мало свечей для бэктеста", "Увеличь период")
    rows = sorted(candles, key=lambda item: item.tradedate)
    fee_rate = spec.fee_bps / 10_000
    cash = spec.initial_capital_rub
    shares = 0
    pending_target = 0
    entry: Optional[Dict[str, Any]] = None
    trades: List[Dict[str, Any]] = []
    equity: List[Dict[str, Any]] = []
    orders = 0
    close_sum = 0.0
    fast_sum = 0.0
    slow_sum = 0.0

    def sell(position: Dict[str, Any], price: float, tradedate: str, reason: str) -> Dict[str, Any]:
        gross = position["quantity"] * price
        sell_fee = gross * fee_rate
        entry_cost = position["gross"] + position["entry_fee"]
        net_pnl = gross - sell_fee - entry_cost
        trade = {
            "entry_date": position["entry_date"],
            "exit_date": tradedate,
            "entry_price_rub": round(position["entry_price"], 4),
            "exit_price_rub": round(price, 4),
            "quantity": position["quantity"],
            "fees_rub": round(position["entry_fee"] + sell_fee, 2),
            "net_pnl_rub": round(net_pnl, 2),
            "return_pct": round(net_pnl / entry_cost * 100, 4),
            "holding_days": (__import__("datetime").date.fromisoformat(tradedate) - __import__("datetime").date.fromisoformat(position["entry_date"])).days,
            "exit_reason": reason,
        }
        return {"cash_after": position["cash_before"] - position["gross"] - position["entry_fee"] + gross - sell_fee, "trade": trade}

    for index, candle in enumerate(rows):
        tradedate = candle.tradedate.isoformat()
        if index > 0 and pending_target == 1 and shares == 0:
            purchase = _execute_buy(cash, candle.open, fee_rate)
            shares = int(purchase["quantity"])
            if shares > 0:
                orders += 1
                entry = {
                    "entry_date": tradedate,
                    "entry_price": candle.open,
                    "quantity": shares,
                    "gross": purchase["gross"],
                    "entry_fee": purchase["fee"],
                    "cash_before": cash,
                }
                cash = purchase["cash_after"]
        elif index > 0 and pending_target == 0 and shares > 0 and entry is not None:
            outcome = sell(entry, candle.open, tradedate, "signal")
            cash = outcome["cash_after"]
            trades.append(outcome["trade"])
            shares = 0
            entry = None
            orders += 1

        close_sum += candle.close
        fast_sum += candle.close
        slow_sum += candle.close
        if index >= spec.fast_window:
            fast_sum -= rows[index - spec.fast_window].close
        if index >= spec.slow_window:
            slow_sum -= rows[index - spec.slow_window].close
        fast_sma = fast_sum / spec.fast_window if index >= spec.fast_window - 1 else None
        slow_sma = slow_sum / spec.slow_window if index >= spec.slow_window - 1 else None
        signal = int(fast_sma is not None and slow_sma is not None and fast_sma > slow_sma)
        pending_target = signal
        equity.append({
            "date": tradedate,
            "equity": cash + shares * candle.close,
            "cash": cash,
            "close": candle.close,
            "position": int(shares > 0),
            "signal": signal,
            "fast_sma": fast_sma,
            "slow_sma": slow_sma,
        })

    if shares > 0 and entry is not None:
        final_candle = rows[-1]
        outcome = sell(entry, final_candle.close, final_candle.tradedate.isoformat(), "end_of_data")
        cash = outcome["cash_after"]
        trades.append(outcome["trade"])
        orders += 1
        shares = 0
        equity[-1]["equity"] = cash
        equity[-1]["cash"] = cash
        equity[-1]["position"] = 0

    benchmark_cash = spec.initial_capital_rub
    first_purchase = _execute_buy(benchmark_cash, rows[0].open, fee_rate)
    benchmark_shares = int(first_purchase["quantity"])
    benchmark_cash = first_purchase["cash_after"]
    benchmark_orders = 1 if benchmark_shares else 0
    benchmark_equity = []
    for index, candle in enumerate(rows):
        value = benchmark_cash + benchmark_shares * candle.close
        benchmark_equity.append({"date": candle.tradedate.isoformat(), "equity": value, "position": int(benchmark_shares > 0)})
    benchmark_trade = []
    if benchmark_shares:
        benchmark_entry = {
            "entry_date": rows[0].tradedate.isoformat(),
            "entry_price": rows[0].open,
            "quantity": benchmark_shares,
            "gross": first_purchase["gross"],
            "entry_fee": first_purchase["fee"],
            "cash_before": spec.initial_capital_rub,
        }
        outcome = sell(benchmark_entry, rows[-1].close, rows[-1].tradedate.isoformat(), "end_of_data")
        benchmark_trade.append(outcome["trade"])
        benchmark_equity[-1]["equity"] = outcome["cash_after"]
        benchmark_equity[-1]["position"] = 0
        benchmark_orders += 1

    for row, benchmark in zip(equity, benchmark_equity):
        row["buy_hold"] = benchmark["equity"]

    metrics = _metrics(equity, spec.initial_capital_rub, trades, orders)
    benchmark_metrics = _metrics(benchmark_equity, spec.initial_capital_rub, benchmark_trade, benchmark_orders)
    metrics["excess_return_pp"] = round(metrics["total_return_pct"] - benchmark_metrics["total_return_pct"], 4)
    moves = []
    for index in range(1, len(rows)):
        daily_return = rows[index].close / rows[index - 1].close - 1
        moves.append({
            "date": rows[index].tradedate.isoformat(),
            "close": rows[index].close,
            "return_pct": round(daily_return * 100, 4),
            "abs_return_pct": abs(daily_return * 100),
        })
    return {
        "strategy": spec.model_dump(mode="json"),
        "period": {"first": equity[0]["date"], "last": equity[-1]["date"], "sessions": len(equity)},
        "metrics": metrics,
        "buy_hold": benchmark_metrics,
        "trades": trades,
        "equity": equity,
        "price_moves": sorted(moves, key=lambda item: item["abs_return_pct"], reverse=True),
    }
