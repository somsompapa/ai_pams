"""DCA(정액·정량 분할매수) 계획 모델.

DCA(Dollar Cost Averaging)는 시장 타이밍을 재지 않고 대기자금을 정기적으로
나눠 투입하는 적립식 매수 전략이다. IPS의 목표비중을 향해 현금을 '천천히'
이동시키는 실행 메커니즘이며, 판단(살지 말지)은 이미 사용자가 정해둔 계획이
내리고 시스템은 "오늘 매수 예정분"을 계산해 제안까지만 한다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import StrEnum, unique

from pams.shared_kernel.domain import (
    Currency,
    DomainValidationError,
    Money,
    Quantity,
)

_WEEKDAY_MAX = 6  # 0=월 ... 6=일


@unique
class DcaFrequency(StrEnum):
    DAILY = "daily"  # 매 거래일(평일)
    WEEKLY = "weekly"  # 매주 특정 요일


@dataclass(frozen=True, slots=True)
class DcaEntry:
    """단일 자산에 대한 정기 적립매수 규칙.

    amount(정액)와 quantity(정량) 중 정확히 하나만 지정한다.
    WEEKLY는 weekday(0=월~6=일)가 필수, DAILY는 weekday를 두지 않는다.
    """

    asset_id: str
    frequency: DcaFrequency
    amount: Money | None = None
    quantity: Quantity | None = None
    weekday: int | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise DomainValidationError("asset_id는 비어 있을 수 없다")
        if (self.amount is None) == (self.quantity is None):
            raise DomainValidationError(
                f"{self.asset_id}: amount(정액)와 quantity(정량) 중 정확히 하나만 지정해야 한다"
            )
        if self.amount is not None and not self.amount.is_positive:
            raise DomainValidationError(f"{self.asset_id}: 매수 금액은 양수여야 한다")
        if self.quantity is not None and self.quantity.is_zero:
            raise DomainValidationError(f"{self.asset_id}: 매수 수량은 양수여야 한다")
        if self.frequency is DcaFrequency.WEEKLY:
            if self.weekday is None:
                raise DomainValidationError(f"{self.asset_id}: WEEKLY는 weekday(요일)가 필요하다")
            if not 0 <= self.weekday <= _WEEKDAY_MAX:
                raise DomainValidationError(
                    f"{self.asset_id}: weekday는 0(월)~6(일)이어야 한다: {self.weekday}"
                )
        elif self.weekday is not None:
            raise DomainValidationError(f"{self.asset_id}: DAILY는 weekday를 지정하지 않는다")

    @property
    def _dedup_key(self) -> tuple[str, DcaFrequency, int | None]:
        return (self.asset_id, self.frequency, self.weekday)

    def is_due(self, on_date: date) -> bool:
        if self.frequency is DcaFrequency.DAILY:
            return on_date.weekday() < 5  # 월(0)~금(4)
        return on_date.weekday() == self.weekday

    def to_order(self) -> DcaOrder:
        return DcaOrder(
            asset_id=self.asset_id,
            amount=self.amount,
            quantity=self.quantity,
            note=self.note,
        )


@dataclass(frozen=True, slots=True)
class DcaOrder:
    """특정 일자에 매수 예정인 1건. 시스템의 제안이며 실행은 사용자가 한다."""

    asset_id: str
    amount: Money | None
    quantity: Quantity | None
    note: str = ""


@dataclass(frozen=True, slots=True)
class DcaPlan:
    entries: tuple[DcaEntry, ...]

    def __post_init__(self) -> None:
        duplicated = [
            key for key, count in Counter(e._dedup_key for e in self.entries).items() if count > 1
        ]
        if duplicated:
            raise DomainValidationError(f"중복된 DCA 규칙(자산·주기·요일): {duplicated}")

    def due_on(self, on_date: date) -> tuple[DcaOrder, ...]:
        return tuple(entry.to_order() for entry in self.entries if entry.is_due(on_date))

    def amount_totals(self) -> dict[Currency, Money]:
        """정액 항목의 통화별 1회 매수 합계(정량 항목 제외). 요약 표시용."""
        totals: dict[Currency, Money] = {}
        for entry in self.entries:
            if entry.amount is None:
                continue
            currency = entry.amount.currency
            totals[currency] = totals.get(currency, Money.zero(currency)) + entry.amount
        return totals
