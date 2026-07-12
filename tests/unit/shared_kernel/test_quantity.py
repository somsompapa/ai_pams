"""Quantity 값객체 테스트.

보유 수량은 음수가 될 수 없고, 소수점 수량(미국주식 소수점 매매, 금 g, 가상자산)을 지원한다.
"""

from decimal import Decimal

import pytest

from pams.shared_kernel.domain import DomainValidationError, Quantity


class TestQuantity:
    def test_integer_and_fractional(self) -> None:
        assert Quantity.of(10).value == Decimal("10")
        assert Quantity.of("0.35").value == Decimal("0.35")

    def test_negative_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            Quantity.of(-1)

    def test_zero_allowed(self) -> None:
        assert Quantity.of(0).is_zero

    def test_float_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            Quantity.of(1.5)  # type: ignore[arg-type]

    def test_add_subtract(self) -> None:
        assert Quantity.of(10) + Quantity.of(5) == Quantity.of(15)
        assert Quantity.of(10) - Quantity.of(4) == Quantity.of(6)

    def test_subtract_below_zero_rejected(self) -> None:
        """보유 수량보다 많이 매도할 수 없다."""
        with pytest.raises(DomainValidationError):
            Quantity.of(3) - Quantity.of(5)
