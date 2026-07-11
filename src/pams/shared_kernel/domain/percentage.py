"""Percentage 값객체: 자산비중/수익률/한도의 표준 표현.

내부적으로 비율(ratio)로 저장한다: from_percent(10) == from_ratio("0.10") == 10%.
수익률 표현을 위해 음수를 허용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pams.shared_kernel.domain.errors import DomainValidationError
from pams.shared_kernel.domain.money import Money


@dataclass(frozen=True, slots=True, order=True)
class Percentage:
    ratio: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.ratio, Decimal):
            raise DomainValidationError(
                f"Percentage.ratio는 Decimal이어야 한다 (float 금지): {self.ratio!r}"
            )

    @classmethod
    def from_percent(cls, value: str | int | Decimal) -> Percentage:
        if isinstance(value, float):
            raise DomainValidationError(f"float 퍼센트는 허용되지 않는다: {value!r}")
        return cls(Decimal(value) / 100)

    @classmethod
    def from_ratio(cls, value: str | int | Decimal) -> Percentage:
        if isinstance(value, float):
            raise DomainValidationError(f"float 비율은 허용되지 않는다: {value!r}")
        return cls(Decimal(value))

    @classmethod
    def zero(cls) -> Percentage:
        return cls(Decimal(0))

    @property
    def as_percent(self) -> Decimal:
        return self.ratio * 100

    def of(self, money: Money) -> Money:
        """비중 계산: Percentage.from_percent(10).of(1,000,000원) == 100,000원."""
        return money * self.ratio

    def __add__(self, other: Percentage) -> Percentage:
        return Percentage(self.ratio + other.ratio)

    def __sub__(self, other: Percentage) -> Percentage:
        return Percentage(self.ratio - other.ratio)

    def __neg__(self) -> Percentage:
        return Percentage(-self.ratio)
