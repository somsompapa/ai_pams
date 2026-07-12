"""Quote 값객체 + FetchMarketData 유스케이스 테스트."""

from datetime import date
from decimal import Decimal

import pytest

from pams.market_data.application import FetchMarketData, FetchResult
from pams.market_data.domain import (
    MarketDataProviderError,
    Quote,
    QuoteProvider,
    SymbolMap,
)
from pams.shared_kernel.domain import Currency, DomainValidationError

QUOTE_DATE = date(2026, 7, 10)


class TestQuote:
    def test_valid(self) -> None:
        quote = Quote(
            symbol="AAPL", quote_date=QUOTE_DATE, close=Decimal("220"), currency=Currency.USD
        )
        assert quote.close == Decimal("220")

    def test_float_close_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            Quote(symbol="AAPL", quote_date=QUOTE_DATE, close=220.0, currency=Currency.USD)  # type: ignore[arg-type]

    def test_non_positive_close_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            Quote(symbol="AAPL", quote_date=QUOTE_DATE, close=Decimal("0"), currency=Currency.USD)


class TestSymbolMap:
    def test_parses_three_sections(self) -> None:
        symbol_map = SymbolMap.from_dict(
            {
                "prices": {"KRX:005930": "005930.KS", "NASDAQ:AAPL": "AAPL"},
                "fx": {"USD/KRW": "KRW=X"},
                "indicators": {"vix": "^VIX"},
            }
        )
        assert symbol_map.prices == {"KRX:005930": "005930.KS", "NASDAQ:AAPL": "AAPL"}
        assert symbol_map.fx == {(Currency.USD, Currency.KRW): "KRW=X"}
        assert symbol_map.indicators == {"vix": "^VIX"}

    def test_bad_fx_pair_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            SymbolMap.from_dict({"fx": {"USD-KRW": "KRW=X"}})

    def test_empty_sections_default(self) -> None:
        symbol_map = SymbolMap.from_dict({})
        assert symbol_map.prices == {} and symbol_map.fx == {} and symbol_map.indicators == {}


class FakeProvider:
    def __init__(self, quotes: dict[str, Quote]) -> None:
        self._quotes = quotes
        self.requested: list[str] = []

    def latest_quote(self, symbol: str) -> Quote | None:
        self.requested.append(symbol)
        return self._quotes.get(symbol)


def quote(symbol: str, close: str, currency: Currency = Currency.KRW) -> Quote:
    return Quote(symbol=symbol, quote_date=QUOTE_DATE, close=Decimal(close), currency=currency)


SYMBOLS = SymbolMap.from_dict(
    {
        "prices": {"KRX:005930": "005930.KS", "NASDAQ:AAPL": "AAPL"},
        "fx": {"USD/KRW": "KRW=X"},
        "indicators": {"vix": "^VIX"},
    }
)


class TestFetchMarketData:
    def test_provider_port(self) -> None:
        assert isinstance(FakeProvider({}), QuoteProvider)

    def test_collects_prices_fx_indicators(self) -> None:
        provider = FakeProvider(
            {
                "005930.KS": quote("005930.KS", "75000", Currency.KRW),
                "AAPL": quote("AAPL", "220", Currency.USD),
                "KRW=X": quote("KRW=X", "1380", Currency.KRW),
                "^VIX": quote("^VIX", "24.5", Currency.USD),
            }
        )
        result = FetchMarketData(provider=provider).execute(symbols=SYMBOLS)
        assert isinstance(result, FetchResult)
        assert result.prices["KRX:005930"].close == Decimal("75000")
        assert result.prices["NASDAQ:AAPL"].currency is Currency.USD
        assert result.fx[(Currency.USD, Currency.KRW)] == Decimal("1380")
        assert result.indicators["vix"] == Decimal("24.5")
        assert result.errors == []

    def test_missing_symbol_recorded_as_error_not_crash(self) -> None:
        provider = FakeProvider({"005930.KS": quote("005930.KS", "75000")})
        result = FetchMarketData(provider=provider).execute(symbols=SYMBOLS)
        assert "KRX:005930" in result.prices
        assert any("AAPL" in e for e in result.errors)
        assert any("^VIX" in e for e in result.errors)

    def test_provider_exception_recorded_as_error(self) -> None:
        class BrokenProvider:
            def latest_quote(self, symbol: str) -> Quote | None:
                raise MarketDataProviderError(f"boom {symbol}")

        result = FetchMarketData(provider=BrokenProvider()).execute(symbols=SYMBOLS)
        assert result.prices == {}
        assert len(result.errors) == 4  # 2 prices + 1 fx + 1 indicator
