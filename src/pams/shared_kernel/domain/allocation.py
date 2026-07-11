"""AllocationTarget: 자산군별 목표비중과 허용밴드.

투자헌장(ips)이 정의하고 리밸런싱(rebalancing)이 소비하는 공유 어휘다.
"""

from __future__ import annotations

from dataclasses import dataclass

from pams.shared_kernel.domain.asset_class import AssetClass
from pams.shared_kernel.domain.errors import DomainValidationError
from pams.shared_kernel.domain.percentage import Percentage

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

    def contains(self, weight: Percentage) -> bool:
        """weight가 허용밴드 안에 있는가 (경계 포함)."""
        return self.min_weight <= weight <= self.max_weight
