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

from pams.market_data.domain import DailyBar, MarketDataProviderError, Quote
from pams.shared_kernel.domain import Currency, DomainValidationError

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

    def historical_quotes(self, symbol: str, *, years: int = 5) -> tuple[Quote, ...]:
        """PER/PBR 5년밴드 계산 전용 — 월 단위(1mo)로 근사해 조회한다(일 단위 전체
        이력은 결산연도별 매칭에 필요 이상으로 무겁다). 실패해도 예외를 던지지
        않는다 — 빈 튜플이면 밴드 계산만 생략된다(임의 대체 금지)."""
        url = f"{_BASE_URL}/{symbol}"
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = client.get(
                    url,
                    params={"interval": "1mo", "range": f"{years}y"},
                    headers={"User-Agent": _USER_AGENT},
                )
        except httpx.HTTPError:
            return ()
        if response.status_code >= 400:
            return ()
        try:
            result = response.json()["chart"]["result"]
        except (KeyError, TypeError, ValueError):
            return ()
        if not result:
            return ()

        raw_currency = result[0].get("meta", {}).get("currency")
        try:
            currency = Currency(str(raw_currency))
        except ValueError:
            return ()

        timestamps = result[0].get("timestamp") or []
        quote_blocks = result[0].get("indicators", {}).get("quote") or [{}]
        closes = quote_blocks[0].get("close") or []

        points: list[Quote] = []
        for epoch, close in zip(timestamps, closes, strict=False):
            if close is None:
                continue
            try:
                price_date = datetime.fromtimestamp(int(epoch), tz=UTC).date()
                decimal_close = Decimal(str(close))
                points.append(
                    Quote(
                        symbol=symbol, quote_date=price_date, close=decimal_close, currency=currency
                    )
                )
            except (InvalidOperation, ValueError, OSError, DomainValidationError):
                continue
        return tuple(points)

    def recent_daily_bars(self, symbol: str, *, days: int = 20) -> tuple[DailyBar, ...]:
        """유동성 스크리닝(P-5, 최근 20영업일 평균 거래대금) 전용 — 일 단위 종가·
        거래량 조회. 실패해도 예외를 던지지 않는다(빈 튜플이면 유동성 확인만 생략)."""
        url = f"{_BASE_URL}/{symbol}"
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = client.get(
                    url,
                    params={"interval": "1d", "range": "2mo"},
                    headers={"User-Agent": _USER_AGENT},
                )
        except httpx.HTTPError:
            return ()
        if response.status_code >= 400:
            return ()
        try:
            result = response.json()["chart"]["result"]
        except (KeyError, TypeError, ValueError):
            return ()
        if not result:
            return ()

        timestamps = result[0].get("timestamp") or []
        quote_blocks = result[0].get("indicators", {}).get("quote") or [{}]
        closes = quote_blocks[0].get("close") or []
        volumes = quote_blocks[0].get("volume") or []

        bars: list[DailyBar] = []
        for epoch, close, volume in zip(timestamps, closes, volumes, strict=False):
            if close is None or volume is None:
                continue
            try:
                bar_date = datetime.fromtimestamp(int(epoch), tz=UTC).date()
                bars.append(
                    DailyBar(quote_date=bar_date, close=Decimal(str(close)), volume=int(volume))
                )
            except (InvalidOperation, ValueError, OSError):
                continue
        return tuple(bars[-days:])
