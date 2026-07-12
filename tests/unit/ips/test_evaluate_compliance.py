"""EvaluateCompliance 유스케이스 테스트.

유스케이스는 PolicyRepository 포트에만 의존한다 - 인메모리 페이크로 검증한다.
"""

from datetime import date
from decimal import Decimal

from pams.ips.application import EvaluateCompliance
from pams.ips.domain import (
    AllocationTarget,
    ComparisonOperator,
    Condition,
    EvaluationContext,
    PolicyRepository,
    PolicyStatement,
    Rule,
    RuleAction,
    Severity,
)
from pams.shared_kernel.domain import AssetClass, Currency, Percentage


def make_policy() -> PolicyStatement:
    return PolicyStatement(
        name="테스트 헌장",
        base_currency=Currency.KRW,
        targets=(
            AllocationTarget(
                asset_class=AssetClass.US_STOCK,
                target=Percentage.from_percent(60),
                band=Percentage.from_percent(5),
            ),
            AllocationTarget(
                asset_class=AssetClass.CASH,
                target=Percentage.from_percent(40),
                band=Percentage.from_percent(5),
            ),
        ),
        rules=(
            Rule(
                rule_id="min-cash",
                description="현금성 자산 비중은 10% 이상이어야 한다",
                severity=Severity.VIOLATION,
                conditions=(Condition("cash_weight", ComparisonOperator.LT, Decimal("0.10")),),
                action=RuleAction(action_type="block_new_buys"),
            ),
        ),
    )


class InMemoryPolicyRepository:
    def __init__(self, policy: PolicyStatement) -> None:
        self._policy = policy

    def load(self) -> PolicyStatement:
        return self._policy


class TestEvaluateCompliance:
    def test_repository_satisfies_port(self) -> None:
        assert isinstance(InMemoryPolicyRepository(make_policy()), PolicyRepository)

    def test_violation_detected(self) -> None:
        use_case = EvaluateCompliance(repository=InMemoryPolicyRepository(make_policy()))
        report = use_case.execute(
            EvaluationContext(as_of=date(2026, 7, 10), metrics={"cash_weight": Decimal("0.05")})
        )
        assert not report.is_compliant
        assert report.violations[0].rule.action.action_type == "block_new_buys"

    def test_compliant_portfolio(self) -> None:
        use_case = EvaluateCompliance(repository=InMemoryPolicyRepository(make_policy()))
        report = use_case.execute(
            EvaluationContext(as_of=date(2026, 7, 10), metrics={"cash_weight": Decimal("0.40")})
        )
        assert report.is_compliant
