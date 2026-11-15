from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=12, pattern=r"^[A-Z][A-Z0-9.-]*$")
    date_from: date
    date_to: date
    fast_window: int = Field(ge=2, le=100)
    slow_window: int = Field(ge=3, le=250)
    initial_capital_rub: float = Field(ge=10_000, le=1_000_000_000)
    fee_bps: float = Field(ge=0, le=100)
    interval: int = Field(default=24, description="Дневные свечи MOEX ISS")

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("interval")
    @classmethod
    def daily_only(cls, value: int) -> int:
        if value != 24:
            raise ValueError("поддерживаются только дневные свечи: interval=24")
        return value

    @model_validator(mode="after")
    def validate_windows_and_dates(self) -> "StrategySpec":
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window должен быть меньше slow_window")
        if self.date_to <= self.date_from:
            raise ValueError("date_to должен быть позже date_from")
        if (self.date_to - self.date_from).days < self.slow_window:
            raise ValueError("период короче медленного окна; увеличьте date_to")
        return self


class Candle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tradedate: date
    open: float = Field(gt=0)
    close: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    volume: float = Field(ge=0)


@dataclass
class DataBundle:
    candles: List[Candle]
    source: str
    source_url: str
    cache_path: Optional[str] = None
    warning: Optional[str] = None
    fetched_at: Optional[str] = None
    sha256: Optional[str] = None


@dataclass
class AgentSession:
    run_dir: Path
    strategy: Optional[StrategySpec] = None
    assumptions: List[str] = field(default_factory=list)
    data: Optional[DataBundle] = None
    result: Optional[Dict[str, Any]] = None
    news: Optional[Dict[str, Any]] = None


DISCLAIMER = (
    "Это исследование на исторических данных, а не инвестиционная рекомендация. "
    "Прошлая доходность не гарантирует будущую. Результат чувствителен к допущениям, "
    "комиссиям, налогам, ликвидности и качеству данных."
)
