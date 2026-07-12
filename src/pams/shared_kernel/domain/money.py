"""Money 값객체: 통화가 명시된 Decimal 금액.

자산 계산에서 이진 부동소수점(float) 오차는 허용할 수 없으므로
float 입력은 생성 시점에 거부한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from pams.shared_kernel.domain.currency import Currency
from pams.shared_kernel.domain.errors import CurrencyMismatchError, DomainValidationError


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise DomainValidationError(
                f"Money.amount는 Decimal이어야 한다 (float 금지): {self.amount!r}"
            )

    @classmethod
    def of(cls, amount: str | int | Decimal, currency: Currency) -> Money:
        if isinstance(amount, float):
            raise DomainValidationError(f"float 금액은 허용되지 않는다: {amount!r}")
        return cls(Decimal(amount), currency)

    @classmethod
    def zero(cls, currency: Currency) -> Money:
        return cls(Decimal(0), currency)

    def _require_same_currency(self, other: Money, operation: str) -> None:
        if self.currency is not other.currency:
            raise CurrencyMismatchError(
                f"{self.currency}와 {other.currency}는 직접 {operation}할 수 없다 "
                "- ExchangeRate로 변환 후 연산해야 한다"
            )

    def __add__(self, other: Money) -> Money:
        self._require_same_currency(other, "덧셈")
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._require_same_currency(other, "뺄셈")
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __mul__(self, factor: int | Decimal) -> Money:
        if isinstance(factor, float):
            raise DomainValidationError(f"float 배수는 허용되지 않는다: {factor!r}")
        return Money(self.amount * factor, self.currency)

    def __rmul__(self, factor: int | Decimal) -> Money:
        return self.__mul__(factor)

    def __lt__(self, other: Money) -> bool:
        self._require_same_currency(other, "비교")
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._require_same_currency(other, "비교")
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._require_same_currency(other, "비교")
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._require_same_currency(other, "비교")
        return self.amount >= other.amount

    @property
    def is_positive(self) -> bool:
        return self.amount > 0

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    def round_to(self, decimal_places: int) -> Money:
        """사사오입(ROUND_HALF_UP) 반올림.

        표시/정산 시점에만 사용하고 중간 계산은 반올림하지 않는다.
        """
        exponent = Decimal(1).scaleb(-decimal_places)
        return Money(self.amount.quantize(exponent, rounding=ROUND_HALF_UP), self.currency)
