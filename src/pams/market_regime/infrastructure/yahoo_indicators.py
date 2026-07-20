"""VIX·KOSPI 등락률 자동조회 (market_regime 전용). Yahoo의 공개 chart API를 그대로
쓴다(market_data.infrastructure.yahoo_provider와 같은 API, 별도 어댑터로 분리한
이유: 여긴 "최신 종가" 하나가 아니라 "전일 대비 등락률" 계산에 필요한 2개 종가가
필요해서 응답 파싱 범위가 다르다).

나머지 3개 지표(10년물·S&P500 PER·KOSPI 외국인수급)는 rulebook 자체가 "자동조회
안 함"(market_analysis_rules.md 4-1)으로 명시하므로 여기서 다루지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from pams.market_regime.domain.regime import MarketRegimeProviderError

_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
_USER_AGENT = "Mozilla/5.0 (compatible; PAMS/0.1)"


@dataclass(frozen=True, slots=True)
class YahooMarketRegimeIndicatorProvider:
    timeout_seconds: float = 15.0
    transport: httpx.BaseTransport | None = None  # 테스트 주입용

    def _fetch_recent_closes(self, symbol: str) -> tuple[Decimal, ...]:
        """최근 며칠간 종가(오름차순, 과거→최신). 최소 2개 있어야 등락률을 계산할 수 있다."""
        url = f"{_BASE_URL}/{symbol}"
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = client.get(
                    url,
                    params={"interval": "1d", "range": "5d"},
                    headers={"User-Agent": _USER_AGENT},
                )
        except httpx.HTTPError as error:
            raise MarketRegimeProviderError(f"{symbol}: 요청 실패: {error}") from error

        if response.status_code >= 400:
            raise MarketRegimeProviderError(
                f"{symbol}: HTTP {response.status_code}: {response.text[:120]}"
            )
        try:
            result = response.json()["chart"]["result"]
        except (KeyError, TypeError, ValueError) as error:
            raise MarketRegimeProviderError(f"{symbol}: 예상 밖 응답 형식") from error
        if not result:
            raise MarketRegimeProviderError(f"{symbol}: 조회 결과 없음")

        try:
            raw_closes = result[0]["indicators"]["quote"][0]["close"]
        except (KeyError, TypeError, IndexError) as error:
            raise MarketRegimeProviderError(f"{symbol}: 종가 배열을 찾지 못함") from error

        closes: list[Decimal] = []
        for value in raw_closes:
            if value is None:
                continue
            try:
                closes.append(Decimal(str(value)))
            except InvalidOperation:
                continue
        return tuple(closes)

    def fetch_vix(self) -> Decimal:
        """^VIX 최신 종가."""
        closes = self._fetch_recent_closes("^VIX")
        if not closes:
            raise MarketRegimeProviderError("^VIX: 유효한 종가가 없음")
        return closes[-1]

    def fetch_kospi_change_pct(self) -> Decimal:
        """KOSPI(^KS11) 전일 대비 등락률(%). 예: -5.3 => -5.3%."""
        closes = self._fetch_recent_closes("^KS11")
        if len(closes) < 2:
            raise MarketRegimeProviderError(
                "^KS11: 등락률 계산에 필요한 2개 이상의 종가를 확보하지 못함"
            )
        previous, latest = closes[-2], closes[-1]
        if previous == 0:
            raise MarketRegimeProviderError("^KS11: 전일 종가가 0 — 등락률 계산 불가")
        return (latest - previous) / previous * Decimal(100)
