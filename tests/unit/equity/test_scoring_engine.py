"""ScoringEngine 테스트. ai_stock 프로젝트(python/scoring.py)의 검증된 케이스를 이식."""

from datetime import date
from decimal import Decimal

from pams.equity.domain.score import Verdict
from pams.equity.domain.scoring_config import ScoringConfig
from pams.equity.domain.scoring_engine import (
    CompanyScoreInputs,
    RiskDeduction,
    score_company,
    score_competitiveness,
    score_growth,
    score_risk,
)

AS_OF = date(2026, 7, 17)


def _full_non_financial_inputs(**overrides: object) -> CompanyScoreInputs:
    """ai_stock python/scoring.py __main__ 자기점검과 동일한 입력값(총점 86점 기대)."""
    base = dict(
        symbol="TEST",
        as_of=AS_OF,
        data_source="manual",
        is_financial=False,
        revenue_cagr_3y=Decimal("0.16"),
        eps_cagr_3y=Decimal("0.13"),
        industry_tam_cagr=Decimal("0.11"),
        market_share_trend="up",
        gross_margin_vs_industry_pp=Decimal("0.06"),
        entry_barrier_regulatory=True,
        entry_barrier_capital_intensity="normal",
        entry_barrier_basis="규제 라이선스 +2, 자본집약 +1",
        roe=Decimal("0.18"),
        roic=Decimal("0.13"),
        wacc_estimate=Decimal("0.085"),
        wacc_basis="CAPM 예시",
        op_margin_industry_rank="top30",
        fcf_positive_years=3,
        debt_ratio=Decimal("0.4"),
        dcf_valuation_score=Decimal("6"),
        relative_valuation_score=Decimal("7"),
        risk_deductions=(
            RiskDeduction(reason="경쟁 심화 신호", points=Decimal(3), basis="신규 진입"),
        ),
    )
    base.update(overrides)
    return CompanyScoreInputs(**base)  # type: ignore[arg-type]


class TestScoreCompanyNonFinancial:
    def test_matches_ai_stock_reference_total(self, scoring_config: ScoringConfig) -> None:
        """ai_stock scoring.py __main__ 샘플과 완전히 동일한 입력 → 총점 86점, 매수 검토."""
        report = score_company(_full_non_financial_inputs(), scoring_config)
        assert report.total_score == Decimal(86)
        assert report.verdict is Verdict.BUY_REVIEW
        assert report.buy_score_condition_met is True

    def test_category_breakdown(self, scoring_config: ScoringConfig) -> None:
        report = score_company(_full_non_financial_inputs(), scoring_config)
        assert report.category("성장성").score == Decimal(10 + 7 + 10)  # 16%,13%,11%
        assert report.category("경쟁력").score == Decimal(8 + 8 + 3)  # up, +6%p, 진입장벽3
        assert report.category("재무").score == Decimal(5 + 5 + 4 + 3 + 3)
        assert report.category("밸류에이션").score == Decimal(6 + 7)
        assert report.category("리스크(감점)").score == Decimal(10 - 3)


class TestScoreGrowthFinancialSectorException:
    def test_uses_total_assets_cagr_instead_of_revenue(self, scoring_config: ScoringConfig) -> None:
        """신한지주 실측(2023→2025 총자산 CAGR≈6.6%) → 6~10% 구간 7점."""
        inputs = _full_non_financial_inputs(
            is_financial=True,
            revenue_cagr_3y=None,
            total_assets_cagr_3y=Decimal("0.066"),
            roa_vs_industry_pp=Decimal("0.0005"),
        )
        growth = score_growth(inputs, scoring_config)
        assert growth.items[0].metric == "총자산 3Y CAGR(금융업 대체지표)"
        assert growth.items[0].score == Decimal(7)

    def test_non_financial_uses_revenue_cagr(self, scoring_config: ScoringConfig) -> None:
        inputs = _full_non_financial_inputs()
        growth = score_growth(inputs, scoring_config)
        assert growth.items[0].metric == "매출 3Y CAGR"


class TestScoreCompetitivenessFinancialSectorException:
    def test_uses_roa_instead_of_gross_margin(self, scoring_config: ScoringConfig) -> None:
        inputs = _full_non_financial_inputs(is_financial=True, roa_vs_industry_pp=Decimal("0.0005"))
        comp = score_competitiveness(inputs, scoring_config)
        roa_item = next(i for i in comp.items if "ROA" in i.metric)
        assert roa_item.score == Decimal(4)  # ±0.2%p 이내


class TestMissingDataScoresZeroNotGuessed:
    def test_all_none_inputs_score_zero_with_reason(self, scoring_config: ScoringConfig) -> None:
        inputs = CompanyScoreInputs(symbol="EMPTY", as_of=AS_OF, data_source="manual")
        report = score_company(inputs, scoring_config)
        assert report.total_score == Decimal(10)  # 리스크만 기본 10점, 나머지는 전부 0
        assert report.verdict is Verdict.EXCLUDE
        growth_items = report.category("성장성").items
        assert all(item.score == Decimal(0) for item in growth_items)
        assert all("데이터 누락" in item.bucket or item.bucket for item in growth_items)


class TestScoreRiskCaps:
    def test_deduction_within_cap_applied_fully(self, scoring_config: ScoringConfig) -> None:
        inputs = CompanyScoreInputs(
            symbol="X",
            as_of=AS_OF,
            data_source="manual",
            risk_deductions=(
                RiskDeduction(reason="규제 리스크 확대", points=Decimal(3), basis="조사 착수"),
            ),
        )
        risk = score_risk(inputs, scoring_config)
        assert risk.score == Decimal(7)

    def test_deduction_exceeding_cap_is_capped(self, scoring_config: ScoringConfig) -> None:
        """ai_stock v1.1 버그 수정 대상: 카테고리 상한(3)을 초과한 입력(5)이 그대로
        반영되면 안 된다 — 캡이 적용돼 7점(=10-3)이어야 한다."""
        inputs = CompanyScoreInputs(
            symbol="X",
            as_of=AS_OF,
            data_source="manual",
            risk_deductions=(
                RiskDeduction(reason="규제 리스크 확대", points=Decimal(5), basis="과도한 입력"),
            ),
        )
        risk = score_risk(inputs, scoring_config)
        assert risk.score == Decimal(7)

    def test_undefined_category_capped_not_unlimited(self, scoring_config: ScoringConfig) -> None:
        """정의되지 않은 리스크 사유가 캡 없이 무제한 감점하던 버그(ai_stock에서 수정됨)의
        회귀 테스트 — 정의된 카테고리 중 최댓값(3)으로 캡되어야 한다."""
        inputs = CompanyScoreInputs(
            symbol="X",
            as_of=AS_OF,
            data_source="manual",
            risk_deductions=(RiskDeduction(reason="알수없는사유", points=Decimal(9)),),
        )
        risk = score_risk(inputs, scoring_config)
        assert risk.score == Decimal(7)  # 10 - min(9, undefined_cap=3)

    def test_score_never_below_zero(self, scoring_config: ScoringConfig) -> None:
        inputs = CompanyScoreInputs(
            symbol="X",
            as_of=AS_OF,
            data_source="manual",
            risk_deductions=(
                RiskDeduction(reason="규제 리스크 확대", points=Decimal(3)),
                RiskDeduction(reason="경쟁 심화 신호", points=Decimal(3)),
                RiskDeduction(reason="경기민감업종 & 경기 후행국면", points=Decimal(2)),
                RiskDeduction(reason="경영진 리스크 이슈", points=Decimal(2)),
            ),
        )
        risk = score_risk(inputs, scoring_config)
        assert risk.score == Decimal(0)

    def test_negative_points_input_rejected_as_deduction(
        self, scoring_config: ScoringConfig
    ) -> None:
        """리스크 항목에 음수(가점) 입력이 들어와도 실제로 가점되지 않아야 한다."""
        inputs = CompanyScoreInputs(
            symbol="X",
            as_of=AS_OF,
            data_source="manual",
            risk_deductions=(RiskDeduction(reason="규제 리스크 확대", points=Decimal(-5)),),
        )
        risk = score_risk(inputs, scoring_config)
        assert risk.score == Decimal(10)
