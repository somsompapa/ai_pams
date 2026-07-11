"""Money 값객체 테스트.

핵심 계약:
- 금액은 Decimal만 허용한다 (float 금지 - 이진 부동소수점 오차로 인한 자산 계산 오류 방지)
- 서로 다른 통화끼리는 연산할 수 없다
- 값객체이므로 불변이다
"""

from decimal import Decimal

import pytest

from pams.shared_kernel.domain import (
    Currency,
    CurrencyMismatchError,
    DomainValidationError,
    Money,
)


class TestCreation:
    def test_of_accepts_str_int_decimal(self) -> None:
        assert Money.of("10000.50", Currency.KRW).amount == Decimal("10000.50")
        assert Money.of(10000, Currency.KRW).amount == Decimal("10000")
        assert Money.of(Decimal("3.14"), Currency.USD).amount == Decimal("3.14")

    def test_float_is_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            Money.of(0.1, Currency.KRW)  # type: ignore[arg-type]

    def test_direct_constructor_rejects_non_decimal(self) -> None:
        with pytest.raises(DomainValidationError):
            Money(0.1, Currency.KRW)  # type: ignore[arg-type]

    def test_zero(self) -> None:
        zero = Money.zero(Currency.USD)
        assert zero.amount == Decimal("0")
        assert zero.currency is Currency.USD

    def test_immutable(self) -> None:
        money = Money.of("100", Currency.KRW)
        with pytest.raises(AttributeError):
            money.amount = Decimal("200")  # type: ignore[misc]


class TestArithmetic:
    def test_add_same_currency(self) -> None:
        result = Money.of("100", Currency.KRW) + Money.of("50", Currency.KRW)
        assert result == Money.of("150", Currency.KRW)

    def test_add_different_currency_raises(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            Money.of("100", Currency.KRW) + Money.of("1", Currency.USD)

    def test_subtract(self) -> None:
        result = Money.of("100", Currency.KRW) - Money.of("30", Currency.KRW)
        assert result == Money.of("70", Currency.KRW)

    def test_subtract_can_go_negative(self) -> None:
        result = Money.of("30", Currency.KRW) - Money.of("100", Currency.KRW)
        assert result.amount == Decimal("-70")
        assert result.is_negative

    def test_multiply_by_int_and_decimal(self) -> None:
        price = Money.of("70000", Currency.KRW)
        assert (price * 10).amount == Decimal("700000")
        assert (price * Decimal("0.5")).amount == Decimal("35000")
        assert (3 * price).amount == Decimal("210000")

    def test_negation(self) -> None:
        assert (-Money.of("100", Currency.KRW)).amount == Decimal("-100")

    def test_no_float_precision_error(self) -> None:
        """float였다면 0.1+0.2 != 0.3 이 되는 대표적인 사례."""
        result = Money.of("0.1", Currency.USD) + Money.of("0.2", Currency.USD)
        assert result == Money.of("0.3", Currency.USD)


class TestComparison:
    def test_ordering_same_currency(self) -> None:
        small = Money.of("100", Currency.KRW)
        big = Money.of("200", Currency.KRW)
        assert small < big
        assert big > small
        assert small <= Money.of("100", Currency.KRW)

    def test_ordering_different_currency_raises(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            _ = Money.of("100", Currency.KRW) < Money.of("1", Currency.USD)

    def test_sign_properties(self) -> None:
        assert Money.of("1", Currency.KRW).is_positive
        assert Money.of("-1", Currency.KRW).is_negative
        assert Money.zero(Currency.KRW).is_zero


class TestRounding:
    def test_round_to_decimal_places(self) -> None:
        money = Money.of("1234.5678", Currency.USD)
        assert money.round_to(2) == Money.of("1234.57", Currency.USD)
        assert money.round_to(0) == Money.of("1235", Currency.USD)

    def test_round_half_up(self) -> None:
        """금융 계산 관례: 사사오입(ROUND_HALF_UP)."""
        assert Money.of("0.125", Currency.USD).round_to(2) == Money.of("0.13", Currency.USD)
