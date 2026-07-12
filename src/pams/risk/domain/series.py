"""수익률 계산의 기초 시계열 값객체.

리스크 지표는 전부 Decimal 순수 계산으로 구현한다 - domain은 외부 라이브러리
(numpy/pandas)에 의존하지 않으며, float 이진 오차도 유입되지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pams.shared_kernel.domain import DomainError, DomainValidationError


class InsufficientDataError(DomainError):
    """지표를 계산하기에 데이터가 부족하다. 부족한 채 0을 반환하면 오판을 부른다."""


def _validated_entries(
    pairs: Iterable[tuple[date, Decimal]], *, positive_only: bool
) -> tuple[tuple[date, Decimal], ...]:
    entries = sorted(pairs, key=lambda pair: pair[0])
    if not entries:
        raise DomainValidationError("시계열이 비어 있다")
    seen: set[date] = set()
    for entry_date, value in entries:
        if not isinstance(value, Decimal):
            raise DomainValidationError(f"{entry_date}: 값은 Decimal이어야 한다: {value!r}")
        if entry_date in seen:
            raise DomainValidationError(f"중복된 날짜: {entry_date}")
        seen.add(entry_date)
        if positive_only and value <= 0:
            raise DomainValidationError(f"{entry_date}: 가치는 양수여야 한다: {value}")
    return tuple(entries)


@dataclass(frozen=True, slots=True)
class ReturnSeries:
    """기간 수익률(비율) 시계열."""

    entries: tuple[tuple[date, Decimal], ...]

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[date, Decimal]]) -> ReturnSeries:
        return cls(_validated_entries(pairs, positive_only=False))

    @property
    def dates(self) -> tuple[date, ...]:
        return tuple(entry_date for entry_date, _value in self.entries)

    @property
    def values(self) -> tuple[Decimal, ...]:
        return tuple(value for _date, value in self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def mean(self) -> Decimal:
        return sum(self.values, Decimal(0)) / len(self)

    @property
    def sample_std(self) -> Decimal:
        """표본 표준편차 (n-1 분모)."""
        if len(self) < 2:
            raise InsufficientDataError("표준편차 계산에는 수익률이 2개 이상 필요하다")
        mean = self.mean
        variance = sum(((v - mean) ** 2 for v in self.values), Decimal(0)) / (len(self) - 1)
        return variance.sqrt()

    def downside_deviation(self, target: Decimal) -> Decimal:
        """목표수익률(target) 미달분만의 제곱평균제곱근 (분모 n)."""
        shortfalls = [min(v - target, Decimal(0)) for v in self.values]
        mean_square = sum((s**2 for s in shortfalls), Decimal(0)) / len(self)
        return mean_square.sqrt()

    def align(self, other: ReturnSeries) -> tuple[ReturnSeries, ReturnSeries]:
        """두 시계열의 공통 날짜 구간만 남긴다 (벤치마크 비교용)."""
        common = set(self.dates) & set(other.dates)
        if not common:
            raise InsufficientDataError("두 시계열에 공통 날짜가 없다")
        mine = ReturnSeries.from_pairs([e for e in self.entries if e[0] in common])
        theirs = ReturnSeries.from_pairs([e for e in other.entries if e[0] in common])
        return mine, theirs


@dataclass(frozen=True, slots=True)
class ValueSeries:
    """일별 포트폴리오(또는 벤치마크) 가치 시계열."""

    entries: tuple[tuple[date, Decimal], ...]

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[date, Decimal]]) -> ValueSeries:
        return cls(_validated_entries(pairs, positive_only=True))

    @property
    def dates(self) -> tuple[date, ...]:
        return tuple(entry_date for entry_date, _value in self.entries)

    @property
    def values(self) -> tuple[Decimal, ...]:
        return tuple(value for _date, value in self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def start(self) -> tuple[date, Decimal]:
        return self.entries[0]

    @property
    def end(self) -> tuple[date, Decimal]:
        return self.entries[-1]

    def returns(self) -> ReturnSeries:
        if len(self) < 2:
            raise InsufficientDataError("수익률 계산에는 가치가 2개 이상 필요하다")
        pairs = [
            (current_date, current / previous - 1)
            for (_pd, previous), (current_date, current) in zip(
                self.entries, self.entries[1:], strict=False
            )
        ]
        return ReturnSeries.from_pairs(pairs)
