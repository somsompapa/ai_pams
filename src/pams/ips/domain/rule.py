"""Rule: IF 조건 THEN 액션.

규칙은 YAML(config/rules/)에서 로드되는 데이터이며, 코드에 하드코딩하지 않는다.
액션은 선언적 명령(문자열 + 파라미터)일 뿐이고, 해석은 다운스트림 엔진
(리밸런싱, 알림)이 담당한다 - Rule Engine 자체는 판정만 한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum, unique

from pams.shared_kernel.domain import DomainValidationError


@unique
class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"  # 주의 - 준수 여부는 바꾸지 않음 (예: 긴급 리밸런싱 후보)
    VIOLATION = "violation"  # 위반 - 포트폴리오가 IPS를 벗어난 상태


@unique
class ComparisonOperator(StrEnum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    NEQ = "neq"

    def compare(self, left: Decimal, right: Decimal) -> bool:
        match self:
            case ComparisonOperator.GT:
                return left > right
            case ComparisonOperator.GTE:
                return left >= right
            case ComparisonOperator.LT:
                return left < right
            case ComparisonOperator.LTE:
                return left <= right
            case ComparisonOperator.EQ:
                return left == right
            case ComparisonOperator.NEQ:
                return left != right


@dataclass(frozen=True, slots=True)
class Condition:
    """지표(metric)를 임계값과 비교하는 단일 조건."""

    metric: str
    operator: ComparisonOperator
    value: Decimal

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise DomainValidationError("condition.metric은 비어 있을 수 없다")
        if not isinstance(self.value, Decimal):
            raise DomainValidationError(
                f"condition.value는 Decimal이어야 한다 (float 금지): {self.value!r}"
            )

    def is_met(self, observed: Decimal) -> bool:
        return self.operator.compare(observed, self.value)


@dataclass(frozen=True, slots=True)
class RuleAction:
    """규칙 발동 시의 선언적 명령. 예: block_new_buys, reduce_equity."""

    action_type: str
    params: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.action_type.strip():
            raise DomainValidationError("action_type은 비어 있을 수 없다")


@dataclass(frozen=True, slots=True)
class Rule:
    """조건 전부(AND)가 충족되면 발동하는 규칙."""

    rule_id: str
    description: str
    severity: Severity
    conditions: tuple[Condition, ...]
    action: RuleAction

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise DomainValidationError("rule_id는 비어 있을 수 없다")
        if not self.conditions:
            raise DomainValidationError(f"규칙 '{self.rule_id}'에 조건이 하나도 없다")
