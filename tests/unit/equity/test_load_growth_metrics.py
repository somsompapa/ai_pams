"""LoadGrowthMetrics 유스케이스 테스트 — 페이크 FinancialStatementProvider 주입."""

from dataclasses import dataclass
from decimal import Decimal

from pams.equity.application.load_growth_metrics import LoadGrowthMetrics
from pams.equity.domain.financial_statement import AnnualFinancials, AnnualFinancialsResult


@dataclass(frozen=True, slots=True)
class _FakeProvider:
    result: AnnualFinancialsResult

    def annual_financials(self, asset_id: str, *, years: int = 4) -> AnnualFinancialsResult:
        return self.result


class TestLoadGrowthMetrics:
    def test_computes_metrics_from_provider_result(self) -> None:
        fake = _FakeProvider(
            result=AnnualFinancialsResult(
                asset_id="AAPL",
                data_source="fake",
                annual=(
                    AnnualFinancials(fiscal_year=2022, revenue=Decimal(1000)),
                    AnnualFinancials(fiscal_year=2023, revenue=Decimal(1100)),
                    AnnualFinancials(fiscal_year=2024, revenue=Decimal(1210)),
                    AnnualFinancials(fiscal_year=2025, revenue=Decimal(1331)),
                ),
            )
        )
        report = LoadGrowthMetrics(provider=fake).execute("AAPL")
        assert report.financials.asset_id == "AAPL"
        assert report.metrics.revenue_cagr_3y is not None
        assert abs(report.metrics.revenue_cagr_3y - Decimal("0.10")) < Decimal("0.0001")
