"""YahooQuoteProvider 통합 테스트 (HTTP는 MockTransport로 목킹).

실제 네트워크 호출은 사용자의 배포 환경에서 이루어진다. 여기서는 어댑터의
요청/응답 파싱 계약만 검증한다.
"""

from datetime import UTC, datetime
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


def _chart_series_response(currency: str, points: list[tuple[int, float | None]]) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {"currency": currency},
                    "timestamp": [epoch for epoch, _ in points],
                    "indicators": {"quote": [{"close": [close for _, close in points]}]},
                }
            ],
            "error": None,
        }
    }


class TestHistoricalQuotes:
    """PER/PBR 5년밴드 계산 전용 — historical_quotes()는 조회 실패해도 예외를
    던지지 않는다(빈 튜플)는 계약이 핵심이다."""

    def make(self, handler) -> YahooQuoteProvider:  # type: ignore[no-untyped-def]
        return YahooQuoteProvider(transport=httpx.MockTransport(handler))

    def test_parses_monthly_series(self) -> None:
        provider = self.make(
            lambda _r: httpx.Response(
                200,
                json=_chart_series_response("KRW", [(1672444800, 60000.0), (1704067200, 65000.0)]),
            )
        )
        points = provider.historical_quotes("005930.KS", years=5)
        assert len(points) == 2
        assert points[0].close == Decimal("60000.0")
        assert points[0].currency is Currency.KRW

    def test_skips_null_close_entries(self) -> None:
        """일부 구간은 거래정지 등으로 close가 null일 수 있다 — 임의로 채우지 않고 건너뛴다."""
        provider = self.make(
            lambda _r: httpx.Response(
                200,
                json=_chart_series_response(
                    "USD", [(1672444800, 100.0), (1675123200, None), (1704067200, 110.0)]
                ),
            )
        )
        points = provider.historical_quotes("X", years=5)
        assert len(points) == 2

    def test_http_error_returns_empty_tuple_not_raises(self) -> None:
        provider = self.make(lambda _r: httpx.Response(500))
        assert provider.historical_quotes("X", years=5) == ()

    def test_unknown_symbol_returns_empty_tuple(self) -> None:
        provider = self.make(
            lambda _r: httpx.Response(404, json={"chart": {"result": None, "error": {}}})
        )
        assert provider.historical_quotes("NOPE", years=5) == ()


def _chart_daily_response(points: list[tuple[int, float | None, int | None]]) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [epoch for epoch, _, _ in points],
                    "indicators": {
                        "quote": [
                            {
                                "close": [close for _, close, _ in points],
                                "volume": [volume for _, _, volume in points],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


class TestRecentDailyBars:
    """유동성 스크리닝(P-5, 최근 20영업일 평균 거래대금) 전용."""

    def make(self, handler) -> YahooQuoteProvider:  # type: ignore[no-untyped-def]
        return YahooQuoteProvider(transport=httpx.MockTransport(handler))

    def test_parses_close_and_volume(self) -> None:
        provider = self.make(
            lambda _r: httpx.Response(
                200,
                json=_chart_daily_response(
                    [(1704067200, 100.0, 1_000_000), (1704153600, 105.0, 1_200_000)]
                ),
            )
        )
        bars = provider.recent_daily_bars("X", days=20)
        assert len(bars) == 2
        assert bars[0].close == Decimal("100.0")
        assert bars[0].volume == 1_000_000

    def test_limits_to_requested_days_keeping_most_recent(self) -> None:
        points = [(1704067200 + i * 86400, 100.0, 1000) for i in range(30)]
        provider = self.make(lambda _r: httpx.Response(200, json=_chart_daily_response(points)))
        bars = provider.recent_daily_bars("X", days=20)
        assert len(bars) == 20
        # 마지막(가장 최신) 관측치가 남아야 한다 — 앞쪽(오래된) 10개가 잘려나간다.
        expected_last_epoch = 1704067200 + 29 * 86400
        assert bars[-1].quote_date.day == datetime.fromtimestamp(expected_last_epoch, tz=UTC).day

    def test_skips_null_volume_entries(self) -> None:
        provider = self.make(
            lambda _r: httpx.Response(
                200,
                json=_chart_daily_response(
                    [(1704067200, 100.0, None), (1704153600, 105.0, 1_000_000)]
                ),
            )
        )
        bars = provider.recent_daily_bars("X", days=20)
        assert len(bars) == 1

    def test_http_error_returns_empty_tuple_not_raises(self) -> None:
        provider = self.make(lambda _r: httpx.Response(500))
        assert provider.recent_daily_bars("X", days=20) == ()
