"""규칙 평가의 입력(EvaluationContext)과 출력(ComplianceReport)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pams.ips.domain.rule import Rule, Severity
from pams.shared_kernel.domain import DomainError, DomainValidationError


class MissingMetricError(DomainError):
    """규칙이 참조한 지표가 컨텍스트에 없다.

    지표 누락을 조용히 건너뛰면 규칙이 실행되지 않은 채 '준수'로 오판될 수
    있으므로, 엄격 실행 원칙에 따라 즉시 실패시킨다.
    """


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """평가 시점의 지표 스냅샷. 지표는 포트폴리오/리스크 엔진이 계산해 채운다.

    지표 예: equity_weight(주식비중), cash_weight(현금성 비중), vix,
    max_position_weight(최대 단일종목 비중), drawdown(현재 낙폭) 등.
    """

    as_of: date
    metrics: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        for name, value in self.metrics.items():
            if not isinstance(value, Decimal):
                raise DomainValidationError(
                    f"지표 '{name}'는 Decimal이어야 한다 (float 금지): {value!r}"
                )

    def metric(self, name: str) -> Decimal:
        try:
            return self.metrics[name]
        except KeyError:
            raise MissingMetricError(
                f"지표 '{name}'가 평가 컨텍스트에 없다 (보유 지표: {sorted(self.metrics)})"
            ) from None


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    """단일 규칙의 판정 결과."""

    rule: Rule
    triggered: bool
    observed: Mapping[str, Decimal]  # 조건이 참조한 지표들의 관측값

    @property
    def message(self) -> str:
        status = "TRIGGERED" if self.triggered else "OK"
        observations = ", ".join(f"{name}={value}" for name, value in self.observed.items())
        return (
            f"[{status}][{self.rule.severity}] {self.rule.rule_id}: "
            f"{self.rule.description} ({observations})"
        )


@dataclass(frozen=True, slots=True)
class ComplianceReport:
    """전체 규칙 평가 결과. 리밸런싱/알림/보고서가 소비하는 표준 출력."""

    as_of: date
    evaluations: tuple[RuleEvaluation, ...]

    def _triggered_with(self, severity: Severity) -> tuple[RuleEvaluation, ...]:
        return tuple(e for e in self.evaluations if e.triggered and e.rule.severity is severity)

    @property
    def violations(self) -> tuple[RuleEvaluation, ...]:
        return self._triggered_with(Severity.VIOLATION)

    @property
    def warnings(self) -> tuple[RuleEvaluation, ...]:
        return self._triggered_with(Severity.WARNING)

    @property
    def is_compliant(self) -> bool:
        """위반(VIOLATION)이 하나도 발동하지 않으면 준수 상태다."""
        return not self.violations
