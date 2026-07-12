"""RuleEngine 테스트.

계약:
- 규칙의 모든 조건이 충족되면 triggered (AND 의미론)
- 참조 지표가 없으면 조용히 건너뛰지 않고 MissingMetricError (엄격 실행 원칙)
- VIOLATION 규칙이 하나라도 triggered면 보고서는 non-compliant
"""

from datetime import date
from decimal import Decimal

import pytest

from pams.ips.domain import (
    ComparisonOperator,
    Condition,
    EvaluationContext,
    MissingMetricError,
    Rule,
    RuleAction,
    RuleEngine,
    Severity,
)
from pams.shared_kernel.domain import DomainValidationError

AS_OF = date(2026, 7, 10)


def make_rule(
    rule_id: str,
    metric: str,
    operator: ComparisonOperator,
    value: str,
    severity: Severity = Severity.VIOLATION,
    conditions: tuple[Condition, ...] | None = None,
) -> Rule:
    return Rule(
        rule_id=rule_id,
        description=f"{metric} 규칙",
        severity=severity,
        conditions=conditions or (Condition(metric, operator, Decimal(value)),),
        action=RuleAction(action_type="noop"),
    )


def context(**metrics: str) -> EvaluationContext:
    return EvaluationContext(
        as_of=AS_OF, metrics={name: Decimal(value) for name, value in metrics.items()}
    )


class TestEvaluation:
    def test_triggered_rule(self) -> None:
        rule = make_rule("max-equity", "equity_weight", ComparisonOperator.GT, "0.70")
        report = RuleEngine().evaluate([rule], context(equity_weight="0.72"))
        assert len(report.evaluations) == 1
        assert report.evaluations[0].triggered
        assert report.evaluations[0].observed["equity_weight"] == Decimal("0.72")

    def test_not_triggered_rule(self) -> None:
        rule = make_rule("max-equity", "equity_weight", ComparisonOperator.GT, "0.70")
        report = RuleEngine().evaluate([rule], context(equity_weight="0.65"))
        assert not report.evaluations[0].triggered
        assert report.is_compliant

    def test_and_semantics_requires_all_conditions(self) -> None:
        """VIX > 35 이고 주식비중 > 50% 일 때만 긴급 리밸런싱 후보."""
        rule = make_rule(
            "vix-emergency",
            "vix",
            ComparisonOperator.GT,
            "35",
            severity=Severity.WARNING,
            conditions=(
                Condition("vix", ComparisonOperator.GT, Decimal("35")),
                Condition("equity_weight", ComparisonOperator.GT, Decimal("0.50")),
            ),
        )
        engine = RuleEngine()
        both = engine.evaluate([rule], context(vix="40", equity_weight="0.60"))
        only_vix = engine.evaluate([rule], context(vix="40", equity_weight="0.30"))
        assert both.evaluations[0].triggered
        assert not only_vix.evaluations[0].triggered

    def test_missing_metric_raises(self) -> None:
        rule = make_rule("max-equity", "equity_weight", ComparisonOperator.GT, "0.70")
        with pytest.raises(MissingMetricError):
            RuleEngine().evaluate([rule], context(cash_weight="0.10"))

    def test_duplicate_rule_ids_rejected(self) -> None:
        rules = [
            make_rule("dup", "equity_weight", ComparisonOperator.GT, "0.70"),
            make_rule("dup", "cash_weight", ComparisonOperator.LT, "0.10"),
        ]
        with pytest.raises(DomainValidationError):
            RuleEngine().evaluate(rules, context(equity_weight="0.5", cash_weight="0.2"))


class TestComplianceReport:
    def test_violation_makes_report_non_compliant(self) -> None:
        rules = [
            make_rule("max-equity", "equity_weight", ComparisonOperator.GT, "0.70"),
            make_rule("vix-watch", "vix", ComparisonOperator.GT, "35", severity=Severity.WARNING),
        ]
        report = RuleEngine().evaluate(rules, context(equity_weight="0.75", vix="20"))
        assert not report.is_compliant
        assert [e.rule.rule_id for e in report.violations] == ["max-equity"]
        assert report.warnings == ()

    def test_triggered_warning_keeps_report_compliant(self) -> None:
        """경고는 준수 여부를 바꾸지 않는다 - 위반(VIOLATION)만 non-compliant."""
        rules = [
            make_rule("max-equity", "equity_weight", ComparisonOperator.GT, "0.70"),
            make_rule("vix-watch", "vix", ComparisonOperator.GT, "35", severity=Severity.WARNING),
        ]
        report = RuleEngine().evaluate(rules, context(equity_weight="0.60", vix="40"))
        assert report.is_compliant
        assert [e.rule.rule_id for e in report.warnings] == ["vix-watch"]

    def test_message_contains_rule_id(self) -> None:
        rule = make_rule("max-equity", "equity_weight", ComparisonOperator.GT, "0.70")
        report = RuleEngine().evaluate([rule], context(equity_weight="0.75"))
        assert "max-equity" in report.evaluations[0].message


class TestEvaluationContext:
    def test_float_metric_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            EvaluationContext(as_of=AS_OF, metrics={"vix": 35.5})  # type: ignore[dict-item]
