"""성과분석 입력 시계열: 평가액 + 외부 현금흐름.

입출금은 수익이 아니므로, 수익률은 시간가중(TWR) 방식으로 계산한다:
구간 성장배수 = (V_i - F_i) / V_{i-1}  (F_i = 해당 일자의 순입출금, 입금 +, 출금 -)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pams.shared_kernel.domain import DomainError, DomainValidationError


class PerformanceCalculationError(DomainError):
    """성과 지표를 계산할 수 없다 (데이터 부족, 정의 불가한 수익률 등)."""


@dataclass(frozen=True, slots=True)
class ValuationPoint:
    """특정 일자의 포트폴리오 평가액과 그날 발생한 순입출금."""

    point_date: date
    value: Decimal
    net_flow: Decimal  # 입금 +, 출금 -. 없으면 0

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal) or not isinstance(self.net_flow, Decimal):
            raise DomainValidationError(
                f"{self.point_date}: 평가액/현금흐름은 Decimal이어야 한다 (float 금지)"
            )
        if self.value <= 0:
            raise DomainValidationError(f"{self.point_date}: 평가액은 양수여야 한다: {self.value}")


@dataclass(frozen=True, slots=True)
class PerformanceHistory:
    points: tuple[ValuationPoint, ...]

    @classmethod
    def from_points(cls, points: Iterable[ValuationPoint]) -> PerformanceHistory:
        ordered = tuple(sorted(points, key=lambda p: p.point_date))
        if not ordered:
            raise DomainValidationError("성과 시계열이 비어 있다")
        dates = [p.point_date for p in ordered]
        if len(set(dates)) != len(dates):
            raise DomainValidationError("중복된 날짜가 있다")
        return cls(ordered)

    @property
    def start_date(self) -> date:
        return self.points[0].point_date

    @property
    def end_date(self) -> date:
        return self.points[-1].point_date

    def growth_factors(self) -> tuple[tuple[date, Decimal], ...]:
        """인접 구간의 (종료일, 성장배수) 목록. TWR의 원재료."""
        if len(self.points) < 2:
            raise PerformanceCalculationError("수익률 계산에는 평가액이 2개 이상 필요하다")
        factors = []
        for previous, current in zip(self.points, self.points[1:], strict=False):
            adjusted_end = current.value - current.net_flow
            if adjusted_end <= 0:
                raise PerformanceCalculationError(
                    f"{current.point_date}: 현금흐름({current.net_flow})을 제외한 "
                    f"평가액이 0 이하라 수익률이 정의되지 않는다"
                )
            factors.append((current.point_date, adjusted_end / previous.value))
        return tuple(factors)

    def cumulative_twr(self) -> Decimal:
        """전체 기간 시간가중수익률."""
        product = Decimal(1)
        for _end_date, factor in self.growth_factors():
            product *= factor
        return product - 1
