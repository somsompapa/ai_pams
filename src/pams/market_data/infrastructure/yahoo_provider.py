"""Yahoo Finance 시세 어댑터 (QuoteProvider 구현).

Yahoo의 공개 chart API(키 불필요)를 호출한다. 한국주식(005930.KS/.KQ),
미국주식(AAPL), 환율(KRW=X), 지수/VIX(^VIX) 등을 심볼로 조회한다.

주의: 비공식 API이므로 언제든 바뀔 수 있다. 포트(QuoteProvider) 뒤에 있으므로
다른 공급자로 교체 가능하다. 종가는 str을 거쳐 Decimal로 변환해 float 오차를 막는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx

from pams.market_data.domain import MarketDataProviderError, Quote
from pams.shared_kernel.domain import Currency

_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
_USER_AGENT = "Mozilla/5.0 (compatible; PAMS/0.1)"


@dataclass(frozen=True, slots=True)
class YahooQuoteProvider:
    timeout_seconds: float = 15.0
    transport: httpx.BaseTransport | None = None  # 테스트 주입용

    def latest_quote(self, symbol: str) -> Quote | None:
        url = f"{_BASE_URL}/{symbol}"
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = client.get(
                    url,
                    params={"interval": "1d", "range": "5d"},
                    headers={"User-Agent": _USER_AGENT},
                )
        except httpx.HTTPError as error:
            raise MarketDataProviderError(f"{symbol}: 요청 실패: {error}") from error

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise MarketDataProviderError(
                f"{symbol}: HTTP {response.status_code}: {response.text[:120]}"
            )

        try:
            result = response.json()["chart"]["result"]
        except (KeyError, TypeError, ValueError) as error:
            raise MarketDataProviderError(f"{symbol}: 예상 밖 응답 형식") from error
        if not result:
            return None

        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        raw_currency = meta.get("currency")
        if price is None or raw_currency is None:
            raise MarketDataProviderError(f"{symbol}: 응답에 가격/통화가 없다")

        try:
            currency = Currency(str(raw_currency))
        except ValueError:
            raise MarketDataProviderError(
                f"{symbol}: 지원하지 않는 통화 {raw_currency!r}"
            ) from None
        try:
            close = Decimal(str(price))
        except InvalidOperation:
            raise MarketDataProviderError(f"{symbol}: 가격을 숫자로 해석 불가: {price!r}") from None

        epoch = meta.get("regularMarketTime")
        quote_date = (
            datetime.fromtimestamp(int(epoch), tz=UTC).date()
            if epoch is not None
            else datetime.now(UTC).date()
        )
        try:
            return Quote(symbol=symbol, quote_date=quote_date, close=close, currency=currency)
        except Exception as error:  # 도메인 검증 실패(음수 등)
            raise MarketDataProviderError(f"{symbol}: {error}") from error
