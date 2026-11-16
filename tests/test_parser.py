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


@pytest.mark.parametrize('condition', [
    'Покупай только если RSI(14) < 30',
    'Фильтр MACD выше нуля',
    'Покупай при EMA(10) > EMA(30)',
    'Применяй CUSTOM(14)',
    'Стоп 5%',
    'Покупай, когда SMA(20) ниже SMA(50)',
    'Покупай если SMA(20) < SMA(50)',
    'SMA(20) < SMA(50) — покупка',
    'Buy when SMA(20) < SMA(50)',
    'Продавай когда SMA(20) > SMA(50)',
    'Покупай когда SMA(20) >= SMA(50)',
])
def test_rejects_unsupported_conditions(condition):
    with pytest.raises(ToolProblem) as error:
        formalize_strategy('SBER 2024-01-01 2025-12-31 SMA(20) SMA(50). ' + condition)
    assert error.value.kind == 'unsupported_strategy'


@pytest.mark.parametrize('condition', [
    'Покупай, когда SMA(20) выше SMA(50), продавай при обратном условии',
    'SMA(20) > SMA(50) — покупка, SMA(20) < SMA(50) — продажа',
    'Покупай при SMA(20) > SMA(50) и продавай при SMA(20) <= SMA(50)',
    'Buy when SMA(20) > SMA(50); sell when SMA(20) < SMA(50)',
])
def test_supported_directions_still_work(condition):
    spec, _ = formalize_strategy('SBER 2024-01-01 2025-12-31. ' + condition)
    assert (spec.fast_window, spec.slow_window) == (20, 50)
