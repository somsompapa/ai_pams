"""기업 100점 스코어링 엔진 — company_analysis_rules.md 3장 구현.

ai_stock 프로젝트(python/scoring.py)의 검증된 로직을 PAMS 컨벤션(Decimal, 값객체,
config 기반 구간표)으로 이식한다.

설계 원칙(ai_stock에서 실제로 잡은 버그들을 반영):
  - 데이터 누락은 임의 추정하지 않고 0점 + "데이터 누락" 근거를 남긴다.
  - is_financial=True(은행/보험/증권/지주)면 매출 3Y CAGR·매출총이익률 대신 총자산
    3Y CAGR·ROA(업종평균 대비)를 쓴다 — K-IFRS상 금융업에는 매출/매출원가 개념
    자체가 없다(company_analysis_rules.md 3-1/3-2 금융업 예외, ai_stock v1.5.6에서
    신한지주 실측으로 검증).
  - 리스크 감점은 정의된 4개 카테고리별 상한을 넘지 못한다(무제한 감점 방지).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pams.equity.domain.score import CategoryScore, CompanyScoreReport, ScoreItem
from pams.equity.domain.scoring_config import ScoringConfig


@dataclass(frozen=True, slots=True)
class RiskDeduction:
    reason: str
    points: Decimal
    basis: str = ""


@dataclass(frozen=True, slots=True)
class CompanyScoreInputs:
    """score_company()의 입력. None/미설정 필드는 "데이터 누락"으로 0점 처리된다."""

    symbol: str
    as_of: date
    data_source: str
    is_financial: bool = False

    # 3-1 성장성
    revenue_cagr_3y: Decimal | None = None
    eps_cagr_3y: Decimal | None = None
    industry_tam_cagr: Decimal | None = None
    total_assets_cagr_3y: Decimal | None = None  # 금융업 대체지표

    # 3-2 경쟁력
    market_share_trend: str | None = None  # 'up' | 'flat' | 'down'
    gross_margin_vs_industry_pp: Decimal | None = None
    roa_vs_industry_pp: Decimal | None = None  # 금융업 대체지표
    entry_barrier_regulatory: bool = False
    entry_barrier_capital_intensity: str = "none"  # 'none' | 'normal' | 'extreme'
    entry_barrier_network_effect: bool = False
    entry_barrier_basis: str = ""

    # 3-3 재무
    roe: Decimal | None = None
    roic: Decimal | None = None
    wacc_estimate: Decimal | None = None
    wacc_basis: str = ""
    op_margin_industry_rank: str | None = None  # 'top30' | 'mid' | 'bottom'
    fcf_positive_years: int | None = None
    debt_ratio: Decimal | None = None  # v1.4 정의: 총부채/자기자본. is_financial이면 예외 처리.
    debt_ratio_interest_bearing: Decimal | None = None  # 감점 시 보조지표
    debt_ratio_basis: str = ""

    # 3-4 밸류에이션 (dcf.py/relative_valuation 유스케이스가 계산해 주입)
    dcf_valuation_score: Decimal | None = None
    relative_valuation_score: Decimal | None = None

    # 3-5 리스크
    risk_deductions: tuple[RiskDeduction, ...] = ()

    data_quality_flags: tuple[str, ...] = field(default_factory=tuple)


_DISPLAY_QUANTIZE = Decimal("0.0001")


def _display(value: Decimal) -> str:
    """근거표 표시용 반올림(4자리) — CAGR은 ln()/exp()로 계산돼 전체 정밀도(28자리)를
    그대로 str()하면 근거표가 읽기 어렵다. 채점 자체는 원본 Decimal로 이미 끝난 뒤이므로
    표시값만 반올림해도 점수 정확도에는 영향이 없다(ai_stock의 round(v*100, 2)와 동일 취지)."""
    return str(value.quantize(_DISPLAY_QUANTIZE))


def _missing(metric: str, max_score: Decimal, reason: str = "데이터 누락") -> ScoreItem:
    return ScoreItem(
        metric=metric,
        value="—",
        bucket=reason,
        score=Decimal(0),
        max_score=max_score,
        note="임의추정 금지 → 0점",
    )


def score_growth(inputs: CompanyScoreInputs, config: ScoringConfig) -> CategoryScore:
    items: list[ScoreItem] = []

    if inputs.is_financial:
        table = config.financial_sector_total_assets_cagr_3y
        value = inputs.total_assets_cagr_3y
        metric = "총자산 3Y CAGR(금융업 대체지표)"
    else:
        table = config.revenue_cagr_3y
        value = inputs.revenue_cagr_3y
        metric = "매출 3Y CAGR"
    if value is None:
        items.append(_missing(metric, table.max_score))
    else:
        band = table.score_for(value)
        items.append(
            ScoreItem(
                metric=metric,
                value=_display(value),
                bucket=band.label,
                score=band.score,
                max_score=table.max_score,
            )
        )

    if inputs.eps_cagr_3y is None:
        items.append(_missing("EPS 3Y CAGR", config.eps_cagr_3y.max_score))
    else:
        band = config.eps_cagr_3y.score_for(inputs.eps_cagr_3y)
        items.append(
            ScoreItem(
                metric="EPS 3Y CAGR",
                value=_display(inputs.eps_cagr_3y),
                bucket=band.label,
                score=band.score,
                max_score=config.eps_cagr_3y.max_score,
            )
        )

    if inputs.industry_tam_cagr is None:
        items.append(_missing("산업 TAM CAGR", config.industry_tam_cagr.max_score))
    else:
        band = config.industry_tam_cagr.score_for(inputs.industry_tam_cagr)
        items.append(
            ScoreItem(
                metric="산업 TAM CAGR",
                value=_display(inputs.industry_tam_cagr),
                bucket=band.label,
                score=band.score,
                max_score=config.industry_tam_cagr.max_score,
            )
        )

    total = sum((item.score for item in items), Decimal(0))
    return CategoryScore(category="성장성", max_score=Decimal(30), score=total, items=tuple(items))


def score_competitiveness(inputs: CompanyScoreInputs, config: ScoringConfig) -> CategoryScore:
    items: list[ScoreItem] = []

    trend_table = config.market_share_trend
    if inputs.market_share_trend is None:
        items.append(_missing("시장점유율 추이(3년)", trend_table.max_score))
    else:
        option = trend_table.score_for(inputs.market_share_trend)
        if option is None:
            items.append(
                _missing(
                    "시장점유율 추이(3년)",
                    trend_table.max_score,
                    reason=f"미정의 값({inputs.market_share_trend})",
                )
            )
        else:
            items.append(
                ScoreItem(
                    metric="시장점유율 추이(3년)",
                    value=inputs.market_share_trend,
                    bucket=option.label,
                    score=option.score,
                    max_score=trend_table.max_score,
                )
            )

    if inputs.is_financial:
        table = config.financial_sector_roa_vs_industry
        value = inputs.roa_vs_industry_pp
        metric = "ROA(업종평균 대비, 금융업 대체지표)"
    else:
        table = config.gross_margin_vs_industry
        value = inputs.gross_margin_vs_industry_pp
        metric = "매출총이익률(업종 대비 %p)"
    if value is None:
        items.append(_missing(metric, table.max_score))
    else:
        band = table.score_for(value)
        items.append(
            ScoreItem(
                metric=metric,
                value=_display(value),
                bucket=band.label,
                score=band.score,
                max_score=table.max_score,
            )
        )

    eb = config.entry_barrier
    eb_score = eb.total(
        regulatory=inputs.entry_barrier_regulatory,
        capital_intensity=inputs.entry_barrier_capital_intensity,
        network_effect=inputs.entry_barrier_network_effect,
    )
    note = inputs.entry_barrier_basis or "⚠️ 근거 문장 미기재 — 점수 무효 처리 권장"
    items.append(
        ScoreItem(
            metric="진입장벽(정성)",
            value=str(eb_score),
            bucket="체크리스트 합산",
            score=eb_score,
            max_score=eb.max_score,
            note=note,
        )
    )

    total = sum((item.score for item in items), Decimal(0))
    return CategoryScore(category="경쟁력", max_score=Decimal(20), score=total, items=tuple(items))


def score_financials(inputs: CompanyScoreInputs, config: ScoringConfig) -> CategoryScore:
    items: list[ScoreItem] = []

    if inputs.roe is None:
        items.append(_missing("ROE", config.roe.max_score))
    else:
        band = config.roe.score_for(inputs.roe)
        items.append(
            ScoreItem(
                metric="ROE",
                value=_display(inputs.roe),
                bucket=band.label,
                score=band.score,
                max_score=config.roe.max_score,
            )
        )

    if inputs.roic is None or inputs.wacc_estimate is None:
        missing = [
            name
            for name, val in (("ROIC", inputs.roic), ("WACC", inputs.wacc_estimate))
            if val is None
        ]
        items.append(
            _missing(
                "ROIC vs WACC",
                config.roic_minus_wacc_spread.max_score,
                reason=f"{'·'.join(missing)} 누락",
            )
        )
    else:
        spread = inputs.roic - inputs.wacc_estimate
        band = config.roic_minus_wacc_spread.score_for(spread)
        items.append(
            ScoreItem(
                metric="ROIC vs WACC",
                value=f"ROIC={inputs.roic}, WACC={inputs.wacc_estimate}",
                bucket=band.label,
                score=band.score,
                max_score=config.roic_minus_wacc_spread.max_score,
                note=inputs.wacc_basis or "WACC 근거 기재 필요",
            )
        )

    rank_table = config.op_margin_industry_rank
    if inputs.op_margin_industry_rank is None:
        items.append(_missing("영업이익률(업종 순위)", rank_table.max_score))
    else:
        option = rank_table.score_for(inputs.op_margin_industry_rank)
        if option is None:
            items.append(
                _missing(
                    "영업이익률(업종 순위)",
                    rank_table.max_score,
                    reason=f"미정의 값({inputs.op_margin_industry_rank})",
                )
            )
        else:
            items.append(
                ScoreItem(
                    metric="영업이익률(업종 순위)",
                    value=inputs.op_margin_industry_rank,
                    bucket=option.label,
                    score=option.score,
                    max_score=rank_table.max_score,
                )
            )

    fcf_table = config.fcf_positive_years
    if inputs.fcf_positive_years is None:
        items.append(_missing("FCF 흑자 연도수(3년)", fcf_table.max_score))
    else:
        option = fcf_table.score_for(str(inputs.fcf_positive_years))
        if option is None:
            items.append(
                _missing(
                    "FCF 흑자 연도수(3년)",
                    fcf_table.max_score,
                    reason=f"미정의 값({inputs.fcf_positive_years})",
                )
            )
        else:
            items.append(
                ScoreItem(
                    metric="FCF 흑자 연도수(3년)",
                    value=str(inputs.fcf_positive_years),
                    bucket=option.label,
                    score=option.score,
                    max_score=fcf_table.max_score,
                )
            )

    if inputs.is_financial:
        items.append(
            ScoreItem(
                metric="부채비율",
                value=_display(inputs.debt_ratio) if inputs.debt_ratio is not None else "—",
                bucket="금융업 예외",
                score=Decimal(0),
                max_score=config.debt_ratio.max_score,
                note=(
                    "⚠️ 금융업: 부채비율 일반기준 미적용. "
                    "자본적정성(BIS/지급여력)으로 별도 평가 필요"
                ),
            )
        )
    elif inputs.debt_ratio is None:
        items.append(_missing("부채비율", config.debt_ratio.max_score))
    else:
        band = config.debt_ratio.score_for(inputs.debt_ratio)
        note = ""
        if band.score < config.debt_ratio.max_score:
            if inputs.debt_ratio_interest_bearing is not None:
                note = (
                    f"보조지표(이자부채기준): {inputs.debt_ratio_interest_bearing}. "
                    f"{inputs.debt_ratio_basis}"
                )
            else:
                note = (
                    "⚠️ 감점 발생 — 이자부채기준 보조지표 병기 권장(company_analysis_rules.md 3-3)"
                )
        items.append(
            ScoreItem(
                metric="부채비율(총부채기준)",
                value=_display(inputs.debt_ratio),
                bucket=band.label,
                score=band.score,
                max_score=config.debt_ratio.max_score,
                note=note,
            )
        )

    total = sum((item.score for item in items), Decimal(0))
    return CategoryScore(category="재무", max_score=Decimal(20), score=total, items=tuple(items))


def score_valuation(inputs: CompanyScoreInputs) -> CategoryScore:
    """DCF/상대지표 점수는 별도 유스케이스(dcf.py 등)가 계산해 여기 주입한다 —
    이 함수는 순수하게 조립만 한다."""
    items: list[ScoreItem] = []
    if inputs.dcf_valuation_score is None:
        items.append(_missing("DCF 괴리율 점수", Decimal(10), reason="미산출"))
    else:
        score = max(Decimal(0), min(Decimal(10), inputs.dcf_valuation_score))
        items.append(
            ScoreItem(
                metric="DCF 괴리율 점수",
                value=str(score),
                bucket="valuation.dcf 산출",
                score=score,
                max_score=Decimal(10),
            )
        )

    if inputs.relative_valuation_score is None:
        items.append(_missing("상대지표(PER/PBR/PEG)", Decimal(10), reason="미산출"))
    else:
        score = max(Decimal(0), min(Decimal(10), inputs.relative_valuation_score))
        items.append(
            ScoreItem(
                metric="상대지표(PER/PBR/PEG)",
                value=str(score),
                bucket="밴드/업종 위치",
                score=score,
                max_score=Decimal(10),
            )
        )

    total = sum((item.score for item in items), Decimal(0))
    return CategoryScore(
        category="밸류에이션", max_score=Decimal(20), score=total, items=tuple(items)
    )


def score_risk(inputs: CompanyScoreInputs, config: ScoringConfig) -> CategoryScore:
    items: list[ScoreItem] = []
    score = config.risk.base_score
    for deduction in inputs.risk_deductions:
        points = max(Decimal(0), deduction.points)  # 감점 전용 — 음수(가점) 입력 방지
        cap = config.risk.category_caps.get(deduction.reason)
        note = deduction.basis
        if cap is None:
            undefined_cap = config.risk.undefined_category_cap
            reclassify = (
                f"⚠️ 미정의 리스크 카테고리('{deduction.reason}') — 정의된 카테고리로 재분류 필요"
            )
            if points > undefined_cap:
                note = f"{reclassify}. 최대 {undefined_cap}점으로 캡"
                points = undefined_cap
            else:
                note = note or reclassify
        elif points > cap:
            note = f"⚠️ 최대 차감 {cap} 초과 입력({points}) → {cap}로 캡"
            points = cap
        score -= points
        items.append(
            ScoreItem(
                metric="리스크 감점",
                value=deduction.reason,
                bucket=f"-{points}",
                score=-points,
                max_score=Decimal(0),
                note=note,
            )
        )
    score = max(Decimal(0), score)
    if not inputs.risk_deductions:
        items.append(
            ScoreItem(
                metric="리스크 감점",
                value="해당 없음",
                bucket="차감 사유 없음",
                score=Decimal(0),
                max_score=Decimal(0),
                note=f"기본 {config.risk.base_score}점 유지",
            )
        )
    return CategoryScore(
        category="리스크(감점)", max_score=config.risk.base_score, score=score, items=tuple(items)
    )


def score_company(inputs: CompanyScoreInputs, config: ScoringConfig) -> CompanyScoreReport:
    """기업 100점 종합 산출. 항목별 근거표 포함 리포트를 반환한다(3-7 필수 출력 형식)."""
    categories = (
        score_growth(inputs, config),
        score_competitiveness(inputs, config),
        score_financials(inputs, config),
        score_valuation(inputs),
        score_risk(inputs, config),
    )
    return CompanyScoreReport(
        symbol=inputs.symbol,
        as_of=inputs.as_of,
        data_source=inputs.data_source,
        categories=categories,
        data_quality_flags=inputs.data_quality_flags,
    )
