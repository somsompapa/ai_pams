"""유스케이스: 현재 지표에 투자헌장 규칙을 적용해 준수 보고서를 만든다.

다른 컨텍스트(리밸런싱, 알림, 보고서)는 이 유스케이스를 통해서만
ips 컨텍스트와 통신한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pams.ips.domain import ComplianceReport, EvaluationContext, PolicyRepository, RuleEngine


@dataclass(frozen=True, slots=True)
class EvaluateCompliance:
    repository: PolicyRepository
    engine: RuleEngine = field(default_factory=RuleEngine)

    def execute(self, context: EvaluationContext) -> ComplianceReport:
        policy = self.repository.load()
        return self.engine.evaluate(policy.rules, context)
