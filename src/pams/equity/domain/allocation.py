"""주식 슬리브 내 종목별 배분(Tier 2) 도메인.

IPS(Tier 1)가 '주식 = 자산 대비 N%'를 정한 뒤, 그 주식 슬리브 안에서
종목별 목표비중과 매수/매도 밴드를 정한다. 현재비중(슬리브 대비)이 밴드를
벗어나면 매수/매도 신호를 낸다. 판단은 이 규칙이 하고, 실제 매매는 사용자가 한다.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum, unique

from pams.shared_kernel.domain import (
    Currency,
    DomainValidationError,
    Money,
    Percentage,
)

_ZERO = Percentage.zero()
_FULL = Percentage.from_percent(100)


@unique
class StockSignal(StrEnum):
    BUY = "buy"  # 현재비중이 매수 트리거 이하
    SELL = "sell"  # 현재비중이 매도 트리거 이상
    HOLD = "hold"  # 밴드 안 (또는 목표 미설정)


@dataclass(frozen=True, slots=True)
class StockTarget:
    """종목별 목표비중(주식 슬리브 대비)과 매수/매도 밴드.

    매수 트리거 = target - buy_band (이하로 내려가면 매수)
    매도 트리거 = target + sell_band (이상으로 올라가면 매도)
    """

    asset_id: str
    target: Percentage
    buy_band: Percentage
    sell_band: Percentage

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise DomainValidationError("asset_id는 비어 있을 수 없다")
        if not (_ZERO <= self.target <= _FULL):
            raise DomainValidationError(
                f"{self.asset_id} 목표비중은 0~100%여야 한다: {self.target.as_percent}%"
            )
        if self.buy_band < _ZERO or self.sell_band < _ZERO:
            raise DomainValidationError(f"{self.asset_id} 밴드는 음수가 될 수 없다")

    @property
    def buy_trigger(self) -> Percentage:
        low = self.target - self.buy_band
        return low if low > _ZERO else _ZERO

    @property
    def sell_trigger(self) -> Percentage:
        high = self.target + self.sell_band
        return high if high < _FULL else _FULL

    def signal(self, current_weight: Percentage) -> StockSignal:
        if current_weight <= self.buy_trigger:
            return StockSignal.BUY
        if current_weight >= self.sell_trigger:
            return StockSignal.SELL
        return StockSignal.HOLD


@dataclass(frozen=True, slots=True)
class StockTargetPlan:
    targets: tuple[StockTarget, ...]

    def __post_init__(self) -> None:
        duplicated = [
            asset_id
            for asset_id, count in Counter(t.asset_id for t in self.targets).items()
            if count > 1
        ]
        if duplicated:
            raise DomainValidationError(f"중복된 종목 목표: {duplicated}")

    def target_for(self, asset_id: str) -> StockTarget | None:
        for target in self.targets:
            if target.asset_id == asset_id:
                return target
        return None


@dataclass(frozen=True, slots=True)
class StockAllocationRow:
    asset_id: str
    current_weight: Percentage  # 주식 슬리브 대비
    target: StockTarget | None
    signal: StockSignal
    adjust_amount: Money  # 목표까지 필요한 금액 (+매수 / -매도)


@dataclass(frozen=True, slots=True)
class StockAllocationReport:
    sleeve_value: Money  # 주식 슬리브 총액
    rows: tuple[StockAllocationRow, ...]


@dataclass(frozen=True, slots=True)
class EvaluateStockAllocation:
    """주식 슬리브 평가금액과 종목 목표를 받아 종목별 신호를 계산한다."""

    plan: StockTargetPlan

    def execute(
        self, *, holdings: Mapping[str, Money], base_currency: Currency
    ) -> StockAllocationReport:
        sleeve = Money.zero(base_currency)
        for value in holdings.values():
            sleeve = sleeve + value
        if not sleeve.is_positive:
            return StockAllocationReport(sleeve_value=Money.zero(base_currency), rows=())

        rows = []
        for asset_id, value in holdings.items():
            weight = Percentage.from_ratio(value.amount / sleeve.amount)
            target = self.plan.target_for(asset_id)
            if target is None:
                signal = StockSignal.HOLD
                adjust = Money.zero(base_currency)
            else:
                signal = target.signal(weight)
                desired = Money(target.target.ratio * sleeve.amount, base_currency)
                adjust = desired - value
            rows.append(
                StockAllocationRow(
                    asset_id=asset_id,
                    current_weight=weight,
                    target=target,
                    signal=signal,
                    adjust_amount=adjust,
                )
            )
        return StockAllocationReport(sleeve_value=sleeve, rows=tuple(rows))
