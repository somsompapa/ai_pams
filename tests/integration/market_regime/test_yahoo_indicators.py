"""YahooMarketRegimeIndicatorProvider 통합 테스트 (HTTP는 MockTransport로 목킹)."""

from decimal import Decimal

import httpx
import pytest

from pams.market_regime.domain.regime import MarketRegimeProviderError
from pams.market_regime.infrastructure.yahoo_indicators import (
    YahooMarketRegimeIndicatorProvider,
)


def _chart_response(closes: list[float | None]) -> dict:
    return {
        "chart": {
            "result": [{"indicators": {"quote": [{"close": closes}]}}],
            "error": None,
        }
    }


class TestYahooMarketRegimeIndicatorProvider:
    def make(self, handler) -> YahooMarketRegimeIndicatorProvider:  # type: ignore[no-untyped-def]
        return YahooMarketRegimeIndicatorProvider(transport=httpx.MockTransport(handler))

    def test_fetch_vix_returns_latest_close(self) -> None:
        provider = self.make(
            lambda _r: httpx.Response(200, json=_chart_response([20.1, 21.5, 22.4]))
        )
        assert provider.fetch_vix() == Decimal("22.4")

    def test_fetch_kospi_change_pct_computes_from_last_two_closes(self) -> None:
        provider = self.make(
            lambda _r: httpx.Response(200, json=_chart_response([2500.0, 2600.0, 2470.0]))
        )
        pct = provider.fetch_kospi_change_pct()
        assert abs(pct - Decimal("-5")) < Decimal("0.001")

    def test_fetch_kospi_change_pct_skips_null_entries(self) -> None:
        """장중 조회 등으로 최신 값이 null이면 그 앞의 유효한 두 값을 쓴다."""
        provider = self.make(
            lambda _r: httpx.Response(200, json=_chart_response([2500.0, 2600.0, None]))
        )
        pct = provider.fetch_kospi_change_pct()
        assert abs(pct - Decimal("4")) < Decimal("0.001")

    def test_insufficient_closes_raises(self) -> None:
        provider = self.make(lambda _r: httpx.Response(200, json=_chart_response([2500.0])))
        with pytest.raises(MarketRegimeProviderError, match="2개 이상"):
            provider.fetch_kospi_change_pct()

    def test_http_error_raises_provider_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("network down")

        provider = self.make(handler)
        with pytest.raises(MarketRegimeProviderError, match="요청 실패"):
            provider.fetch_vix()

    def test_empty_result_raises(self) -> None:
        provider = self.make(
            lambda _r: httpx.Response(200, json={"chart": {"result": [], "error": None}})
        )
        with pytest.raises(MarketRegimeProviderError, match="조회 결과 없음"):
            provider.fetch_vix()
