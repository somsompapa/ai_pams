"""TossHoldingsProvider(토스증권 Open API) 통합 테스트 (HTTP는 MockTransport로 목킹).

실제 인증/네트워크는 사용자의 배포 환경에서 이루어진다. 여기서는 토큰/계좌seq
캐시, 보유종목 파싱, 오류 매핑 계약만 검증한다.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from pams.portfolio.domain import BrokerProviderError, HoldingsProvider
from pams.portfolio.infrastructure import TossHoldingsProvider
from pams.shared_kernel.domain import Currency

_TOKEN_PATH = "/oauth2/token"
_ACCOUNTS_PATH = "/api/v1/accounts"
_HOLDINGS_PATH = "/api/v1/holdings"


def _token_response(*, expires_in: int = 86400) -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": "tok-123", "token_type": "Bearer", "expires_in": expires_in}
    )


def _accounts_response(seq: int = 1) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "result": [{"accountNo": "12345678901", "accountSeq": seq, "accountType": "BROKERAGE"}]
        },
    )


def _holdings_response(items: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"result": {"items": items}})


_SAMSUNG_ITEM = {
    "symbol": "005930",
    "name": "삼성전자",
    "marketCountry": "KR",
    "currency": "KRW",
    "quantity": "100",
    "lastPrice": "72000",
    "averagePurchasePrice": "65000",
}


class TestTossHoldingsProvider:
    def make(
        self,
        handler,
        *,
        token_cache_path: Path | None = None,
        account_cache_path: Path | None = None,
    ) -> TossHoldingsProvider:  # type: ignore[no-untyped-def]
        return TossHoldingsProvider(
            client_id="id",
            client_secret="secret",
            transport=httpx.MockTransport(handler),
            token_cache_path=token_cache_path,
            account_cache_path=account_cache_path,
            min_request_interval_seconds=0,
        )

    def test_satisfies_port(self) -> None:
        assert isinstance(self.make(lambda _r: httpx.Response(200)), HoldingsProvider)

    def test_fetches_token_account_then_holdings(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == _TOKEN_PATH:
                assert "grant_type=client_credentials" in request.content.decode()
                return _token_response()
            if request.url.path == _ACCOUNTS_PATH:
                assert request.headers["authorization"] == "Bearer tok-123"
                return _accounts_response(seq=42)
            assert request.url.path == _HOLDINGS_PATH
            assert request.headers["authorization"] == "Bearer tok-123"
            assert request.headers["x-tossinvest-account"] == "42"
            return _holdings_response([_SAMSUNG_ITEM])

        holdings = self.make(handler).holdings()
        assert calls == [_TOKEN_PATH, _ACCOUNTS_PATH, _HOLDINGS_PATH]
        assert len(holdings) == 1
        h = holdings[0]
        assert h.symbol == "005930"
        assert h.quantity == Decimal("100")
        assert h.avg_price == Decimal("65000")
        assert h.current_price == Decimal("72000")
        assert h.currency is Currency.KRW

    def test_parses_multiple_items(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                return _token_response()
            if request.url.path == _ACCOUNTS_PATH:
                return _accounts_response()
            return _holdings_response(
                [
                    _SAMSUNG_ITEM,
                    {
                        "symbol": "AAPL",
                        "name": "Apple Inc.",
                        "marketCountry": "US",
                        "currency": "USD",
                        "quantity": "10",
                        "lastPrice": "178.5",
                        "averagePurchasePrice": "155.3",
                    },
                ]
            )

        holdings = self.make(handler).holdings()
        symbols = {h.symbol for h in holdings}
        assert symbols == {"005930", "AAPL"}

    def test_no_accounts_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                return _token_response()
            if request.url.path == _ACCOUNTS_PATH:
                return httpx.Response(200, json={"result": []})
            raise AssertionError("계좌가 없으면 holdings까지 가면 안 된다")

        with pytest.raises(BrokerProviderError, match="계좌"):
            self.make(handler).holdings()

    def test_malformed_holdings_response_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                return _token_response()
            if request.url.path == _ACCOUNTS_PATH:
                return _accounts_response()
            return httpx.Response(200, json={"result": {"unexpected": True}})

        with pytest.raises(BrokerProviderError):
            self.make(handler).holdings()

    def test_http_error_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                return _token_response()
            return httpx.Response(500, text="boom")

        with pytest.raises(BrokerProviderError):
            self.make(handler).holdings()

    def test_token_request_failure_raises(self) -> None:
        provider = self.make(lambda _r: httpx.Response(401, json={"error": "invalid_client"}))
        with pytest.raises(BrokerProviderError):
            provider.holdings()

    def test_token_and_account_cached_across_calls(self, tmp_path: Path) -> None:
        calls = {"token": 0, "account": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                calls["token"] += 1
                return _token_response()
            if request.url.path == _ACCOUNTS_PATH:
                calls["account"] += 1
                return _accounts_response()
            return _holdings_response([_SAMSUNG_ITEM])

        token_cache = tmp_path / ".toss_token.json"
        account_cache = tmp_path / ".toss_account.json"
        provider = self.make(
            handler, token_cache_path=token_cache, account_cache_path=account_cache
        )
        provider.holdings()
        provider.holdings()
        assert calls == {"token": 1, "account": 1}
        assert json.loads(account_cache.read_text(encoding="utf-8"))["account_seq"] == 1

    def test_expired_cached_token_is_refreshed(self, tmp_path: Path) -> None:
        cache = tmp_path / ".toss_token.json"
        expired_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        cache.write_text(
            json.dumps({"access_token": "stale", "expires_at": expired_at}), encoding="utf-8"
        )
        token_calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                token_calls["n"] += 1
                return _token_response()
            if request.url.path == _ACCOUNTS_PATH:
                assert request.headers["authorization"] == "Bearer tok-123"
                return _accounts_response()
            return _holdings_response([_SAMSUNG_ITEM])

        self.make(handler, token_cache_path=cache).holdings()
        assert token_calls["n"] == 1

    def test_throttles_between_requests(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == _TOKEN_PATH:
                return _token_response()
            if request.url.path == _ACCOUNTS_PATH:
                return _accounts_response()
            return _holdings_response([_SAMSUNG_ITEM])

        provider = TossHoldingsProvider(
            client_id="id",
            client_secret="secret",
            transport=httpx.MockTransport(handler),
            min_request_interval_seconds=0.05,
        )
        start = time.monotonic()
        provider.holdings()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.1  # 토큰+계좌+시세 3회 호출 중 최소 두번은 대기해야 한다
