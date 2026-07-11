"""유스케이스: 평가액 시계열로 성과 보고서를 만든다.

평가액/현금흐름 이력 적재는 이후 저장소 포트로 연결되며, 다른 컨텍스트
(reporting, ai_analysis)는 이 유스케이스를 통해서만 performance와 통신한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pams.performance.domain import PerformanceEngine, PerformanceHistory, PerformanceReport


@dataclass(frozen=True, slots=True)
class ComputePerformanceReport:
    engine: PerformanceEngine = field(default_factory=PerformanceEngine)

    def execute(
        self,
        *,
        history: PerformanceHistory,
        benchmark: PerformanceHistory | None = None,
        realized_pnls: Sequence[Decimal] | None = None,
        compliance_history: Sequence[tuple[date, bool]] | None = None,
    ) -> PerformanceReport:
        return self.engine.analyze(
            history=history,
            benchmark=benchmark,
            realized_pnls=realized_pnls,
            compliance_history=compliance_history,
        )
