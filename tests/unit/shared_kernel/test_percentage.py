"""Percentage 값객체 테스트.

자산비중/수익률/한도 표현에 쓰인다. 내부적으로는 비율(ratio)로 저장한다:
Percentage.from_percent(10) == Percentage.from_ratio("0.10") == 10%
"""

from decimal import Decimal

import pytest

from pams.shared_kernel.domain import Currency, DomainValidationError, Money, Percentage


class TestCreation:
    def test_from_percent(self) -> None:
        pct = Percentage.from_percent(10)
        assert pct.ratio == Decimal("0.1")
        assert pct.as_percent == Decimal("10")

    def test_from_ratio(self) -> None:
        pct = Percentage.from_ratio("0.35")
        assert pct.as_percent == Decimal("35")

    def test_float_is_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            Percentage.from_percent(10.5)  # type: ignore[arg-type]

    def test_negative_allowed_for_returns(self) -> None:
        """수익률은 음수일 수 있으므로 음수 비율을 허용한다."""
        pct = Percentage.from_percent(-3)
        assert pct.ratio == Decimal("-0.03")

    def test_zero(self) -> None:
        assert Percentage.zero().ratio == Decimal("0")


class TestOperations:
    def test_of_money(self) -> None:
        """비중 계산의 핵심: 10% of 1,000,000원 = 100,000원."""
        pct = Percentage.from_percent(10)
        assert pct.of(Money.of("1000000", Currency.KRW)) == Money.of("100000", Currency.KRW)

    def test_add_subtract(self) -> None:
        a = Percentage.from_percent(60)
        b = Percentage.from_percent(25)
        assert (a + b).as_percent == Decimal("85")
        assert (a - b).as_percent == Decimal("35")

    def test_ordering(self) -> None:
        assert Percentage.from_percent(10) < Percentage.from_percent(20)
        assert Percentage.from_percent(30) >= Percentage.from_percent(30)

    def test_equality(self) -> None:
        assert Percentage.from_percent(50) == Percentage.from_ratio("0.5")
