"""PER/PBR 5년밴드 백분위. valuation_rules.md V-2 (1)/company_analysis_rules.md 3-4 —
종목 자신의 과거 결산연도별 PER/PBR 분포 내에서 현재 PER/PBR이 어디에 위치하는지
계산한다(업종 평균이 아니라 자기 자신의 과거 밴드).

연도별 가격은 해당 연도 내 관측치 중 가장 늦은 값으로 근사한다 — 정확한 결산일을
추적하지 않으므로(fiscal_year는 정수 연도일 뿐이라 미국처럼 회계연도가 12월 말이
아닌 회사는 오차가 있을 수 있다) 이 근사가 필요하다. 표본이 최근 몇 개 결산연도뿐이라
데일리 밴드보다 훨씬 성긴(coarse) 백분위라는 한계도 있다 — 실측 데이터로 계산하되
이 한계는 숨기지 않는다(임의추정 금지 원칙은 정밀도를 부풀리지 않는 것도 포함한다).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pams.equity.domain.financial_statement import AnnualFinancials
from pams.market_data.domain import Quote

# 현재값 포함 3개 미만이면 백분위 구간이 너무 성겨(0%/100% 양극단뿐) 의미가 없다.
_MIN_HISTORICAL_POINTS = 2


@dataclass(frozen=True, slots=True)
class PriceBandResult:
    per_band_percentile: Decimal | None
    pbr_band_percentile: Decimal | None
    note: str | None


def _year_end_price(prices: tuple[Quote, ...], year: int) -> Decimal | None:
    candidates = [p for p in prices if p.quote_date.year == year]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.quote_date).close


def _percentile_rank(current: Decimal, historical: list[Decimal]) -> Decimal | None:
    if len(historical) < _MIN_HISTORICAL_POINTS:
        return None
    combined = sorted([*historical, current])
    position = combined.index(current)
    return Decimal(position) / Decimal(len(combined) - 1)


def compute_price_band(
    *,
    current_price: Decimal | None,
    annual: tuple[AnnualFinancials, ...],
    historical_prices: tuple[Quote, ...],
) -> PriceBandResult:
    if current_price is None or not annual:
        return PriceBandResult(
            per_band_percentile=None,
            pbr_band_percentile=None,
            note="현재가 또는 재무제표 미확보 — 자동 계산 불가",
        )
    if not historical_prices:
        return PriceBandResult(
            per_band_percentile=None,
            pbr_band_percentile=None,
            note="과거 가격 이력 조회 실패 — 자동 계산 불가",
        )

    latest = annual[-1]

    per_series: list[Decimal] = []
    pbr_series: list[Decimal] = []
    for row in annual:
        price = _year_end_price(historical_prices, row.fiscal_year)
        if price is None:
            continue
        if row.eps is not None and row.eps > 0:
            per_series.append(price / row.eps)
        if (
            row.total_equity is not None
            and row.total_equity > 0
            and row.shares_outstanding is not None
            and row.shares_outstanding > 0
        ):
            pbr_series.append(price / (row.total_equity / row.shares_outstanding))

    per_percentile = None
    if latest.eps is not None and latest.eps > 0:
        current_per = current_price / latest.eps
        per_percentile = _percentile_rank(current_per, per_series)

    pbr_percentile = None
    if (
        latest.total_equity is not None
        and latest.total_equity > 0
        and latest.shares_outstanding is not None
        and latest.shares_outstanding > 0
    ):
        current_pbr = current_price / (latest.total_equity / latest.shares_outstanding)
        pbr_percentile = _percentile_rank(current_pbr, pbr_series)

    note = (
        None
        if per_percentile is not None or pbr_percentile is not None
        else "결산연도별 가격 매칭 표본 부족(최소 2개년 필요) — 자동 계산 불가"
    )
    return PriceBandResult(
        per_band_percentile=per_percentile, pbr_band_percentile=pbr_percentile, note=note
    )
