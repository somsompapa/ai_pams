"""시장 데이터 공급자 포트(인터페이스).

구체적인 공급자(증권사 API, yfinance, 한국은행 ECOS 등)는 infrastructure에서
이 Protocol을 구현하며, domain/application은 구현체를 알지 못한다(DIP).
따라서 공급자는 언제든 교체 가능하다.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from pams.market_data.domain.models import ExchangeRate, PricePoint
from pams.shared_kernel.domain import Currency


@runtime_checkable
class PriceProvider(Protocol):
    def get_price(self, asset_id: str, as_of: date) -> PricePoint | None:
        """as_of 시점(또는 그 이전 최근 영업일)의 가격. 없으면 None."""
        ...


@runtime_checkable
class ExchangeRateProvider(Protocol):
    def get_rate(self, base: Currency, quote: Currency, as_of: date) -> ExchangeRate | None:
        """as_of 시점의 환율. 없으면 None."""
        ...
