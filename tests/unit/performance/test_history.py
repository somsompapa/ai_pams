"""PerformanceHistory(평가액+현금흐름 시계열) 테스트."""

from datetime import date
from decimal import Decimal

import pytest

from pams.performance.domain import (
    PerformanceCalculationError,
    PerformanceHistory,
    ValuationPoint,
)
from pams.shared_kernel.domain import DomainValidationError


def point(day: str, value: str, flow: str = "0") -> ValuationPoint:
    return ValuationPoint(
        point_date=date.fromisoformat(day), value=Decimal(value), net_flow=Decimal(flow)
    )


class TestValidation:
    def test_sorted_and_accessible(self) -> None:
        history = PerformanceHistory.from_points(
            [point("2026-01-31", "110"), point("2026-01-01", "100")]
        )
        assert history.points[0].point_date == date(2026, 1, 1)
        assert history.end_date == date(2026, 1, 31)

    def test_duplicate_dates_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            PerformanceHistory.from_points([point("2026-01-01", "100"), point("2026-01-01", "101")])

    def test_non_positive_value_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            PerformanceHistory.from_points([point("2026-01-01", "0")])

    def test_float_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            ValuationPoint(point_date=date(2026, 1, 1), value=100.0, net_flow=Decimal(0))  # type: ignore[arg-type]
        with pytest.raises(DomainValidationError):
            ValuationPoint(point_date=date(2026, 1, 1), value=Decimal(100), net_flow=0.5)  # type: ignore[arg-type]

    def test_empty_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            PerformanceHistory.from_points([])


class TestTwr:
    def test_deposit_does_not_inflate_return(self) -> None:
        """핵심 계약: 입금 50은 수익이 아니다.

        100 → (입금 50 직후) 160 → 176
        구간1: (160-50)/100 = 1.10 (+10%), 구간2: 176/160 = 1.10 (+10%)
        TWR = 1.1×1.1 - 1 = 21% (단순수익률이라면 (176-150)/100 = 26%로 왜곡)
        """
        history = PerformanceHistory.from_points(
            [
                point("2026-01-01", "100"),
                point("2026-01-15", "160", flow="50"),
                point("2026-01-31", "176"),
            ]
        )
        assert history.cumulative_twr() == Decimal("0.21")

    def test_withdrawal_does_not_deflate_return(self) -> None:
        """출금(음수 flow)도 수익률을 왜곡하지 않는다: (55-(-50))/100 = 1.05."""
        history = PerformanceHistory.from_points(
            [point("2026-01-01", "100"), point("2026-01-15", "55", flow="-50")]
        )
        assert history.cumulative_twr() == Decimal("0.05")

    def test_needs_two_points(self) -> None:
        history = PerformanceHistory.from_points([point("2026-01-01", "100")])
        with pytest.raises(PerformanceCalculationError):
            history.cumulative_twr()

    def test_flow_exceeding_value_rejected(self) -> None:
        """입금액이 평가액 이상이면 (V-F)≤0 - 수익률이 정의되지 않는다."""
        history = PerformanceHistory.from_points(
            [point("2026-01-01", "100"), point("2026-01-15", "90", flow="90")]
        )
        with pytest.raises(PerformanceCalculationError):
            history.cumulative_twr()
