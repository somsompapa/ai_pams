"""유스케이스: 특정 일자에 매수 예정인 DCA 주문 목록을 만든다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pams.dca.domain import DcaOrder, DcaPlan


@dataclass(frozen=True, slots=True)
class PlanDcaOrders:
    plan: DcaPlan

    def execute(self, *, as_of: date) -> tuple[DcaOrder, ...]:
        return self.plan.due_on(as_of)
