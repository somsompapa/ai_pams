"""유스케이스: 심볼 맵의 모든 항목을 조회해 시세/환율/지표를 수집한다.

개별 심볼 실패(심볼 없음, 일시적 공급자 오류)가 전체 수집을 중단시키지 않도록
오류를 모아서 반환한다 - 하나가 실패해도 나머지는 갱신된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pams.market_data.domain import (
    MarketDataProviderError,
    Quote,
    QuoteProvider,
    SymbolMap,
)
from pams.shared_kernel.domain import Currency


@dataclass(frozen=True, slots=True)
class FetchResult:
    prices: dict[str, Quote]  # asset_id → Quote
    fx: dict[tuple[Currency, Currency], Decimal]  # (base,quote) → rate
    indicators: dict[str, Decimal]  # metric 이름 → 값
    errors: list[str]  # 수집 실패한 항목 (사람이 읽는 메시지)

    @property
    def fetched_count(self) -> int:
        return len(self.prices) + len(self.fx) + len(self.indicators)


@dataclass(frozen=True, slots=True)
class FetchMarketData:
    provider: QuoteProvider

    def execute(self, *, symbols: SymbolMap) -> FetchResult:
        prices: dict[str, Quote] = {}
        fx: dict[tuple[Currency, Currency], Decimal] = {}
        indicators: dict[str, Decimal] = {}
        errors: list[str] = []

        for asset_id, symbol in symbols.prices.items():
            quote = self._quote(symbol, errors, label=asset_id)
            if quote is not None:
                prices[asset_id] = quote

        for pair, symbol in symbols.fx.items():
            quote = self._quote(symbol, errors, label=f"{pair[0]}/{pair[1]}")
            if quote is not None:
                fx[pair] = quote.close

        for name, symbol in symbols.indicators.items():
            quote = self._quote(symbol, errors, label=name)
            if quote is not None:
                indicators[name] = quote.close

        return FetchResult(prices=prices, fx=fx, indicators=indicators, errors=errors)

    def _quote(self, symbol: str, errors: list[str], *, label: str) -> Quote | None:
        try:
            quote = self.provider.latest_quote(symbol)
        except MarketDataProviderError as error:
            errors.append(f"{label} ({symbol}): {error}")
            return None
        if quote is None:
            errors.append(f"{label} ({symbol}): 심볼을 찾을 수 없다")
        return quote
