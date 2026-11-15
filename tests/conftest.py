from datetime import date, timedelta

import pytest

from moex_agent.models import Candle, StrategySpec


@pytest.fixture
def spec():
    return StrategySpec(
        ticker="SBER", date_from=date(2024, 1, 1), date_to=date(2024, 5, 31),
        fast_window=2, slow_window=3, initial_capital_rub=100_000, fee_bps=5,
    )


@pytest.fixture
def candles():
    rows = []
    start = date(2024, 1, 1)
    for index in range(100):
        close = 100 + index * 0.3 if index < 50 else 115 - (index - 50) * 0.45
        rows.append(Candle(
            tradedate=start + timedelta(days=index), open=close - 0.2,
            close=close, high=close + 1, low=close - 1, volume=1000 + index,
        ))
    return rows
