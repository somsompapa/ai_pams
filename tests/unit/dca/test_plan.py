"""DCA(정액·정량 분할매수) 계획 도메인 테스트.

DCA는 대기자금을 시장 타이밍 없이 정기적으로 나눠 투입하는 적립식 매수다.
시스템은 "오늘 살 것"을 제안까지만 하고, 실제 매수/기록은 사용자가 한다.
"""

from datetime import date

import pytest

from pams.dca.domain import DcaEntry, DcaFrequency, DcaOrder, DcaPlan
from pams.shared_kernel.domain import Currency, DomainValidationError, Money, Quantity

# 2026-07-13 = 월요일, 07-18 = 토요일
MONDAY = date(2026, 7, 13)
TUESDAY = date(2026, 7, 14)
SATURDAY = date(2026, 7, 18)


class TestDcaEntry:
    def test_daily_amount_entry(self) -> None:
        entry = DcaEntry(
            asset_id="NYSEARCA:SCHD",
            frequency=DcaFrequency.DAILY,
            amount=Money.of("70000", Currency.KRW),
        )
        assert entry.is_due(MONDAY)
        assert entry.is_due(TUESDAY)

    def test_daily_not_due_on_weekend(self) -> None:
        entry = DcaEntry(
            asset_id="NYSEARCA:SPY",
            frequency=DcaFrequency.DAILY,
            amount=Money.of("320000", Currency.KRW),
        )
        assert not entry.is_due(SATURDAY)

    def test_weekly_entry_due_only_on_its_weekday(self) -> None:
        entry = DcaEntry(
            asset_id="KRX:069500",
            frequency=DcaFrequency.WEEKLY,
            quantity=Quantity.of(1),
            weekday=0,  # 월요일
        )
        assert entry.is_due(MONDAY)
        assert not entry.is_due(TUESDAY)
        assert not entry.is_due(SATURDAY)

    def test_requires_exactly_one_of_amount_or_quantity(self) -> None:
        with pytest.raises(DomainValidationError, match="amount.*quantity|정액.*정량"):
            DcaEntry(asset_id="X", frequency=DcaFrequency.DAILY)
        with pytest.raises(DomainValidationError, match="amount.*quantity|정액.*정량"):
            DcaEntry(
                asset_id="X",
                frequency=DcaFrequency.DAILY,
                amount=Money.of("1000", Currency.KRW),
                quantity=Quantity.of(1),
            )

    def test_weekly_requires_weekday(self) -> None:
        with pytest.raises(DomainValidationError, match="weekday|요일"):
            DcaEntry(
                asset_id="X",
                frequency=DcaFrequency.WEEKLY,
                quantity=Quantity.of(1),
            )

    def test_daily_rejects_weekday(self) -> None:
        with pytest.raises(DomainValidationError, match="weekday|요일"):
            DcaEntry(
                asset_id="X",
                frequency=DcaFrequency.DAILY,
                amount=Money.of("1000", Currency.KRW),
                weekday=0,
            )

    def test_weekday_out_of_range_rejected(self) -> None:
        with pytest.raises(DomainValidationError, match="weekday|요일"):
            DcaEntry(
                asset_id="X",
                frequency=DcaFrequency.WEEKLY,
                quantity=Quantity.of(1),
                weekday=7,
            )

    def test_empty_asset_id_rejected(self) -> None:
        with pytest.raises(DomainValidationError, match="asset_id"):
            DcaEntry(
                asset_id="  ",
                frequency=DcaFrequency.DAILY,
                amount=Money.of("1000", Currency.KRW),
            )

    def test_non_positive_amount_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            DcaEntry(
                asset_id="X",
                frequency=DcaFrequency.DAILY,
                amount=Money.zero(Currency.KRW),
            )


class TestDcaPlan:
    def _plan(self) -> DcaPlan:
        return DcaPlan(
            entries=(
                DcaEntry(
                    "NYSEARCA:SCHD", DcaFrequency.DAILY, amount=Money.of("70000", Currency.KRW)
                ),
                DcaEntry(
                    "NYSEARCA:SPY", DcaFrequency.DAILY, amount=Money.of("320000", Currency.KRW)
                ),
                DcaEntry("KRX:069500", DcaFrequency.WEEKLY, quantity=Quantity.of(1), weekday=0),
            )
        )

    def test_due_on_monday_includes_weekly(self) -> None:
        orders = self._plan().due_on(MONDAY)
        assert len(orders) == 3
        assert all(isinstance(o, DcaOrder) for o in orders)
        assert {o.asset_id for o in orders} == {
            "NYSEARCA:SCHD",
            "NYSEARCA:SPY",
            "KRX:069500",
        }

    def test_due_on_tuesday_excludes_weekly(self) -> None:
        orders = self._plan().due_on(TUESDAY)
        assert {o.asset_id for o in orders} == {"NYSEARCA:SCHD", "NYSEARCA:SPY"}

    def test_due_on_weekend_is_empty(self) -> None:
        assert self._plan().due_on(SATURDAY) == ()

    def test_duplicate_entry_rejected(self) -> None:
        with pytest.raises(DomainValidationError, match="중복"):
            DcaPlan(
                entries=(
                    DcaEntry(
                        "NYSEARCA:SPY",
                        DcaFrequency.DAILY,
                        amount=Money.of("320000", Currency.KRW),
                    ),
                    DcaEntry(
                        "NYSEARCA:SPY",
                        DcaFrequency.DAILY,
                        amount=Money.of("10000", Currency.KRW),
                    ),
                )
            )

    def test_daily_total_amount_by_currency(self) -> None:
        """정액 항목의 통화별 1회 매수 합계 (정량 항목은 제외)."""
        totals = self._plan().amount_totals()
        assert totals[Currency.KRW] == Money.of("390000", Currency.KRW)
