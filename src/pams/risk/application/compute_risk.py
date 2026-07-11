"""유스케이스: 가치 시계열로 위험지표 보고서를 만든다.

가치 시계열의 적재(일별 스냅샷 저장)는 이후 Phase에서 저장소 포트로 연결되고,
다른 컨텍스트(reporting, ips)는 이 유스케이스를 통해서만 risk와 통신한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from pams.risk.domain import RiskEngine, RiskParameters, RiskReport, ValueSeries


@dataclass(frozen=True, slots=True)
class ComputeRiskReport:
    engine: RiskEngine = field(default_factory=RiskEngine)

    def execute(
        self,
        *,
        portfolio_values: ValueSeries,
        parameters: RiskParameters,
        benchmark_values: ValueSeries | None = None,
        position_weights: Mapping[str, Decimal] | None = None,
    ) -> RiskReport:
        return self.engine.analyze(
            portfolio_values=portfolio_values,
            parameters=parameters,
            benchmark_values=benchmark_values,
            position_weights=position_weights,
        )
