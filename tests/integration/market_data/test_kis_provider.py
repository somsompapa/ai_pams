"""KisQuoteProvider(한국투자증권 OpenAPI) 통합 테스트 (HTTP는 MockTransport로 목킹).

실제 인증/네트워크는 사용자의 배포 환경에서 이루어진다. 여기서는 토큰 발급/캐시,
국내·해외 현재가 조회, 오류 매핑 계약만 검증한다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from pams.market_data.domain import MarketDataProviderError, QuoteProvider
from pams.market_data.infrastructure import KisQuoteProvider
from pams.shared_kernel.domain import Currency

_TOKEN_PATH = "/oauth2/tokenP"
_DOMESTIC_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
_OVERSEAS_PATH = "/uapi/overseas-price/v1/quotations/price"


def _token_response(*, expires_in: int = 86400) -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": "tok-123", "token_type": "Bearer", "expires_in": expires_in}
    )


class TestKisQuoteProvider:
    def make(self, handler, *, token_cache_path: Path | None = None) -> KisQuoteProvider:  # type: ignore[no-untyped-def]
        return KisQuoteProvider(
            app_key="key",
            app_secret="secret",
            transport=httpx.MockTransport(handler),
            token_cache_path=token_cache_path,
        )

    def test_satisfies_port(self) -> None:
        assert isinstance(self.make(lambda _r: httpx.Response(200)), QuoteProvider)

    def test_domestic_quote_requests_token_then_price(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == _TOKEN_PATH:
                return _token_response()
            assert request.url.path == _DOMESTIC_PATH
            assert request.headers["authorization"] == "Bearer tok-123"
            assert request.headers["tr_id"] == "FHKST01010100"
            assert request.url.params["fid_input_iscd"] == "005930"
            return httpx.Response(200, json={"rt_cd": "0", "output": {"stck_prpr": "75000"}})

        quote = self.make(handler).latest_quote("005930")
        assert quote is not None
        assert quote.symbol == "005930"
        assert quote.close == Decimal("75000")
        assert quote.currency is Currency.KRW
        assert calls == [_TOKEN_PATH, _DOMESTIC_PATH]

    def test_overseas_quote_parses_symbol_and_currency(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                return _token_response()
            assert request.url.path == _OVERSEAS_PATH
            assert request.headers["tr_id"] == "HHDFS00000300"
            assert request.url.params["EXCD"] == "NAS"
            assert request.url.params["SYMB"] == "AAPL"
            return httpx.Response(200, json={"rt_cd": "0", "output": {"last": "220.5"}})

        quote = self.make(handler).latest_quote("NAS:AAPL")
        assert quote is not None
        assert quote.close == Decimal("220.5")
        assert quote.currency is Currency.USD

    def test_unsupported_exchange_raises(self) -> None:
        provider = self.make(lambda r: _token_response() if r.url.path == _TOKEN_PATH else None)
        with pytest.raises(MarketDataProviderError, match="TSE"):
            provider.latest_quote("TSE:7203")

    def test_domestic_zero_price_treated_as_unknown_symbol(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                return _token_response()
            return httpx.Response(200, json={"rt_cd": "0", "output": {"stck_prpr": "0"}})

        assert self.make(handler).latest_quote("999999") is None

    def test_error_rt_cd_raises_with_message(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                return _token_response()
            return httpx.Response(200, json={"rt_cd": "1", "msg1": "모의투자 접근 오류"})

        with pytest.raises(MarketDataProviderError, match="모의투자 접근 오류"):
            self.make(handler).latest_quote("005930")

    def test_http_error_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                return _token_response()
            return httpx.Response(500, text="boom")

        with pytest.raises(MarketDataProviderError):
            self.make(handler).latest_quote("005930")

    def test_token_request_failure_raises(self) -> None:
        provider = self.make(lambda _r: httpx.Response(401, text="bad key"))
        with pytest.raises(MarketDataProviderError):
            provider.latest_quote("005930")

    def test_token_cached_to_file_and_reused_across_calls(self, tmp_path: Path) -> None:
        token_calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                token_calls["n"] += 1
                return _token_response()
            return httpx.Response(200, json={"rt_cd": "0", "output": {"stck_prpr": "75000"}})

        cache = tmp_path / ".kis_token.json"
        provider = self.make(handler, token_cache_path=cache)
        provider.latest_quote("005930")
        provider.latest_quote("069500")
        assert token_calls["n"] == 1  # 두번째 호출은 캐시된 토큰 재사용
        assert json.loads(cache.read_text(encoding="utf-8"))["access_token"] == "tok-123"

    def test_expired_cached_token_is_refreshed(self, tmp_path: Path) -> None:
        cache = tmp_path / ".kis_token.json"
        expired_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        cache.write_text(
            json.dumps({"access_token": "stale", "expires_at": expired_at}), encoding="utf-8"
        )
        token_calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                token_calls["n"] += 1
                return _token_response()
            assert request.headers["authorization"] == "Bearer tok-123"
            return httpx.Response(200, json={"rt_cd": "0", "output": {"stck_prpr": "75000"}})

        self.make(handler, token_cache_path=cache).latest_quote("005930")
        assert token_calls["n"] == 1

    def test_fresh_cached_token_skips_token_request(self, tmp_path: Path) -> None:
        cache = tmp_path / ".kis_token.json"
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        cache.write_text(
            json.dumps({"access_token": "cached-tok", "expires_at": future}), encoding="utf-8"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path != _TOKEN_PATH
            assert request.headers["authorization"] == "Bearer cached-tok"
            return httpx.Response(200, json={"rt_cd": "0", "output": {"stck_prpr": "75000"}})

        quote = self.make(handler, token_cache_path=cache).latest_quote("005930")
        assert quote is not None
