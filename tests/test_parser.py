import pytest

from moex_agent.cli import DEMO_STRATEGY
from moex_agent.errors import ToolProblem
from moex_agent.strategy_parser import formalize_strategy


def test_formalizes_demo_strategy():
    spec, assumptions = formalize_strategy(DEMO_STRATEGY)
    assert spec.ticker == "SBER"
    assert (spec.fast_window, spec.slow_window) == (20, 50)
    assert spec.initial_capital_rub == 1_000_000
    assert spec.fee_bps == 5
    assert spec.date_from.isoformat() == "2024-01-01"
    assert any("следующего" in item for item in assumptions)


def test_defaults_are_explicit():
    spec, assumptions = formalize_strategy("Акция GAZP, период 2024-01-01 — 2025-12-31")
    assert (spec.fast_window, spec.slow_window) == (20, 50)
    assert spec.initial_capital_rub == 1_000_000
    assert len(assumptions) >= 5


def test_rejects_short():
    with pytest.raises(ToolProblem) as error:
        formalize_strategy("SBER 2024-01-01 2025-12-31 SMA(20) SMA(50), открывай шорт с плечом")
    assert error.value.kind == "unsupported_strategy"


def test_rejects_inverted_windows():
    with pytest.raises(ToolProblem) as error:
        formalize_strategy("SBER 2024-01-01 2025-12-31 SMA(50) SMA(20)")
    assert error.value.kind == "validation"


def test_requires_ticker():
    with pytest.raises(ToolProblem) as error:
        formalize_strategy("Купить по SMA(20) и SMA(50) в 2024-01-01 — 2025-12-31")
    assert error.value.kind == "validation"
