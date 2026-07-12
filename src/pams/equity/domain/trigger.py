"""종목별 절대가격 매수/익절/손절 트리거 도메인.

한 종목에 세 가지 가격선을 둘 수 있다(모두 선택, 최소 하나 필수):
- 매수선(buy_at):        이하로 내려가면 매수
- 익절선(take_profit_at): 이상으로 올라가면 매도(이익 실현)
- 손절선(stop_loss_at):   이하로 내려가면 매도(손실 제한)

판단은 이 규칙이 하고 실제 매매는 사용자가 한다(제안까지만).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from pams.equity.domain.allocation import StockSignal
from pams.shared_kernel.domain import DomainValidationError, Money


@dataclass(frozen=True, slots=True)
class TriggerHit:
    """현재가가 어떤 선을 건드려 발생한 신호. label: 매수/익절/손절."""

    signal: StockSignal
    label: str
    bound: Money


@dataclass(frozen=True, slots=True)
class PriceTrigger:
    asset_id: str
    buy_at: Money | None = None
    take_profit_at: Money | None = None
    stop_loss_at: Money | None = None

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise DomainValidationError("asset_id는 비어 있을 수 없다")
        lines = [self.buy_at, self.take_profit_at, self.stop_loss_at]
        if all(line is None for line in lines):
            raise DomainValidationError(
                f"{self.asset_id}: 매수선/익절선/손절선 중 최소 하나는 있어야 한다"
            )
        currencies = {line.currency for line in lines if line is not None}
        if len(currencies) > 1:
            raise DomainValidationError(f"{self.asset_id}: 가격선들의 통화가 서로 다르다")
        for label, line in (
            ("매수선", self.buy_at),
            ("익절선", self.take_profit_at),
            ("손절선", self.stop_loss_at),
        ):
            if line is not None and not line.is_positive:
                raise DomainValidationError(f"{self.asset_id}: {label}은 양수여야 한다")

        # 논리적 순서: 손절선 < 매수선 < 익절선
        if self.stop_loss_at is not None and self.take_profit_at is not None:
            if self.stop_loss_at.amount >= self.take_profit_at.amount:
                raise DomainValidationError(f"{self.asset_id}: 손절선은 익절선보다 낮아야 한다")
        if self.buy_at is not None and self.take_profit_at is not None:
            if self.buy_at.amount >= self.take_profit_at.amount:
                raise DomainValidationError(f"{self.asset_id}: 매수선은 익절선보다 낮아야 한다")
        if self.stop_loss_at is not None and self.buy_at is not None:
            if self.stop_loss_at.amount >= self.buy_at.amount:
                raise DomainValidationError(f"{self.asset_id}: 손절선은 매수선보다 낮아야 한다")

    @property
    def currency(self) -> object:
        for line in (self.buy_at, self.take_profit_at, self.stop_loss_at):
            if line is not None:
                return line.currency
        raise AssertionError("가격선이 하나도 없다")  # __post_init__에서 차단됨

    def evaluate(self, current_price: Money) -> TriggerHit | None:
        """현재가로 신호를 계산한다. 유지(HOLD)면 None.

        우선순위: 손절 → 익절 → 매수 (자본 보호가 최우선).
        """
        for line in (self.stop_loss_at, self.take_profit_at, self.buy_at):
            if line is not None and current_price.currency is not line.currency:
                raise DomainValidationError(f"{self.asset_id}: 현재가 통화가 트리거와 다르다")
        if self.stop_loss_at is not None and current_price.amount <= self.stop_loss_at.amount:
            return TriggerHit(StockSignal.SELL, "손절", self.stop_loss_at)
        if self.take_profit_at is not None and current_price.amount >= self.take_profit_at.amount:
            return TriggerHit(StockSignal.SELL, "익절", self.take_profit_at)
        if self.buy_at is not None and current_price.amount <= self.buy_at.amount:
            return TriggerHit(StockSignal.BUY, "매수", self.buy_at)
        return None

    def signal(self, current_price: Money) -> StockSignal:
        hit = self.evaluate(current_price)
        return hit.signal if hit is not None else StockSignal.HOLD


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
    label: str  # 매수/익절/손절/유지


@dataclass(frozen=True, slots=True)
class PriceTriggerReport:
    rows: tuple[PriceTriggerRow, ...]

    @property
    def firing(self) -> tuple[PriceTriggerRow, ...]:
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
            hit = trigger.evaluate(price)
            rows.append(
                PriceTriggerRow(
                    asset_id=trigger.asset_id,
                    current_price=price,
                    trigger=trigger,
                    signal=hit.signal if hit is not None else StockSignal.HOLD,
                    label=hit.label if hit is not None else "유지",
                )
            )
        return PriceTriggerReport(rows=tuple(rows))
