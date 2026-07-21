"""한국투자증권(KIS) OpenAPI 시세 어댑터 (QuoteProvider 구현).

국내주식은 6자리 종목코드("005930"), 해외주식은 "거래소코드:종목코드"
("NAS:AAPL") 형식을 심볼로 받는다. OAuth2 접근토큰은 유효기간이 길고
(기본 24시간) 재발급 빈도에 제한이 있으므로 파일에 캐시해 재사용한다.

주의: 여기서는 시세 조회만 다룬다 - 주문 연동은 범위 밖이다
(CLAUDE.md 절대원칙: "자동매매는 목표가 아니다").
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

from pams.market_data.domain import MarketDataProviderError, Quote
from pams.shared_kernel.domain import Currency

_REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
_TOKEN_PATH = "/oauth2/tokenP"
_DOMESTIC_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
_OVERSEAS_PRICE_PATH = "/uapi/overseas-price/v1/quotations/price"
_DOMESTIC_TR_ID = "FHKST01010100"
_OVERSEAS_TR_ID = "HHDFS00000300"

# 해외거래소 코드 → 결제통화. 필요해지면 여기에 추가한다.
_EXCHANGE_CURRENCY: dict[str, Currency] = {
    "NAS": Currency.USD,
    "NYS": Currency.USD,
    "AMS": Currency.USD,
}

_TOKEN_EXPIRY_SAFETY_MARGIN = timedelta(minutes=5)  # 만료 임박 토큰은 미리 갱신


@dataclass(frozen=True, slots=True)
class KisQuoteProvider:
    app_key: str
    app_secret: str
    base_url: str = _REAL_BASE_URL
    timeout_seconds: float = 15.0
    transport: httpx.BaseTransport | None = None  # 테스트 주입용
    token_cache_path: Path | None = None  # None이면 매 호출마다 새 토큰 발급
    min_request_interval_seconds: float = 0.5  # KIS 초당 거래건수 제한 회피용 최소 요청 간격
    _last_request_at: list[float] = field(default_factory=lambda: [0.0], compare=False)

    def _throttle(self) -> None:
        if self.min_request_interval_seconds <= 0:
            return
        wait = self.min_request_interval_seconds - (time.monotonic() - self._last_request_at[0])
        if wait > 0:
            time.sleep(wait)
        self._last_request_at[0] = time.monotonic()

    def latest_quote(self, symbol: str) -> Quote | None:
        exchange, _, code = symbol.partition(":")
        if code:
            return self._overseas_quote(exchange=exchange, code=code, symbol=symbol)
        return self._domestic_quote(code=exchange, symbol=symbol)

    def _domestic_quote(self, *, code: str, symbol: str) -> Quote | None:
        output = self._get(
            _DOMESTIC_PRICE_PATH,
            tr_id=_DOMESTIC_TR_ID,
            params={"fid_cond_mrkt_div_code": "J", "fid_input_iscd": code},
            symbol=symbol,
        )
        price = self._decimal(output.get("stck_prpr"), symbol=symbol)
        if price is None or price == 0:
            return None
        return Quote(symbol=symbol, quote_date=date.today(), close=price, currency=Currency.KRW)

    def _overseas_quote(self, *, exchange: str, code: str, symbol: str) -> Quote | None:
        currency = _EXCHANGE_CURRENCY.get(exchange)
        if currency is None:
            raise MarketDataProviderError(f"{symbol}: 지원하지 않는 해외거래소 코드 {exchange!r}")
        output = self._get(
            _OVERSEAS_PRICE_PATH,
            tr_id=_OVERSEAS_TR_ID,
            params={"AUTH": "", "EXCD": exchange, "SYMB": code},
            symbol=symbol,
        )
        price = self._decimal(output.get("last"), symbol=symbol)
        if price is None or price == 0:
            return None
        return Quote(symbol=symbol, quote_date=date.today(), close=price, currency=currency)

    def _get(self, path: str, *, tr_id: str, params: dict[str, str], symbol: str) -> dict[str, Any]:
        token = self._access_token(symbol=symbol)
        try:
            self._throttle()
            with self._client() as client:
                response = client.get(
                    path,
                    params=params,
                    headers={
                        "content-type": "application/json; charset=utf-8",
                        "authorization": f"Bearer {token}",
                        "appkey": self.app_key,
                        "appsecret": self.app_secret,
                        "tr_id": tr_id,
                    },
                )
        except httpx.HTTPError as error:
            raise MarketDataProviderError(f"{symbol}: 요청 실패: {error}") from error

        if response.status_code >= 400:
            raise MarketDataProviderError(
                f"{symbol}: HTTP {response.status_code}: {response.text[:120]}"
            )
        try:
            body = response.json()
        except ValueError as error:
            raise MarketDataProviderError(f"{symbol}: 예상 밖 응답 형식") from error

        if body.get("rt_cd") != "0":
            raise MarketDataProviderError(f"{symbol}: {body.get('msg1', '알 수 없는 오류')}")
        output = body.get("output")
        if not isinstance(output, dict):
            raise MarketDataProviderError(f"{symbol}: 응답에 output이 없다")
        return output

    def _decimal(self, raw: Any, *, symbol: str) -> Decimal | None:
        if raw is None or str(raw).strip() == "":
            return None
        try:
            return Decimal(str(raw))
        except InvalidOperation:
            raise MarketDataProviderError(f"{symbol}: 가격을 숫자로 해석 불가: {raw!r}") from None

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url, transport=self.transport, timeout=self.timeout_seconds
        )

    def _access_token(self, *, symbol: str) -> str:
        cached = self._read_cached_token()
        if cached is not None:
            return cached
        token, expires_in = self._request_token(symbol=symbol)
        self._write_cached_token(token, expires_in)
        return token

    def _read_cached_token(self) -> str | None:
        if self.token_cache_path is None or not self.token_cache_path.exists():
            return None
        try:
            document = json.loads(self.token_cache_path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(document["expires_at"])
            if expires_at - _TOKEN_EXPIRY_SAFETY_MARGIN <= datetime.now(UTC):
                return None
            token = document["access_token"]
            return str(token)
        except (OSError, ValueError, KeyError):
            return None

    def _write_cached_token(self, token: str, expires_in: int) -> None:
        if self.token_cache_path is None:
            return
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        self.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_cache_path.write_text(
            json.dumps({"access_token": token, "expires_at": expires_at.isoformat()}),
            encoding="utf-8",
        )

    def _request_token(self, *, symbol: str) -> tuple[str, int]:
        try:
            self._throttle()
            with self._client() as client:
                response = client.post(
                    _TOKEN_PATH,
                    json={
                        "grant_type": "client_credentials",
                        "appkey": self.app_key,
                        "appsecret": self.app_secret,
                    },
                )
        except httpx.HTTPError as error:
            raise MarketDataProviderError(f"{symbol}: 토큰 발급 요청 실패: {error}") from error

        if response.status_code >= 400:
            raise MarketDataProviderError(
                f"토큰 발급 실패: HTTP {response.status_code}: {response.text[:120]}"
            )
        try:
            body = response.json()
            return str(body["access_token"]), int(body.get("expires_in", 86400))
        except (ValueError, KeyError, TypeError) as error:
            raise MarketDataProviderError("토큰 발급 응답 형식이 예상과 다르다") from error
