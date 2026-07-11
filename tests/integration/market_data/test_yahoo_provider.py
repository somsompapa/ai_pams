"""YahooQuoteProvider 통합 테스트 (HTTP는 MockTransport로 목킹).

실제 네트워크 호출은 사용자의 배포 환경에서 이루어진다. 여기서는 어댑터의
요청/응답 파싱 계약만 검증한다.
"""

from decimal import Decimal

import httpx
import pytest

from pams.market_data.domain import MarketDataProviderError, QuoteProvider
from pams.market_data.infrastructure import YahooQuoteProvider
from pams.shared_kernel.domain import Currency


def chart_response(price: float, currency: str, epoch: int) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": price,
                        "currency": currency,
                        "regularMarketTime": epoch,
                    }
                }
            ],
            "error": None,
        }
    }


class TestYahooQuoteProvider:
    def make(self, handler) -> YahooQuoteProvider:  # type: ignore[no-untyped-def]
        return YahooQuoteProvider(transport=httpx.MockTransport(handler))

    def test_satisfies_port(self) -> None:
        assert isinstance(self.make(lambda _r: httpx.Response(200)), QuoteProvider)

    def test_parses_quote(self) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json=chart_response(75000.0, "KRW", 1783684800))

        provider = self.make(handler)
        quote = provider.latest_quote("005930.KS")
        assert quote is not None
        assert quote.symbol == "005930.KS"
        assert quote.close == Decimal("75000.0")
        assert quote.currency is Currency.KRW
        assert "005930.KS" in captured["url"]

    def test_decimal_not_float(self) -> None:
        provider = self.make(
            lambda _r: httpx.Response(200, json=chart_response(0.1, "USD", 1783684800))
        )
        quote = provider.latest_quote("X")
        assert quote is not None
        assert quote.close == Decimal("0.1")  # str 경유 변환으로 이진오차 없음

    def test_unknown_symbol_returns_none(self) -> None:
        body = {"chart": {"result": None, "error": {"code": "Not Found"}}}
        provider = self.make(lambda _r: httpx.Response(404, json=body))
        assert provider.latest_quote("NOPE") is None

    def test_unsupported_currency_raises(self) -> None:
        provider = self.make(
            lambda _r: httpx.Response(200, json=chart_response(100.0, "ZZZ", 1783684800))
        )
        with pytest.raises(MarketDataProviderError, match="ZZZ"):
            provider.latest_quote("X")

    def test_http_error_raises(self) -> None:
        provider = self.make(lambda _r: httpx.Response(500))
        with pytest.raises(MarketDataProviderError):
            provider.latest_quote("X")
