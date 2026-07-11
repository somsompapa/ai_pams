"""CSV 시세/환율 어댑터 통합 테스트.

핵심 계약: as_of 당일 시세가 없으면 '직전' 시세를 쓴다 (주말/휴장 대응).
단, as_of 이후의 미래 시세는 절대 쓰지 않는다.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pams.market_data.infrastructure import (
    CsvDataError,
    CsvFxLookup,
    CsvPriceLookup,
)
from pams.portfolio.domain import FxLookup, PriceLookup
from pams.shared_kernel.domain import Currency, Money

PRICES = """asset_id,price_date,close,currency
KRX:005930,2026-07-08,74000,KRW
KRX:005930,2026-07-10,75000,KRW
NASDAQ:AAPL,2026-07-09,220,USD
"""

FX = """base,quote,rate_date,rate
USD,KRW,2026-07-08,1375
USD,KRW,2026-07-10,1380
"""


def write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestCsvPriceLookup:
    def make(self, tmp_path: Path, content: str = PRICES) -> CsvPriceLookup:
        return CsvPriceLookup(write(tmp_path, "prices.csv", content))

    def test_satisfies_port(self, tmp_path: Path) -> None:
        assert isinstance(self.make(tmp_path), PriceLookup)

    def test_exact_date(self, tmp_path: Path) -> None:
        price = self.make(tmp_path).price_of("KRX:005930", date(2026, 7, 10))
        assert price == Money.of("75000", Currency.KRW)

    def test_falls_back_to_latest_before(self, tmp_path: Path) -> None:
        """7/9엔 시세가 없다 → 7/8 시세 사용 (미래 7/10은 금지)."""
        price = self.make(tmp_path).price_of("KRX:005930", date(2026, 7, 9))
        assert price == Money.of("74000", Currency.KRW)

    def test_before_first_record_returns_none(self, tmp_path: Path) -> None:
        assert self.make(tmp_path).price_of("KRX:005930", date(2026, 7, 1)) is None

    def test_unknown_asset_returns_none(self, tmp_path: Path) -> None:
        assert self.make(tmp_path).price_of("KRX:000000", date(2026, 7, 10)) is None

    def test_bad_row_reports_row_number(self, tmp_path: Path) -> None:
        bad = "asset_id,price_date,close,currency\nKRX:005930,2026-07-08,,KRW\n"
        with pytest.raises(CsvDataError, match="2행"):
            self.make(tmp_path, bad).price_of("KRX:005930", date(2026, 7, 10))


class TestCsvFxLookup:
    def make(self, tmp_path: Path) -> CsvFxLookup:
        return CsvFxLookup(write(tmp_path, "fx.csv", FX))

    def test_satisfies_port(self, tmp_path: Path) -> None:
        assert isinstance(self.make(tmp_path), FxLookup)

    def test_exact_and_fallback(self, tmp_path: Path) -> None:
        lookup = self.make(tmp_path)
        assert lookup.rate_to(Currency.USD, Currency.KRW, date(2026, 7, 10)) == Decimal("1380")
        assert lookup.rate_to(Currency.USD, Currency.KRW, date(2026, 7, 9)) == Decimal("1375")

    def test_unknown_pair_returns_none(self, tmp_path: Path) -> None:
        assert self.make(tmp_path).rate_to(Currency.JPY, Currency.KRW, date(2026, 7, 10)) is None
