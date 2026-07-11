"""유스케이스: 현재 자산배분과 투자헌장 목표로 리밸런싱 제안서를 만든다.

현재 자산배분(current_values)은 portfolio 컨텍스트의 스냅샷에서,
목표(targets)는 ips 컨텍스트의 투자헌장에서 온다. 두 컨텍스트와의 연결은
interfaces 계층이 담당하고, 이 유스케이스는 shared_kernel 타입만 받는다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from pams.rebalancing.domain import CostModel, RebalancingEngine, RebalancingProposal
from pams.shared_kernel.domain import AllocationTarget, AssetClass, Currency, Money


@dataclass(frozen=True, slots=True)
class ProposeRebalancing:
    costs: CostModel
    engine: RebalancingEngine = field(default_factory=RebalancingEngine)

    def execute(
        self,
        *,
        as_of: date,
        base_currency: Currency,
        current_values: Mapping[AssetClass, Money],
        targets: Sequence[AllocationTarget],
        cost_bases: Mapping[AssetClass, Money] | None = None,
    ) -> RebalancingProposal:
        return self.engine.propose(
            as_of=as_of,
            base_currency=base_currency,
            current_values=current_values,
            targets=targets,
            costs=self.costs,
            cost_bases=cost_bases,
        )
