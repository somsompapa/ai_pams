"""RuleEngine: 판단의 유일한 주체.

AI는 이 엔진의 출력(ComplianceReport)을 해설할 뿐, 판정에 관여하지 않는다.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from pams.ips.domain.evaluation import ComplianceReport, EvaluationContext, RuleEvaluation
from pams.ips.domain.rule import Rule
from pams.shared_kernel.domain import DomainValidationError


class RuleEngine:
    def evaluate(self, rules: Sequence[Rule], context: EvaluationContext) -> ComplianceReport:
        self._require_unique_ids(rules)
        evaluations = tuple(self._evaluate_rule(rule, context) for rule in rules)
        return ComplianceReport(as_of=context.as_of, evaluations=evaluations)

    @staticmethod
    def _require_unique_ids(rules: Sequence[Rule]) -> None:
        duplicates = [
            rule_id for rule_id, count in Counter(r.rule_id for r in rules).items() if count > 1
        ]
        if duplicates:
            raise DomainValidationError(f"중복된 rule_id: {duplicates}")

    @staticmethod
    def _evaluate_rule(rule: Rule, context: EvaluationContext) -> RuleEvaluation:
        observed = {c.metric: context.metric(c.metric) for c in rule.conditions}
        triggered = all(c.is_met(observed[c.metric]) for c in rule.conditions)
        return RuleEvaluation(rule=rule, triggered=triggered, observed=observed)
