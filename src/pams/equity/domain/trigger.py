"""종목별 절대가격 매수/매도 트리거 도메인.

"삼성전자 7만원 이하면 매수, 9만원 이상이면 매도" 같은, 사용자가 직접 정한
가격선. 현재가가 선을 건드리면 매수/매도 신호를 낸다. 판단은 이 규칙이 하고
실제 매매는 사용자가 한다(제안까지만).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from pams.equity.domain.allocation import StockSignal
from pams.shared_kernel.domain import DomainValidationError, Money


@dataclass(frozen=True, slots=True)
class PriceTrigger:
    """종목 하나의 매수/매도 가격선. 자산의 거래통화 기준. 둘 중 하나는 필수."""

    asset_id: str
    buy_at: Money | None
    sell_at: Money | None

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise DomainValidationError("asset_id는 비어 있을 수 없다")
        if self.buy_at is None and self.sell_at is None:
            raise DomainValidationError(
                f"{self.asset_id}: buy_at/sell_at 중 최소 하나는 있어야 한다"
            )
        if self.buy_at is not None and not self.buy_at.is_positive:
            raise DomainValidationError(f"{self.asset_id}: 매수가는 양수여야 한다")
        if self.sell_at is not None and not self.sell_at.is_positive:
            raise DomainValidationError(f"{self.asset_id}: 매도가는 양수여야 한다")
        if self.buy_at is not None and self.sell_at is not None:
            if self.buy_at.currency is not self.sell_at.currency:
                raise DomainValidationError(f"{self.asset_id}: 매수/매도가 통화가 다르다")
            if self.buy_at.amount >= self.sell_at.amount:
                raise DomainValidationError(f"{self.asset_id}: 매수가는 매도가보다 낮아야 한다")

    @property
    def currency(self) -> object:
        bound = self.buy_at if self.buy_at is not None else self.sell_at
        assert bound is not None
        return bound.currency

    def signal(self, current_price: Money) -> StockSignal:
        if self.buy_at is not None and current_price.currency is not self.buy_at.currency:
            raise DomainValidationError(f"{self.asset_id}: 현재가 통화가 트리거와 다르다")
        if self.sell_at is not None and current_price.currency is not self.sell_at.currency:
            raise DomainValidationError(f"{self.asset_id}: 현재가 통화가 트리거와 다르다")
        if self.buy_at is not None and current_price.amount <= self.buy_at.amount:
            return StockSignal.BUY
        if self.sell_at is not None and current_price.amount >= self.sell_at.amount:
            return StockSignal.SELL
        return StockSignal.HOLD


@dataclass(frozen=True, slots=True)
class PriceTriggerPlan:
    triggers: tuple[PriceTrigger, ...]

    def __post_init__(self) -> None:
        duplicated = [
            asset_id
            for asset_id, count in Counter(t.asset_id for t in self.triggers).items()
            if count > 1
        ]
        if duplicated:
            raise DomainValidationError(f"중복된 가격 트리거: {duplicated}")

    def trigger_for(self, asset_id: str) -> PriceTrigger | None:
        for trigger in self.triggers:
            if trigger.asset_id == asset_id:
                return trigger
        return None


@dataclass(frozen=True, slots=True)
class PriceTriggerRow:
    asset_id: str
    current_price: Money
    trigger: PriceTrigger
    signal: StockSignal


@dataclass(frozen=True, slots=True)
class PriceTriggerReport:
    rows: tuple[PriceTriggerRow, ...]

    @property
    def firing(self) -> tuple[PriceTriggerRow, ...]:
        """실제로 매수/매도 신호가 켜진 행만."""
        return tuple(r for r in self.rows if r.signal is not StockSignal.HOLD)


@dataclass(frozen=True, slots=True)
class EvaluatePriceTriggers:
    plan: PriceTriggerPlan

    def execute(self, *, current_prices: Mapping[str, Money]) -> PriceTriggerReport:
        rows = []
        for trigger in self.plan.triggers:
            price = current_prices.get(trigger.asset_id)
            if price is None:
                continue
            rows.append(
                PriceTriggerRow(
                    asset_id=trigger.asset_id,
                    current_price=price,
                    trigger=trigger,
                    signal=trigger.signal(price),
                )
            )
        return PriceTriggerReport(rows=tuple(rows))
