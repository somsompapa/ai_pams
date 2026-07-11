"""ValueSeries/ReturnSeries 테스트."""

from datetime import date
from decimal import Decimal

import pytest

from pams.risk.domain import InsufficientDataError, ReturnSeries, ValueSeries
from pams.shared_kernel.domain import DomainValidationError

D = [date(2026, 1, i) for i in range(1, 11)]


class TestValueSeries:
    def test_from_pairs_sorts_by_date(self) -> None:
        series = ValueSeries.from_pairs([(D[1], Decimal(110)), (D[0], Decimal(100))])
        assert series.dates == (D[0], D[1])
        assert series.values == (Decimal(100), Decimal(110))

    def test_duplicate_dates_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            ValueSeries.from_pairs([(D[0], Decimal(100)), (D[0], Decimal(101))])

    def test_non_positive_value_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            ValueSeries.from_pairs([(D[0], Decimal(0))])

    def test_float_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            ValueSeries.from_pairs([(D[0], 100.0)])  # type: ignore[list-item]

    def test_empty_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            ValueSeries.from_pairs([])

    def test_returns(self) -> None:
        series = ValueSeries.from_pairs(
            [(D[0], Decimal(100)), (D[1], Decimal(110)), (D[2], Decimal(99))]
        )
        returns = series.returns()
        assert returns.values == (Decimal("0.1"), Decimal("-0.1"))
        assert returns.dates == (D[1], D[2])

    def test_returns_need_two_points(self) -> None:
        series = ValueSeries.from_pairs([(D[0], Decimal(100))])
        with pytest.raises(InsufficientDataError):
            series.returns()


class TestReturnSeries:
    def make(self, *values: str) -> ReturnSeries:
        return ReturnSeries.from_pairs([(D[i], Decimal(v)) for i, v in enumerate(values)])

    def test_mean(self) -> None:
        assert self.make("0.05", "0.15", "0.10").mean == Decimal("0.10")

    def test_sample_std(self) -> None:
        """편차 -0.05/+0.05/0 → 표본분산 0.0025 → 표준편차 0.05 (정확값)."""
        assert self.make("0.05", "0.15", "0.10").sample_std == Decimal("0.05")

    def test_sample_std_needs_two_returns(self) -> None:
        with pytest.raises(InsufficientDataError):
            _ = self.make("0.05").sample_std

    def test_downside_deviation(self) -> None:
        """음수 편차만: (-0.06)², (-0.08)² → 평균 0.0025 → 0.05 (정확값)."""
        series = self.make("0.10", "-0.06", "0.20", "-0.08")
        assert series.downside_deviation(Decimal(0)) == Decimal("0.05")

    def test_align_intersects_dates(self) -> None:
        a = ReturnSeries.from_pairs([(D[0], Decimal("0.1")), (D[1], Decimal("0.2"))])
        b = ReturnSeries.from_pairs([(D[1], Decimal("0.3")), (D[2], Decimal("0.4"))])
        aligned_a, aligned_b = a.align(b)
        assert aligned_a.dates == (D[1],)
        assert aligned_a.values == (Decimal("0.2"),)
        assert aligned_b.values == (Decimal("0.3"),)
