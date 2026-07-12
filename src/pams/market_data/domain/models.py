"""시장 데이터 도메인 모델: 가격, 환율."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pams.shared_kernel.domain import Currency, DomainValidationError, Money


@dataclass(frozen=True, slots=True)
class PricePoint:
    """특정 시점의 자산 가격."""

    asset_id: str
    price_date: date
    close: Money

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise DomainValidationError("asset_id는 비어 있을 수 없다")
        if not self.close.is_positive:
            raise DomainValidationError(f"가격은 양수여야 한다: {self.close.amount}")


@dataclass(frozen=True, slots=True)
class ExchangeRate:
    """환율: 1 base = rate quote (예: 1 USD = 1,380 KRW)."""

    base: Currency
    quote: Currency
    rate: Decimal
    rate_date: date

    def __post_init__(self) -> None:
        if not isinstance(self.rate, Decimal):
            raise DomainValidationError(f"환율은 Decimal이어야 한다 (float 금지): {self.rate!r}")
        if self.base is self.quote:
            raise DomainValidationError(f"base와 quote가 같을 수 없다: {self.base}")
        if self.rate <= 0:
            raise DomainValidationError(f"환율은 양수여야 한다: {self.rate}")

    def convert(self, money: Money) -> Money:
        """base 통화 금액을 quote 통화로 변환한다."""
        if money.currency is not self.base:
            raise DomainValidationError(
                f"이 환율은 {self.base}→{self.quote} 변환용이다: {money.currency} 입력 불가"
            )
        return Money(money.amount * self.rate, self.quote)
