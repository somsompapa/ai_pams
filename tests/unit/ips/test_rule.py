"""Rule/Condition 도메인 모델 테스트."""

from decimal import Decimal

import pytest

from pams.ips.domain import ComparisonOperator, Condition, Rule, RuleAction, Severity
from pams.shared_kernel.domain import DomainValidationError


def condition(**overrides: object) -> Condition:
    defaults: dict[str, object] = {
        "metric": "equity_weight",
        "operator": ComparisonOperator.GT,
        "value": Decimal("0.70"),
    }
    defaults.update(overrides)
    return Condition(**defaults)  # type: ignore[arg-type]


def rule(**overrides: object) -> Rule:
    defaults: dict[str, object] = {
        "rule_id": "max-equity-weight",
        "description": "주식비중은 70%를 초과할 수 없다",
        "severity": Severity.VIOLATION,
        "conditions": (condition(),),
        "action": RuleAction(action_type="reduce_equity", params={"target": "0.70"}),
    }
    defaults.update(overrides)
    return Rule(**defaults)  # type: ignore[arg-type]


class TestConditionOperators:
    @pytest.mark.parametrize(
        ("operator", "observed", "expected"),
        [
            (ComparisonOperator.GT, "0.71", True),
            (ComparisonOperator.GT, "0.70", False),
            (ComparisonOperator.GTE, "0.70", True),
            (ComparisonOperator.LT, "0.69", True),
            (ComparisonOperator.LT, "0.70", False),
            (ComparisonOperator.LTE, "0.70", True),
            (ComparisonOperator.EQ, "0.70", True),
            (ComparisonOperator.EQ, "0.71", False),
            (ComparisonOperator.NEQ, "0.71", True),
        ],
    )
    def test_compare(self, operator: ComparisonOperator, observed: str, expected: bool) -> None:
        cond = condition(operator=operator)
        assert cond.is_met(Decimal(observed)) is expected


class TestConditionValidation:
    def test_empty_metric_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            condition(metric="  ")

    def test_float_value_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            condition(value=0.7)


class TestRuleValidation:
    def test_valid_rule(self) -> None:
        r = rule()
        assert r.rule_id == "max-equity-weight"
        assert r.action.params["target"] == "0.70"

    def test_empty_rule_id_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            rule(rule_id="")

    def test_rule_without_conditions_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            rule(conditions=())

    def test_empty_action_type_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            RuleAction(action_type=" ")
