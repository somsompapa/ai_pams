"""PolicyStatement: 투자헌장(IPS) - 시스템의 최상위 규칙 문서.

AllocationTarget은 리밸런싱과 공유하는 어휘라 shared_kernel에 있다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from pams.ips.domain.rule import Rule
from pams.shared_kernel.domain import (
    AllocationTarget,
    AssetClass,
    Currency,
    DomainValidationError,
    Percentage,
)


@dataclass(frozen=True, slots=True)
class PolicyStatement:
    name: str
    base_currency: Currency
    targets: tuple[AllocationTarget, ...]
    rules: tuple[Rule, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainValidationError("투자헌장 이름은 비어 있을 수 없다")
        if not self.targets:
            raise DomainValidationError("목표 자산비중이 하나도 정의되지 않았다")

        duplicated_classes = [
            asset_class
            for asset_class, count in Counter(t.asset_class for t in self.targets).items()
            if count > 1
        ]
        if duplicated_classes:
            raise DomainValidationError(f"중복 정의된 자산군: {duplicated_classes}")

        total = sum((t.target.ratio for t in self.targets), Decimal(0))
        if total != Decimal(1):
            raise DomainValidationError(
                f"목표비중 합계는 100%여야 한다: 현재 {Percentage.from_ratio(total).as_percent}%"
            )

        duplicated_rules = [
            rule_id
            for rule_id, count in Counter(r.rule_id for r in self.rules).items()
            if count > 1
        ]
        if duplicated_rules:
            raise DomainValidationError(f"중복된 rule_id: {duplicated_rules}")

    def target_for(self, asset_class: AssetClass) -> AllocationTarget | None:
        for target in self.targets:
            if target.asset_class is asset_class:
                return target
        return None
