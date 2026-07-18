"""compare_industry_peers() 테스트. company_analysis_rules.md 3-2 업종평균 대비 지표를
DART induty_code/SEC SIC로 찾은 실제 피어 재무제표로 계산한다(임의 종목 지어내지 않음)."""

from decimal import Decimal

from pams.equity.domain.growth_metrics import GrowthMetrics
from pams.equity.domain.industry_classification import compare_industry_peers


def _metrics(**kwargs: object) -> GrowthMetrics:
    base = dict(
        revenue_cagr_3y=None,
        revenue_cagr_3y_note=None,
        eps_cagr_3y=None,
        eps_cagr_3y_note=None,
        total_assets_cagr_3y=None,
        total_assets_cagr_3y_note=None,
        fcf_positive_years=None,
        fcf_positive_years_note=None,
        gross_margin_latest=None,
        roa_latest=None,
        roe_latest=None,
        debt_ratio_latest=None,
        roic_latest=None,
        operating_margin_latest=None,
    )
    base.update(kwargs)
    return GrowthMetrics(**base)  # type: ignore[arg-type]


class TestNoPeers:
    def test_empty_peer_list_returns_none_with_note(self) -> None:
        result = compare_industry_peers(
            target=_metrics(gross_margin_latest=Decimal("0.4")),
            is_financial=False,
            peer_metrics=(),
        )
        assert result.peer_count == 0
        assert result.gross_margin_vs_industry_pp is None
        assert result.note is not None


class TestGrossMarginVsIndustry:
    def test_computes_pp_difference_from_peer_average_when_non_financial(self) -> None:
        result = compare_industry_peers(
            target=_metrics(gross_margin_latest=Decimal("0.40")),
            is_financial=False,
            peer_metrics=(
                _metrics(gross_margin_latest=Decimal("0.30")),
                _metrics(gross_margin_latest=Decimal("0.34")),
            ),
        )
        # 피어 평균 0.32, target 0.40 → +0.08(=8%p)
        assert result.gross_margin_vs_industry_pp == Decimal("0.08")

    def test_skipped_for_financial_sector(self) -> None:
        result = compare_industry_peers(
            target=_metrics(gross_margin_latest=Decimal("0.40")),
            is_financial=True,
            peer_metrics=(_metrics(gross_margin_latest=Decimal("0.30")),),
        )
        assert result.gross_margin_vs_industry_pp is None

    def test_none_when_peers_missing_the_metric(self) -> None:
        result = compare_industry_peers(
            target=_metrics(gross_margin_latest=Decimal("0.40")),
            is_financial=False,
            peer_metrics=(_metrics(),),
        )
        assert result.gross_margin_vs_industry_pp is None


class TestRoaVsIndustry:
    def test_computes_pp_difference_when_financial(self) -> None:
        result = compare_industry_peers(
            target=_metrics(roa_latest=Decimal("0.02")),
            is_financial=True,
            peer_metrics=(
                _metrics(roa_latest=Decimal("0.01")),
                _metrics(roa_latest=Decimal("0.015")),
            ),
        )
        assert result.roa_vs_industry_pp == Decimal("0.0075")

    def test_skipped_for_non_financial_sector(self) -> None:
        result = compare_industry_peers(
            target=_metrics(roa_latest=Decimal("0.02")),
            is_financial=False,
            peer_metrics=(_metrics(roa_latest=Decimal("0.01")),),
        )
        assert result.roa_vs_industry_pp is None


class TestOpMarginIndustryRank:
    def test_top30_when_target_is_highest(self) -> None:
        result = compare_industry_peers(
            target=_metrics(operating_margin_latest=Decimal("0.30")),
            is_financial=False,
            peer_metrics=(
                _metrics(operating_margin_latest=Decimal("0.10")),
                _metrics(operating_margin_latest=Decimal("0.15")),
            ),
        )
        assert result.op_margin_industry_rank == "top30"

    def test_bottom_when_target_is_lowest(self) -> None:
        result = compare_industry_peers(
            target=_metrics(operating_margin_latest=Decimal("0.05")),
            is_financial=False,
            peer_metrics=(
                _metrics(operating_margin_latest=Decimal("0.10")),
                _metrics(operating_margin_latest=Decimal("0.15")),
            ),
        )
        assert result.op_margin_industry_rank == "bottom"

    def test_mid_when_target_is_in_the_middle(self) -> None:
        result = compare_industry_peers(
            target=_metrics(operating_margin_latest=Decimal("0.10")),
            is_financial=False,
            peer_metrics=(
                _metrics(operating_margin_latest=Decimal("0.05")),
                _metrics(operating_margin_latest=Decimal("0.20")),
            ),
        )
        assert result.op_margin_industry_rank == "mid"

    def test_none_when_fewer_than_two_peers_have_the_metric(self) -> None:
        """피어가 1개뿐이면 top30/mid/bottom 구간 자체가 의미 없어 생략한다."""
        result = compare_industry_peers(
            target=_metrics(operating_margin_latest=Decimal("0.10")),
            is_financial=False,
            peer_metrics=(_metrics(operating_margin_latest=Decimal("0.05")),),
        )
        assert result.op_margin_industry_rank is None

    def test_none_when_target_metric_missing(self) -> None:
        result = compare_industry_peers(
            target=_metrics(),
            is_financial=False,
            peer_metrics=(
                _metrics(operating_margin_latest=Decimal("0.05")),
                _metrics(operating_margin_latest=Decimal("0.10")),
            ),
        )
        assert result.op_margin_industry_rank is None
