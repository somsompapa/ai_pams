"""compute_growth_metrics() 테스트. ai_stock data_loader.compute_growth_metrics()의
검증된 케이스(신한지주 실측 기반 시나리오 포함)를 이식."""

from decimal import Decimal

from pams.equity.domain.financial_statement import AnnualFinancials
from pams.equity.domain.growth_metrics import compute_growth_metrics


def _row(fiscal_year: int, **kwargs: object) -> AnnualFinancials:
    return AnnualFinancials(fiscal_year=fiscal_year, **kwargs)  # type: ignore[arg-type]


class TestRevenueAndEpsCagr:
    def test_computes_3y_cagr_with_four_years(self) -> None:
        annual = (
            _row(2022, revenue=Decimal(1000), eps=Decimal(10)),
            _row(2023, revenue=Decimal(1100), eps=Decimal(11)),
            _row(2024, revenue=Decimal(1210), eps=Decimal(12)),
            _row(2025, revenue=Decimal(1331), eps=Decimal(13)),
        )
        metrics = compute_growth_metrics(annual)
        assert metrics.revenue_cagr_3y is not None
        assert abs(metrics.revenue_cagr_3y - Decimal("0.10")) < Decimal("0.0001")  # 정확히 10%
        assert metrics.revenue_cagr_3y_note is None

    def test_accepts_unsorted_input(self) -> None:
        """annual이 어떤 순서로 오든(과거→최신 강제 안 해도) 내부에서 정렬해야 한다."""
        annual = (
            _row(2025, revenue=Decimal(1331)),
            _row(2022, revenue=Decimal(1000)),
            _row(2024, revenue=Decimal(1210)),
            _row(2023, revenue=Decimal(1100)),
        )
        metrics = compute_growth_metrics(annual)
        assert metrics.revenue_cagr_3y is not None

    def test_fewer_than_four_years_returns_none_with_reason(self) -> None:
        annual = (_row(2023, revenue=Decimal(1000)), _row(2024, revenue=Decimal(1100)))
        metrics = compute_growth_metrics(annual)
        assert metrics.revenue_cagr_3y is None
        assert "최소 4개년" in (metrics.revenue_cagr_3y_note or "")

    def test_zero_or_missing_base_year_returns_none(self) -> None:
        annual = (
            _row(2022, revenue=None),
            _row(2023, revenue=Decimal(1100)),
            _row(2024, revenue=Decimal(1210)),
            _row(2025, revenue=Decimal(1331)),
        )
        metrics = compute_growth_metrics(annual)
        assert metrics.revenue_cagr_3y is None


class TestFinancialSectorTotalAssetsCagr:
    def test_matches_shinhan_financial_group_actual_scale(self) -> None:
        """신한지주(055550) 실측 DART 데이터(2023~2025) 그대로 재현 — 2년 구간이라
        공식 3Y CAGR(4개년 필요)은 계산 불가해야 한다(데이터 확보 못한 2022년 임의 추정 금지)."""
        annual = (
            _row(2023, total_assets=Decimal("691795333000000")),
            _row(2024, total_assets=Decimal("739764256000000")),
            _row(2025, total_assets=Decimal("786013485000000")),
        )
        metrics = compute_growth_metrics(annual)
        assert metrics.total_assets_cagr_3y is None
        assert "최소 4개년" in (metrics.total_assets_cagr_3y_note or "")

    def test_four_years_yields_cagr_close_to_observed_growth(self) -> None:
        annual = (
            _row(2022, total_assets=Decimal("660000000000000")),
            _row(2023, total_assets=Decimal("691795333000000")),
            _row(2024, total_assets=Decimal("739764256000000")),
            _row(2025, total_assets=Decimal("786013485000000")),
        )
        metrics = compute_growth_metrics(annual)
        assert metrics.total_assets_cagr_3y is not None
        assert Decimal("0.05") < metrics.total_assets_cagr_3y < Decimal("0.07")


class TestFcfPositiveYears:
    def test_counts_positive_years_among_recent_three(self) -> None:
        annual = (
            _row(2022, operating_cash_flow=Decimal(0), capex=Decimal(0)),
            _row(2023, operating_cash_flow=Decimal(529846000000), capex=Decimal(261444000000)),
            _row(2024, operating_cash_flow=Decimal(4626299000000), capex=Decimal(263836000000)),
            _row(2025, operating_cash_flow=Decimal(9730881000000), capex=Decimal(258659000000)),
        )
        metrics = compute_growth_metrics(annual)
        assert metrics.fcf_positive_years == 3
        assert metrics.fcf_positive_years_note is None

    def test_missing_fcf_component_in_recent_window_returns_none(self) -> None:
        annual = (
            _row(2023, operating_cash_flow=Decimal(100), capex=Decimal(10)),
            _row(2024, operating_cash_flow=None, capex=Decimal(10)),
            _row(2025, operating_cash_flow=Decimal(100), capex=Decimal(10)),
        )
        metrics = compute_growth_metrics(annual)
        assert metrics.fcf_positive_years is None
        assert "임의 추정 금지" in (metrics.fcf_positive_years_note or "")


class TestLatestRatios:
    def test_roa_latest_matches_shinhan_actual(self) -> None:
        """신한지주 실측(2025): 순이익 5,084,519,000,000 / 총자산 786,013,485,000,000."""
        annual = (
            _row(
                2025, net_income=Decimal("5084519000000"), total_assets=Decimal("786013485000000")
            ),
        )
        metrics = compute_growth_metrics(annual)
        assert metrics.roa_latest is not None
        assert abs(metrics.roa_latest - Decimal("0.006469")) < Decimal("0.00001")

    def test_gross_margin_latest_computed_from_last_year_only(self) -> None:
        annual = (
            _row(2024, revenue=Decimal(1000), gross_profit=Decimal(300)),
            _row(2025, revenue=Decimal(1200), gross_profit=Decimal(480)),
        )
        metrics = compute_growth_metrics(annual)
        assert metrics.gross_margin_latest == Decimal("0.4")

    def test_missing_latest_year_data_returns_none_not_zero(self) -> None:
        metrics = compute_growth_metrics(())
        assert metrics.roa_latest is None
        assert metrics.gross_margin_latest is None
