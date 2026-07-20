"""equity 도메인 테스트 공용 픽스처 — company_analysis_rules.md 실제 임계값으로 구성한
ScoringConfig. config/equity_scoring/default.yaml과 값이 같아야 한다(불일치하면
tests/unit/equity/test_yaml_scoring_config.py가 잡아낸다)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pams.equity.domain.relative_valuation import RelativeValuationConfig
from pams.equity.domain.scoring_config import EntryBarrierConfig, RiskConfig, ScoringConfig
from pams.shared_kernel.domain import (
    Band,
    BandDirection,
    BandTable,
    CategoricalOption,
    CategoricalTable,
)


def _cagr_10pt(metric: str) -> BandTable:
    """매출/EPS 3Y CAGR 공통 구간표(≥15%→10, 10~15%→7, 5~10%→4, <5%→0)."""
    return BandTable(
        metric=metric,
        max_score=Decimal(10),
        direction=BandDirection.HIGHER_IS_BETTER,
        bands=(
            Band(bound=Decimal("0.15"), score=Decimal(10), label="≥15%"),
            Band(bound=Decimal("0.10"), score=Decimal(7), label="10~15%"),
            Band(bound=Decimal("0.05"), score=Decimal(4), label="5~10%"),
            Band(bound=Decimal("-Infinity"), score=Decimal(0), label="<5%"),
        ),
    )


@pytest.fixture
def scoring_config() -> ScoringConfig:
    return ScoringConfig(
        revenue_cagr_3y=_cagr_10pt("매출 3Y CAGR"),
        eps_cagr_3y=_cagr_10pt("EPS 3Y CAGR"),
        industry_tam_cagr=BandTable(
            metric="산업 TAM CAGR",
            max_score=Decimal(10),
            direction=BandDirection.HIGHER_IS_BETTER,
            bands=(
                Band(bound=Decimal("0.10"), score=Decimal(10), label="≥10%"),
                Band(bound=Decimal("0.05"), score=Decimal(6), label="5~10%"),
                Band(bound=Decimal("-Infinity"), score=Decimal(2), label="<5%"),
            ),
        ),
        financial_sector_total_assets_cagr_3y=BandTable(
            metric="총자산 3Y CAGR(금융업)",
            max_score=Decimal(10),
            direction=BandDirection.HIGHER_IS_BETTER,
            bands=(
                Band(bound=Decimal("0.10"), score=Decimal(10), label="≥10%"),
                Band(bound=Decimal("0.06"), score=Decimal(7), label="6~10%"),
                Band(bound=Decimal("0.03"), score=Decimal(4), label="3~6%"),
                Band(bound=Decimal("-Infinity"), score=Decimal(0), label="<3%"),
            ),
        ),
        market_share_trend=CategoricalTable(
            metric="시장점유율 추이(3년)",
            max_score=Decimal(8),
            options={
                "up": CategoricalOption(score=Decimal(8), label="상승"),
                "flat": CategoricalOption(score=Decimal(4), label="횡보"),
                "down": CategoricalOption(score=Decimal(0), label="하락"),
            },
        ),
        gross_margin_vs_industry=BandTable(
            metric="매출총이익률(업종 대비 %p)",
            max_score=Decimal(8),
            direction=BandDirection.HIGHER_IS_BETTER,
            bands=(
                Band(bound=Decimal("0.05"), score=Decimal(8), label="업종평균 +5%p 이상"),
                Band(bound=Decimal("-0.05"), score=Decimal(4), label="±5%p 이내"),
                Band(bound=Decimal("-Infinity"), score=Decimal(0), label="-5%p 이하"),
            ),
        ),
        financial_sector_roa_vs_industry=BandTable(
            metric="ROA(업종평균 대비, 금융업)",
            max_score=Decimal(8),
            direction=BandDirection.HIGHER_IS_BETTER,
            bands=(
                Band(bound=Decimal("0.002"), score=Decimal(8), label="업종평균 +0.2%p 이상"),
                Band(bound=Decimal("-0.002"), score=Decimal(4), label="±0.2%p 이내"),
                Band(bound=Decimal("-Infinity"), score=Decimal(0), label="-0.2%p 이하"),
            ),
        ),
        entry_barrier=EntryBarrierConfig(
            max_score=Decimal(4),
            regulatory_points=Decimal(2),
            capital_intensity_normal_points=Decimal(1),
            capital_intensity_extreme_points=Decimal(2),
            network_effect_points=Decimal(1),
        ),
        roe=BandTable(
            metric="ROE",
            max_score=Decimal(5),
            direction=BandDirection.HIGHER_IS_BETTER,
            bands=(
                Band(bound=Decimal("0.15"), score=Decimal(5), label="≥15%"),
                Band(bound=Decimal("0.10"), score=Decimal(3), label="10~15%"),
                Band(bound=Decimal("-Infinity"), score=Decimal(0), label="<10%"),
            ),
        ),
        roic_minus_wacc_spread=BandTable(
            metric="ROIC vs WACC",
            max_score=Decimal(5),
            direction=BandDirection.HIGHER_IS_BETTER,
            bands=(
                Band(bound=Decimal("0.03"), score=Decimal(5), label="≥WACC+3%p"),
                Band(bound=Decimal("0"), score=Decimal(3), label="WACC~WACC+3%p"),
                Band(bound=Decimal("-Infinity"), score=Decimal(0), label="<WACC"),
            ),
        ),
        op_margin_industry_rank=CategoricalTable(
            metric="영업이익률(업종 순위)",
            max_score=Decimal(4),
            options={
                "top30": CategoricalOption(score=Decimal(4), label="업종 상위30%"),
                "mid": CategoricalOption(score=Decimal(2), label="중위"),
                "bottom": CategoricalOption(score=Decimal(0), label="하위"),
            },
        ),
        fcf_positive_years=CategoricalTable(
            metric="FCF 흑자 연도수(3년)",
            max_score=Decimal(3),
            options={
                "3": CategoricalOption(score=Decimal(3), label="3년 흑자"),
                "2": CategoricalOption(score=Decimal(2), label="2년 흑자"),
                "1": CategoricalOption(score=Decimal(0), label="1년 이하"),
                "0": CategoricalOption(score=Decimal(0), label="1년 이하"),
            },
        ),
        debt_ratio=BandTable(
            metric="부채비율(총부채기준)",
            max_score=Decimal(3),
            direction=BandDirection.LOWER_IS_BETTER,
            bands=(
                Band(bound=Decimal("1.0"), score=Decimal(3), label="≤100%"),
                Band(bound=Decimal("2.0"), score=Decimal(1), label="100~200%"),
                Band(bound=Decimal("Infinity"), score=Decimal(0), label=">200%"),
            ),
        ),
        relative_valuation=RelativeValuationConfig(
            per_max_score=Decimal(5),
            pbr_max_score=Decimal(3),
            percentile_ratio=BandTable(
                metric="PER/PBR 5년밴드 백분위→배점비율",
                max_score=Decimal(1),
                direction=BandDirection.LOWER_IS_BETTER,
                bands=(
                    Band(bound=Decimal("0.20"), score=Decimal("1.00"), label="하위 20% 이내"),
                    Band(bound=Decimal("0.40"), score=Decimal("0.75"), label="20~40%"),
                    Band(bound=Decimal("0.60"), score=Decimal("0.50"), label="40~60%(중간)"),
                    Band(bound=Decimal("0.80"), score=Decimal("0.25"), label="60~80%"),
                    Band(bound=Decimal("Infinity"), score=Decimal("0.00"), label="80% 초과(상단)"),
                ),
            ),
            peg_adjustment=BandTable(
                metric="PEG 보정",
                max_score=Decimal(2),
                direction=BandDirection.LOWER_IS_BETTER,
                bands=(
                    Band(bound=Decimal("1.0"), score=Decimal(2), label="<1.0"),
                    Band(bound=Decimal("2.0"), score=Decimal(0), label="1.0~2.0"),
                    Band(bound=Decimal("Infinity"), score=Decimal(-2), label=">2.0"),
                ),
            ),
        ),
        risk=RiskConfig(
            base_score=Decimal(10),
            category_caps={
                "규제 리스크 확대": Decimal(3),
                "경쟁 심화 신호": Decimal(3),
                "경기민감업종 & 경기 후행국면": Decimal(2),
                "경영진 리스크 이슈": Decimal(2),
            },
            undefined_category_cap=Decimal(3),
        ),
    )
