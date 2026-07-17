"""config/equity_scoring/default.yaml이 실제로 파싱되고, 도메인 테스트의 in-Python
픽스처(tests/unit/equity/conftest.py)와 동일한 채점 결과를 내는지 확인한다.

이 두 개가 어긋나면(YAML 수정 후 픽스처를 안 맞췄다든지) 실제 운영 설정과 테스트가
다른 걸 테스트하는 셈이 되어 아무 의미가 없다 — 그래서 반드시 실 YAML로도 동일한
회귀 케이스(ai_stock 86점 샘플)를 검증한다.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

from pams.equity.domain.relative_valuation import relative_valuation_score
from pams.equity.domain.scoring_engine import CompanyScoreInputs, RiskDeduction, score_company
from pams.equity.infrastructure.yaml_scoring_config import YamlScoringConfigLoader

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "equity_scoring" / "default.yaml"


class TestYamlScoringConfigLoader:
    def test_loads_and_reproduces_ai_stock_reference_score(self) -> None:
        config = YamlScoringConfigLoader(_CONFIG_PATH).load()
        inputs = CompanyScoreInputs(
            symbol="TEST",
            as_of=date(2026, 7, 17),
            data_source="manual",
            revenue_cagr_3y=Decimal("0.16"),
            eps_cagr_3y=Decimal("0.13"),
            industry_tam_cagr=Decimal("0.11"),
            market_share_trend="up",
            gross_margin_vs_industry_pp=Decimal("0.06"),
            entry_barrier_regulatory=True,
            entry_barrier_capital_intensity="normal",
            entry_barrier_basis="테스트",
            roe=Decimal("0.18"),
            roic=Decimal("0.13"),
            wacc_estimate=Decimal("0.085"),
            op_margin_industry_rank="top30",
            fcf_positive_years=3,
            debt_ratio=Decimal("0.4"),
            dcf_valuation_score=Decimal("6"),
            relative_valuation_score=Decimal("7"),
            risk_deductions=(RiskDeduction(reason="경쟁 심화 신호", points=Decimal(3)),),
        )
        report = score_company(inputs, config)
        assert report.total_score == Decimal(86)

    def test_financial_sector_bands_load(self) -> None:
        config = YamlScoringConfigLoader(_CONFIG_PATH).load()
        band = config.financial_sector_total_assets_cagr_3y.score_for(Decimal("0.066"))
        assert band.score == Decimal(7)
        roa_band = config.financial_sector_roa_vs_industry.score_for(Decimal("0.0005"))
        assert roa_band.score == Decimal(4)

    def test_relative_valuation_bands_load(self) -> None:
        config = YamlScoringConfigLoader(_CONFIG_PATH).load()
        result = relative_valuation_score(
            per_band_percentile=Decimal("0.15"),
            pbr_band_percentile=Decimal("0.50"),
            peg=Decimal("0.8"),
            config=config.relative_valuation,
        )
        assert result.score == Decimal("8.50")
