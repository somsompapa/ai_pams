"""ScoringEngine이 필요로 하는 모든 구간표/설정값 — config/equity_scoring/*.yaml에서 로드된다.

CLAUDE.md 절대원칙 #2: 투자 규칙은 코드에 하드코딩하지 않는다. 이 파일은 "설정값을 담는
그릇"의 형태(dataclass)만 정의하고, 실제 경계값·점수는 infrastructure의 YAML 로더가 채운다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pams.equity.domain.relative_valuation import RelativeValuationConfig
from pams.shared_kernel.domain import BandTable, CategoricalTable, DomainValidationError


@dataclass(frozen=True, slots=True)
class EntryBarrierConfig:
    """진입장벽 체크리스트 배점(company_analysis_rules.md 3-2 v1.1 정량화)."""

    max_score: Decimal
    regulatory_points: Decimal
    capital_intensity_normal_points: Decimal
    capital_intensity_extreme_points: Decimal
    network_effect_points: Decimal

    def total(self, *, regulatory: bool, capital_intensity: str, network_effect: bool) -> Decimal:
        """capital_intensity: 'none' | 'normal' | 'extreme' (배타적 — extreme이 normal을 대체)."""
        points = Decimal(0)
        if regulatory:
            points += self.regulatory_points
        if capital_intensity == "extreme":
            points += self.capital_intensity_extreme_points
        elif capital_intensity == "normal":
            points += self.capital_intensity_normal_points
        if network_effect:
            points += self.network_effect_points
        return min(points, self.max_score)


@dataclass(frozen=True, slots=True)
class RiskConfig:
    """리스크 감점(3-5). base_score에서 category_caps 한도 내로 차감."""

    base_score: Decimal
    category_caps: dict[str, Decimal]
    undefined_category_cap: Decimal

    def __post_init__(self) -> None:
        if not self.category_caps:
            raise DomainValidationError("risk.category_caps가 비어 있다")


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    """company_analysis_rules.md 3장 전체 배점표. is_financial=True면 *_financial_* 필드가
    대응하는 일반 필드를 대체한다(company_analysis_rules.md 3-1/3-2 금융업 예외, v1.5.6)."""

    # 3-1 성장성(30)
    revenue_cagr_3y: BandTable
    eps_cagr_3y: BandTable
    industry_tam_cagr: BandTable
    financial_sector_total_assets_cagr_3y: BandTable  # 금융업: 매출 3Y CAGR 대체

    # 3-2 경쟁력(20)
    market_share_trend: CategoricalTable
    gross_margin_vs_industry: BandTable
    financial_sector_roa_vs_industry: BandTable  # 금융업: 매출총이익률 대체
    entry_barrier: EntryBarrierConfig

    # 3-3 재무(20)
    roe: BandTable
    roic_minus_wacc_spread: BandTable
    op_margin_industry_rank: CategoricalTable
    fcf_positive_years: CategoricalTable
    debt_ratio: BandTable

    # 3-4 밸류에이션(20) — DCF(주계산, 요청별 가정으로 별도 계산·score.py 밖에서 처리)는
    # 여기 없다. 상대지표(PER/PBR/PEG)는 고정 임계값(rulebook 정량표)이라 설정에 포함한다.
    relative_valuation: RelativeValuationConfig

    # 3-5 리스크(10, 감점)
    risk: RiskConfig
