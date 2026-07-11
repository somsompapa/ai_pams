"""RebalancingEngine: 현재비중 vs 목표비중 → 매매 제안 계산.

규칙:
- 허용밴드 안이면 액션 없음. 밴드를 벗어난 자산군만 '목표비중까지' 되돌린다.
- 현금성 자산군은 매매의 잔여(residual)로 조정되므로 액션을 만들지 않는다.
- 목표에 없는 자산군을 보유 중이면 정책 공백이므로 즉시 실패한다.
- 실행순서: 매도(금액 큰 순) → 매수(금액 큰 순). 매도로 현금을 확보한 뒤 매수한다.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date

from pams.rebalancing.domain.cost_model import CostModel
from pams.rebalancing.domain.proposal import (
    RebalancingAction,
    RebalancingProposal,
    TradeDirection,
)
from pams.shared_kernel.domain import (
    AllocationTarget,
    AssetClass,
    Currency,
    DomainValidationError,
    Money,
    Percentage,
)


class RebalancingEngine:
    def propose(
        self,
        *,
        as_of: date,
        base_currency: Currency,
        current_values: Mapping[AssetClass, Money],
        targets: Sequence[AllocationTarget],
        costs: CostModel,
    ) -> RebalancingProposal:
        self._validate(current_values, targets)
        total = Money.zero(base_currency)
        for value in current_values.values():
            total = total + value
        if not total.is_positive:
            raise DomainValidationError("총자산이 0 이하이면 리밸런싱을 제안할 수 없다")

        actions = []
        for target in targets:
            if target.asset_class.is_cash_like:
                continue
            action = self._action_for(target, current_values, total, costs)
            if action is not None:
                actions.append(action)

        ordered = sorted(
            actions,
            key=lambda a: (
                0 if a.direction is TradeDirection.SELL else 1,
                -a.amount.amount,
            ),
        )
        return RebalancingProposal(as_of=as_of, base_currency=base_currency, actions=tuple(ordered))

    @staticmethod
    def _validate(
        current_values: Mapping[AssetClass, Money], targets: Sequence[AllocationTarget]
    ) -> None:
        duplicated = [
            asset_class
            for asset_class, count in Counter(t.asset_class for t in targets).items()
            if count > 1
        ]
        if duplicated:
            raise DomainValidationError(f"중복 정의된 목표 자산군: {duplicated}")
        target_classes = {t.asset_class for t in targets}
        orphans = [
            asset_class.value
            for asset_class, value in current_values.items()
            if value.is_positive and asset_class not in target_classes
        ]
        if orphans:
            raise DomainValidationError(
                f"목표비중에 없는 자산군을 보유 중이다 (투자헌장에 목표를 추가하라): {orphans}"
            )

    @staticmethod
    def _action_for(
        target: AllocationTarget,
        current_values: Mapping[AssetClass, Money],
        total: Money,
        costs: CostModel,
    ) -> RebalancingAction | None:
        current_value = current_values.get(target.asset_class, Money.zero(total.currency))
        current_weight = Percentage.from_ratio(current_value.amount / total.amount)
        if target.contains(current_weight):
            return None

        target_value = target.target.of(total)
        difference = current_value - target_value
        direction = TradeDirection.SELL if difference.is_positive else TradeDirection.BUY
        amount = difference if difference.is_positive else -difference

        rates = costs.rates_for(target.asset_class)
        fee = rates.fee_rate.of(amount)
        tax = (
            rates.sell_tax_rate.of(amount)
            if direction is TradeDirection.SELL
            else Money.zero(amount.currency)
        )
        return RebalancingAction(
            asset_class=target.asset_class,
            direction=direction,
            amount=amount,
            estimated_fee=fee,
            estimated_tax=tax,
            current_weight=current_weight,
            target_weight=target.target,
        )
