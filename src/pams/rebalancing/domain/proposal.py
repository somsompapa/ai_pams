"""리밸런싱 제안 모델.

시스템은 제안까지만 만들고, 실제 매매 실행은 사용자가 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum, unique

from pams.shared_kernel.domain import (
    AssetClass,
    Currency,
    DomainValidationError,
    Money,
    Percentage,
)


@unique
class TradeDirection(StrEnum):
    SELL = "sell"
    BUY = "buy"


@dataclass(frozen=True, slots=True)
class RebalancingAction:
    """단일 자산군에 대한 매매 제안. 금액은 기준통화."""

    asset_class: AssetClass
    direction: TradeDirection
    amount: Money
    estimated_fee: Money
    estimated_tax: Money
    current_weight: Percentage
    target_weight: Percentage

    def __post_init__(self) -> None:
        if not self.amount.is_positive:
            raise DomainValidationError(f"제안 금액은 양수여야 한다: {self.amount.amount}")

    @property
    def deviation(self) -> Percentage:
        """현재비중 - 목표비중 (양수 = 과대보유)."""
        return self.current_weight - self.target_weight

    @property
    def estimated_cost(self) -> Money:
        return self.estimated_fee + self.estimated_tax


@dataclass(frozen=True, slots=True)
class RebalancingProposal:
    """리밸런싱 제안서. actions는 실행순서(매도 먼저, 금액 큰 순)로 정렬되어 있다."""

    as_of: date
    base_currency: Currency
    actions: tuple[RebalancingAction, ...]

    @property
    def is_rebalancing_needed(self) -> bool:
        return bool(self.actions)

    def _total(self, direction: TradeDirection) -> Money:
        total = Money.zero(self.base_currency)
        for action in self.actions:
            if action.direction is direction:
                total = total + action.amount
        return total

    @property
    def total_sell_amount(self) -> Money:
        return self._total(TradeDirection.SELL)

    @property
    def total_buy_amount(self) -> Money:
        return self._total(TradeDirection.BUY)

    @property
    def total_estimated_cost(self) -> Money:
        total = Money.zero(self.base_currency)
        for action in self.actions:
            total = total + action.estimated_cost
        return total
