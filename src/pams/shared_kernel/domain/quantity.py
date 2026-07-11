"""Quantity 값객체: 보유/거래 수량.

음수가 될 수 없고, 소수점 수량(미국주식 소수점 매매, 금 g, 가상자산)을 지원한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pams.shared_kernel.domain.errors import DomainValidationError


@dataclass(frozen=True, slots=True, order=True)
class Quantity:
    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise DomainValidationError(
                f"Quantity.value는 Decimal이어야 한다 (float 금지): {self.value!r}"
            )
        if self.value < 0:
            raise DomainValidationError(f"수량은 음수가 될 수 없다: {self.value}")

    @classmethod
    def of(cls, value: str | int | Decimal) -> Quantity:
        if isinstance(value, float):
            raise DomainValidationError(f"float 수량은 허용되지 않는다: {value!r}")
        return cls(Decimal(value))

    @property
    def is_zero(self) -> bool:
        return self.value == 0

    def __add__(self, other: Quantity) -> Quantity:
        return Quantity(self.value + other.value)

    def __sub__(self, other: Quantity) -> Quantity:
        if other.value > self.value:
            raise DomainValidationError(
                f"보유 수량({self.value})보다 많은 수량({other.value})을 차감할 수 없다"
            )
        return Quantity(self.value - other.value)
