"""유동성 스크리닝(portfolio_rules.md P-5, v1.6.1 신규) — 매수 전 참고용 판단 보조.

최근 20영업일 평균 거래대금이 1차 매수 예정 금액의 최소 20배(초기값, 계좌 규모·
시장별 재검토 대상)는 돼야 한 거래일에 과도한 비중을 차지하지 않고 시장충격 없이
분할매수가 가능하다고 본다. 기준 미달이 매수 금지를 뜻하지 않는다 — 분할 횟수를
늘리거나 목표 수량을 줄이는 등 사용자 판단을 보조할 뿐이다(자동 차단 아님).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pams.market_data.domain import DailyBar

DEFAULT_MULTIPLE = Decimal(20)


@dataclass(frozen=True, slots=True)
class LiquidityCheck:
    average_daily_trading_value: Decimal | None
    required_minimum: Decimal | None
    sufficient: bool | None
    days_observed: int
    note: str | None


def evaluate_liquidity(
    *,
    planned_first_tranche_amount: Decimal,
    daily_bars: tuple[DailyBar, ...],
    multiple: Decimal = DEFAULT_MULTIPLE,
) -> LiquidityCheck:
    if not daily_bars:
        return LiquidityCheck(
            average_daily_trading_value=None,
            required_minimum=None,
            sufficient=None,
            days_observed=0,
            note="거래대금 이력 조회 실패 — 자동 판정 불가, 직접 확인 필요",
        )
    values = [bar.close * bar.volume for bar in daily_bars]
    average = sum(values, Decimal(0)) / len(values)
    required = planned_first_tranche_amount * multiple
    return LiquidityCheck(
        average_daily_trading_value=average,
        required_minimum=required,
        sufficient=average >= required,
        days_observed=len(daily_bars),
        note=None,
    )
