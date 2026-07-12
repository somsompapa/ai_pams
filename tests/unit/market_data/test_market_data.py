"""시장 데이터 도메인 모델(PricePoint, ExchangeRate) 및 공급자 포트 테스트."""

from datetime import date
from decimal import Decimal

import pytest

from pams.market_data.domain import (
    ExchangeRate,
    ExchangeRateProvider,
    PricePoint,
    PriceProvider,
)
from pams.shared_kernel.domain import Currency, DomainValidationError, Money

AS_OF = date(2026, 7, 10)


class TestPricePoint:
    def test_valid(self) -> None:
        point = PricePoint(
            asset_id="KRX:005930",
            price_date=AS_OF,
            close=Money.of("70000", Currency.KRW),
        )
        assert point.close.currency is Currency.KRW

    def test_non_positive_price_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            PricePoint(asset_id="KRX:005930", price_date=AS_OF, close=Money.zero(Currency.KRW))

    def test_empty_asset_id_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            PricePoint(asset_id="", price_date=AS_OF, close=Money.of("1", Currency.KRW))


class TestExchangeRate:
    def test_convert(self) -> None:
        """1 USD = 1,380 KRW 일 때 100 USD → 138,000 KRW."""
        rate = ExchangeRate(
            base=Currency.USD,
            quote=Currency.KRW,
            rate=Decimal("1380"),
            rate_date=AS_OF,
        )
        converted = rate.convert(Money.of("100", Currency.USD))
        assert converted == Money.of("138000", Currency.KRW)

    def test_convert_rejects_wrong_currency(self) -> None:
        rate = ExchangeRate(
            base=Currency.USD, quote=Currency.KRW, rate=Decimal("1380"), rate_date=AS_OF
        )
        with pytest.raises(DomainValidationError):
            rate.convert(Money.of("100", Currency.JPY))

    def test_same_base_quote_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            ExchangeRate(base=Currency.KRW, quote=Currency.KRW, rate=Decimal("1"), rate_date=AS_OF)

    def test_non_positive_rate_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            ExchangeRate(base=Currency.USD, quote=Currency.KRW, rate=Decimal("0"), rate_date=AS_OF)


class TestProviderPorts:
    """공급자는 포트(Protocol)로 추상화되어 어떤 구현으로든 교체 가능해야 한다."""

    def test_in_memory_price_provider_satisfies_port(self) -> None:
        class InMemoryPriceProvider:
            def __init__(self, prices: dict[str, PricePoint]) -> None:
                self._prices = prices

            def get_price(self, asset_id: str, as_of: date) -> PricePoint | None:
                return self._prices.get(asset_id)

        provider = InMemoryPriceProvider(
            {
                "KRX:005930": PricePoint(
                    asset_id="KRX:005930",
                    price_date=AS_OF,
                    close=Money.of("70000", Currency.KRW),
                )
            }
        )
        assert isinstance(provider, PriceProvider)
        found = provider.get_price("KRX:005930", AS_OF)
        assert found is not None and found.close == Money.of("70000", Currency.KRW)
        assert provider.get_price("NASDAQ:AAPL", AS_OF) is None

    def test_in_memory_fx_provider_satisfies_port(self) -> None:
        class InMemoryFxProvider:
            def get_rate(self, base: Currency, quote: Currency, as_of: date) -> ExchangeRate | None:
                if (base, quote) == (Currency.USD, Currency.KRW):
                    return ExchangeRate(
                        base=base, quote=quote, rate=Decimal("1380"), rate_date=as_of
                    )
                return None

        provider = InMemoryFxProvider()
        assert isinstance(provider, ExchangeRateProvider)
        assert provider.get_rate(Currency.USD, Currency.KRW, AS_OF) is not None
