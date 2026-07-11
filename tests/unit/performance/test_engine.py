"""PerformanceEngine 테스트.

시나리오: 매월 정확히 +10% 수익 (2026-01 ~ 2026-03), 벤치마크는 매월 +5%.
"""

from datetime import date
from decimal import Decimal

import pytest

from pams.performance.application import ComputePerformanceReport
from pams.performance.domain import (
    PerformanceCalculationError,
    PerformanceEngine,
    PerformanceHistory,
    ValuationPoint,
)


def history_of(*pairs: tuple[str, str, str]) -> PerformanceHistory:
    return PerformanceHistory.from_points(
        [
            ValuationPoint(
                point_date=date.fromisoformat(day), value=Decimal(value), net_flow=Decimal(flow)
            )
            for day, value, flow in pairs
        ]
    )


PORTFOLIO = history_of(
    ("2026-01-01", "1000000", "0"),
    ("2026-01-31", "1100000", "0"),  # 1월 +10%
    ("2026-02-28", "1210000", "0"),  # 2월 +10%
    ("2026-03-31", "1331000", "0"),  # 3월 +10%
)
BENCHMARK = history_of(
    ("2026-01-01", "100", "0"),
    ("2026-01-31", "105", "0"),
    ("2026-02-28", "110.25", "0"),
    ("2026-03-31", "115.7625", "0"),
)


class TestPeriodBreakdown:
    def test_monthly_returns(self) -> None:
        report = PerformanceEngine().analyze(history=PORTFOLIO)
        labels = [p.label for p in report.monthly]
        assert labels == ["2026-01", "2026-02", "2026-03"]
        for period in report.monthly:
            assert period.twr == Decimal("0.1")

    def test_quarterly_and_yearly(self) -> None:
        report = PerformanceEngine().analyze(history=PORTFOLIO)
        assert [p.label for p in report.quarterly] == ["2026-Q1"]
        assert report.quarterly[0].twr == Decimal("0.331")
        assert [p.label for p in report.yearly] == ["2026"]
        assert report.yearly[0].twr == Decimal("0.331")

    def test_cumulative(self) -> None:
        report = PerformanceEngine().analyze(history=PORTFOLIO)
        assert report.cumulative_twr == Decimal("0.331")
        assert report.as_of == date(2026, 3, 31)

    def test_deposit_mid_month_does_not_distort_monthly_return(self) -> None:
        history = history_of(
            ("2026-01-01", "1000000", "0"),
            ("2026-01-15", "1600000", "500000"),  # 입금 50만 + 수익 10%
            ("2026-01-31", "1760000", "0"),  # +10%
        )
        report = PerformanceEngine().analyze(history=history)
        assert report.monthly[0].twr == Decimal("0.21")


class TestBenchmarkComparison:
    def test_monthly_excess(self) -> None:
        report = PerformanceEngine().analyze(history=PORTFOLIO, benchmark=BENCHMARK)
        january = report.monthly[0]
        assert january.benchmark_twr == Decimal("0.05")
        assert january.excess == Decimal("0.05")

    def test_cumulative_excess(self) -> None:
        report = PerformanceEngine().analyze(history=PORTFOLIO, benchmark=BENCHMARK)
        assert report.cumulative_benchmark_twr == Decimal("0.157625")
        assert report.cumulative_excess == Decimal("0.331") - Decimal("0.157625")

    def test_no_benchmark_leaves_comparison_empty(self) -> None:
        report = PerformanceEngine().analyze(history=PORTFOLIO)
        assert report.cumulative_benchmark_twr is None
        assert report.cumulative_excess is None
        assert report.monthly[0].benchmark_twr is None

    def test_benchmark_missing_period_leaves_none(self) -> None:
        """벤치마크에 없는 기간의 초과수익은 None (0으로 조작하지 않는다)."""
        short_benchmark = history_of(("2026-01-01", "100", "0"), ("2026-01-31", "105", "0"))
        report = PerformanceEngine().analyze(history=PORTFOLIO, benchmark=short_benchmark)
        assert report.monthly[0].excess == Decimal("0.05")
        assert report.monthly[1].benchmark_twr is None
        assert report.monthly[1].excess is None


class TestTradeAndCompliance:
    def test_win_rate(self) -> None:
        """이익 2건 / 전체 4건 (0은 승리가 아님) → 50%."""
        report = PerformanceEngine().analyze(
            history=PORTFOLIO,
            realized_pnls=[Decimal("10"), Decimal("-5"), Decimal("3"), Decimal("0")],
        )
        assert report.win_rate == Decimal("0.5")

    def test_compliance_rate(self) -> None:
        checks = [
            (date(2026, 1, 1), True),
            (date(2026, 2, 1), True),
            (date(2026, 3, 1), False),
            (date(2026, 4, 1), True),
        ]
        report = PerformanceEngine().analyze(history=PORTFOLIO, compliance_history=checks)
        assert report.compliance_rate == Decimal("0.75")

    def test_empty_inputs_leave_none(self) -> None:
        report = PerformanceEngine().analyze(history=PORTFOLIO)
        assert report.win_rate is None
        assert report.compliance_rate is None

    def test_empty_sequences_rejected(self) -> None:
        """빈 목록을 넘기는 것은 '데이터 없음(None)'과 다르다 - 명시적으로 실패시킨다."""
        with pytest.raises(PerformanceCalculationError):
            PerformanceEngine().analyze(history=PORTFOLIO, realized_pnls=[])
        with pytest.raises(PerformanceCalculationError):
            PerformanceEngine().analyze(history=PORTFOLIO, compliance_history=[])


class TestUseCase:
    def test_compute_performance_report(self) -> None:
        report = ComputePerformanceReport().execute(history=PORTFOLIO, benchmark=BENCHMARK)
        assert report.cumulative_twr == Decimal("0.331")
