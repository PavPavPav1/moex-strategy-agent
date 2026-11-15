import hashlib
import json
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from .models import Candle, StrategySpec


def independent_backtest(spec: StrategySpec, candles: List[Candle]) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    frame = pd.DataFrame([
        {
            "date": candle.tradedate.isoformat(),
            "open": candle.open,
            "close": candle.close,
        }
        for candle in sorted(candles, key=lambda item: item.tradedate)
    ])
    frame["fast"] = frame["close"].rolling(spec.fast_window, min_periods=spec.fast_window).mean()
    frame["slow"] = frame["close"].rolling(spec.slow_window, min_periods=spec.slow_window).mean()
    frame["desired"] = (frame["fast"] > frame["slow"]).astype(np.int8)
    targets = frame["desired"].shift(1).fillna(0).astype(np.int8).to_numpy()
    fee = spec.fee_bps / 10_000
    balance = float(spec.initial_capital_rub)
    units = 0
    active = None
    completed: List[Dict[str, Any]] = []
    values: List[float] = []
    positions: List[int] = []

    def close_position(position: Dict[str, Any], price: float, day: str, reason: str) -> Tuple[float, Dict[str, Any]]:
        revenue = position["quantity"] * price
        exit_commission = revenue * fee
        invested = position["cost"] + position["entry_commission"]
        pnl = revenue - exit_commission - invested
        updated_balance = position["prior_balance"] - invested + revenue - exit_commission
        record = {
            "entry_date": position["day"],
            "exit_date": day,
            "entry_price_rub": round(position["price"], 4),
            "exit_price_rub": round(price, 4),
            "quantity": position["quantity"],
            "fees_rub": round(position["entry_commission"] + exit_commission, 2),
            "net_pnl_rub": round(pnl, 2),
            "return_pct": round(pnl / invested * 100, 4),
            "holding_days": (pd.Timestamp(day) - pd.Timestamp(position["day"])).days,
            "exit_reason": reason,
        }
        return updated_balance, record

    for index, row in frame.iterrows():
        if index > 0 and targets[index] == 1 and units == 0:
            units = int(balance // (row["open"] * (1 + fee)))
            if units:
                cost = units * row["open"]
                commission = cost * fee
                active = {
                    "day": row["date"], "price": row["open"], "quantity": units,
                    "cost": cost, "entry_commission": commission, "prior_balance": balance,
                }
                balance -= cost + commission
        elif index > 0 and targets[index] == 0 and units:
            balance, record = close_position(active, row["open"], row["date"], "signal")
            completed.append(record)
            units = 0
            active = None
        values.append(balance + units * row["close"])
        positions.append(int(units > 0))

    if units:
        balance, record = close_position(active, frame.iloc[-1]["close"], frame.iloc[-1]["date"], "end_of_data")
        completed.append(record)
        values[-1] = balance
        positions[-1] = 0
    frame["equity"] = values
    frame["position"] = positions
    return frame[["date", "equity", "position"]], completed


def crosscheck(spec: StrategySpec, candles: List[Candle], primary: Dict[str, Any], tolerance_rub: float = 0.01) -> Dict[str, Any]:
    independent_equity, independent_trades = independent_backtest(spec, candles)
    primary_frame = pd.DataFrame(primary["equity"])[["date", "equity"]]
    comparison = primary_frame.merge(independent_equity, on="date", suffixes=("_primary", "_independent"), validate="one_to_one")
    differences = np.abs(comparison["equity_primary"].to_numpy() - comparison["equity_independent"].to_numpy())
    max_difference = float(differences.max()) if len(differences) else float("inf")
    trade_count_matches = len(primary["trades"]) == len(independent_trades)
    pnl_differences = [
        abs(left["net_pnl_rub"] - right["net_pnl_rub"])
        for left, right in zip(primary["trades"], independent_trades)
    ]
    max_pnl_difference = max(pnl_differences, default=0.0)
    independent_values = independent_equity["equity"]
    independent_return = (independent_values.iloc[-1] / spec.initial_capital_rub - 1) * 100
    independent_drawdown = ((independent_values / independent_values.cummax()) - 1).min() * 100
    return_difference = abs(primary["metrics"]["total_return_pct"] - independent_return)
    drawdown_difference = abs(primary["metrics"]["max_drawdown_pct"] - independent_drawdown)
    passed = (
        len(comparison) == len(primary["equity"])
        and max_difference <= tolerance_rub
        and trade_count_matches
        and max_pnl_difference <= 0.01
        and return_difference <= 0.001
        and drawdown_difference <= 0.001
    )
    canonical = json.dumps(primary["equity"], ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return {
        "status": "PASS" if passed else "FAIL",
        "implementation": "pandas rolling + NumPy targets + отдельный денежный цикл",
        "sessions_compared": len(comparison),
        "max_abs_equity_difference_rub": round(max_difference, 8),
        "max_abs_trade_pnl_difference_rub": round(max_pnl_difference, 8),
        "return_difference_pp": round(return_difference, 8),
        "drawdown_difference_pp": round(drawdown_difference, 8),
        "primary_trades": len(primary["trades"]),
        "independent_trades": len(independent_trades),
        "tolerance_rub": tolerance_rub,
        "primary_equity_sha256": hashlib.sha256(canonical).hexdigest(),
    }
