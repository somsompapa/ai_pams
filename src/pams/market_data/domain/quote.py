"""시세 자동수집 도메인: Quote, QuoteProvider 포트, SymbolMap.

외부 시세 공급자(Yahoo Finance 등)는 QuoteProvider 포트로 추상화되며
infrastructure에서 구현한다. 우리 자산 식별자(asset_id)와 외부 심볼의 매핑은
설정 파일(config/market/symbols.yaml)로 관리한다 - 코드 하드코딩 금지.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from pams.shared_kernel.domain import Currency, DomainError, DomainValidationError


class MarketDataProviderError(DomainError):
    """외부 시세 공급자 호출/응답 처리에 실패했다."""


@dataclass(frozen=True, slots=True)
class Quote:
    """외부 공급자가 반환한 특정 심볼의 최신 종가."""

    symbol: str
    quote_date: date
    close: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if not isinstance(self.close, Decimal):
            raise DomainValidationError(f"close는 Decimal이어야 한다 (float 금지): {self.close!r}")
        if self.close <= 0:
            raise DomainValidationError(f"종가는 양수여야 한다: {self.close}")


@runtime_checkable
class QuoteProvider(Protocol):
    def latest_quote(self, symbol: str) -> Quote | None:
        """심볼의 최신 종가. 심볼을 찾지 못하면 None, 공급자 오류는 예외."""
        ...


@dataclass(frozen=True, slots=True)
class SymbolMap:
    """asset_id/통화쌍/지표 → 외부 심볼 매핑. config/market/symbols.yaml에서 로드."""

    prices: Mapping[str, str] = field(default_factory=dict)  # asset_id → symbol
    fx: Mapping[tuple[Currency, Currency], str] = field(
        default_factory=dict
    )  # (base,quote) → symbol
    indicators: Mapping[str, str] = field(default_factory=dict)  # metric 이름 → symbol

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> SymbolMap:
        raw_prices = document.get("prices") or {}
        raw_fx = document.get("fx") or {}
        raw_indicators = document.get("indicators") or {}

        fx: dict[tuple[Currency, Currency], str] = {}
        for pair, symbol in raw_fx.items():
            base, sep, quote = str(pair).partition("/")
            if not sep:
                raise DomainValidationError(f"fx 통화쌍은 'BASE/QUOTE' 형식이어야 한다: {pair!r}")
            try:
                fx[(Currency(base.strip()), Currency(quote.strip()))] = str(symbol)
            except ValueError:
                raise DomainValidationError(f"fx 통화쌍에 알 수 없는 통화: {pair!r}") from None

        return cls(
            prices={str(k): str(v) for k, v in raw_prices.items()},
            fx=fx,
            indicators={str(k): str(v) for k, v in raw_indicators.items()},
        )
