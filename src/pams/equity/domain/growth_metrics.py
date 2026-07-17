"""연간 재무제표 시계열 → 성장성/수익성 지표(3Y CAGR, FCF 흑자연도, ROA) 계산.

ai_stock 프로젝트 data_loader.compute_growth_metrics()의 검증된 로직을 이식.
CAGR은 Decimal의 ln()/exp()로 계산한다(risk/domain/measures.py의 cagr()과 동일 관례 —
Decimal은 분수 지수의 **를 직접 지원하지 않는다).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from pams.equity.domain.financial_statement import AnnualFinancials

_THREE_YEARS = Decimal(3)


@dataclass(frozen=True, slots=True)
class GrowthMetrics:
    revenue_cagr_3y: Decimal | None
    revenue_cagr_3y_note: str | None
    eps_cagr_3y: Decimal | None
    eps_cagr_3y_note: str | None
    total_assets_cagr_3y: Decimal | None
    total_assets_cagr_3y_note: str | None
    fcf_positive_years: int | None
    fcf_positive_years_note: str | None
    gross_margin_latest: Decimal | None
    roa_latest: Decimal | None


def _cagr_3y(
    annual_sorted: tuple[AnnualFinancials, ...],
    label: str,
    getter: Callable[[AnnualFinancials], Decimal | None],
) -> tuple[Decimal | None, str | None]:
    if len(annual_sorted) < 4:  # t-3~t, 4개 데이터포인트 필요(3년 CAGR)
        return (
            None,
            f"{label} 3Y CAGR 계산 불가 — 최소 4개년(t-3~t) 데이터 필요, "
            f"현재 {len(annual_sorted)}개년",
        )
    begin = getter(annual_sorted[-4])
    end = getter(annual_sorted[-1])
    if begin is None or end is None or begin <= 0:
        return None, f"{label} 3Y CAGR 계산 불가 — 기초/기말 값 누락 또는 기초값 0 이하"
    growth = end / begin
    return (growth.ln() / _THREE_YEARS).exp() - 1, None


def compute_growth_metrics(annual: tuple[AnnualFinancials, ...]) -> GrowthMetrics:
    """연도별 재무(annual, 순서 무관 — 내부에서 fiscal_year 오름차순 정렬)로부터
    3장 채점용 지표를 계산한다. 데이터가 부족하거나 값이 없으면 None + 사유를 반환한다
    (0으로 조용히 채우지 않는다 — data_loader.py 설계 원칙 그대로)."""
    sorted_annual = tuple(sorted(annual, key=lambda a: a.fiscal_year))

    revenue_cagr, revenue_note = _cagr_3y(sorted_annual, "매출", lambda a: a.revenue)
    eps_cagr, eps_note = _cagr_3y(sorted_annual, "EPS", lambda a: a.eps)
    assets_cagr, assets_note = _cagr_3y(sorted_annual, "총자산", lambda a: a.total_assets)

    recent3 = sorted_annual[-3:]
    fcf_years: int | None
    fcf_note: str | None
    if len(recent3) < 3:
        fcf_years, fcf_note = None, f"최근 3개년 데이터 부족(현재 {len(recent3)}개년) — 판단 보류"
    else:
        fcfs = [a.fcf for a in recent3]
        if any(v is None for v in fcfs):
            fcf_years, fcf_note = None, "일부 연도 FCF 값 누락 — 임의 추정 금지, 판단 보류"
        else:
            fcf_years = sum(1 for v in fcfs if v is not None and v > 0)
            fcf_note = None

    gross_margin: Decimal | None = None
    roa: Decimal | None = None
    if sorted_annual:
        last = sorted_annual[-1]
        if last.revenue is not None and last.revenue > 0 and last.gross_profit is not None:
            gross_margin = last.gross_profit / last.revenue
        if last.total_assets is not None and last.total_assets > 0 and last.net_income is not None:
            roa = last.net_income / last.total_assets

    return GrowthMetrics(
        revenue_cagr_3y=revenue_cagr,
        revenue_cagr_3y_note=revenue_note,
        eps_cagr_3y=eps_cagr,
        eps_cagr_3y_note=eps_note,
        total_assets_cagr_3y=assets_cagr,
        total_assets_cagr_3y_note=assets_note,
        fcf_positive_years=fcf_years,
        fcf_positive_years_note=fcf_note,
        gross_margin_latest=gross_margin,
        roa_latest=roa,
    )
