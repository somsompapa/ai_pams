"""PolicyStatement: 투자헌장(IPS) - 시스템의 최상위 규칙 문서."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from pams.ips.domain.rule import Rule
from pams.shared_kernel.domain import (
    AssetClass,
    Currency,
    DomainValidationError,
    Percentage,
)

_ZERO = Percentage.zero()
_FULL = Percentage.from_percent(100)


@dataclass(frozen=True, slots=True)
class AllocationTarget:
    """자산군별 목표비중과 허용밴드(±). 밴드를 벗어나면 리밸런싱 대상이다."""

    asset_class: AssetClass
    target: Percentage
    band: Percentage

    def __post_init__(self) -> None:
        if not (_ZERO <= self.target <= _FULL):
            raise DomainValidationError(
                f"{self.asset_class} 목표비중은 0~100% 사이여야 한다: {self.target.as_percent}%"
            )
        if self.band < _ZERO:
            raise DomainValidationError(
                f"{self.asset_class} 허용밴드는 음수가 될 수 없다: {self.band.as_percent}%"
            )

    @property
    def min_weight(self) -> Percentage:
        low = self.target - self.band
        return low if low > _ZERO else _ZERO

    @property
    def max_weight(self) -> Percentage:
        high = self.target + self.band
        return high if high < _FULL else _FULL


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
