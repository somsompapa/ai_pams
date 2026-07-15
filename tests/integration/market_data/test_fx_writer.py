"""환율 수동 입력(upsert) 통합 테스트."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from pams.market_data.infrastructure import CsvFxLookup, upsert_fx_rate
from pams.shared_kernel.domain import Currency


class TestUpsertFxRate:
    def test_creates_file_and_adds_rate(self, tmp_path: Path) -> None:
        path = tmp_path / "fx.csv"
        upsert_fx_rate(path, Currency.USD, Currency.KRW, date(2026, 7, 15), Decimal("1380"))
        lookup = CsvFxLookup(path)
        assert lookup.rate_to(Currency.USD, Currency.KRW, date(2026, 7, 15)) == Decimal("1380")

    def test_upsert_replaces_same_date(self, tmp_path: Path) -> None:
        path = tmp_path / "fx.csv"
        upsert_fx_rate(path, Currency.USD, Currency.KRW, date(2026, 7, 15), Decimal("1380"))
        upsert_fx_rate(path, Currency.USD, Currency.KRW, date(2026, 7, 15), Decimal("1400"))
        lookup = CsvFxLookup(path)
        assert lookup.rate_to(Currency.USD, Currency.KRW, date(2026, 7, 15)) == Decimal("1400")
        # 한 행만 있어야 한다(중복 적재 아님)
        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2  # 헤더 + 1행

    def test_keeps_other_dates_and_pairs(self, tmp_path: Path) -> None:
        path = tmp_path / "fx.csv"
        upsert_fx_rate(path, Currency.USD, Currency.KRW, date(2026, 7, 14), Decimal("1370"))
        upsert_fx_rate(path, Currency.USD, Currency.KRW, date(2026, 7, 15), Decimal("1380"))
        upsert_fx_rate(path, Currency.JPY, Currency.KRW, date(2026, 7, 15), Decimal("9.1"))
        lookup = CsvFxLookup(path)
        assert lookup.rate_to(Currency.USD, Currency.KRW, date(2026, 7, 14)) == Decimal("1370")
        assert lookup.rate_to(Currency.USD, Currency.KRW, date(2026, 7, 15)) == Decimal("1380")
        assert lookup.rate_to(Currency.JPY, Currency.KRW, date(2026, 7, 15)) == Decimal("9.1")
