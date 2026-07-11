"""portfolio 컨텍스트가 필요로 하는 포트.

시세/환율은 market_data 컨텍스트가 소유하지만, 컨텍스트 간 domain 직접 의존을
막기 위해 portfolio는 자신이 필요한 형태의 조회 인터페이스를 스스로 정의한다.
interfaces 계층이 market_data 유스케이스를 이 포트에 맞게 어댑트한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pams.portfolio.domain.transaction import Transaction
from pams.shared_kernel.domain import Asset, Currency, Money


@runtime_checkable
class TransactionRepository(Protocol):
    def transactions_until(self, as_of: date) -> Sequence[Transaction]:
        """as_of(포함) 이전의 모든 거래."""
        ...


@runtime_checkable
class AssetCatalog(Protocol):
    def get(self, asset_id: str) -> Asset | None: ...


@runtime_checkable
class PriceLookup(Protocol):
    def price_of(self, asset_id: str, as_of: date) -> Money | None:
        """as_of 시점(또는 직전 영업일)의 가격. 자산 통화 기준."""
        ...


@runtime_checkable
class FxLookup(Protocol):
    def rate_to(self, currency: Currency, base: Currency, as_of: date) -> Decimal | None:
        """1 currency = ? base. 없으면 None."""
        ...
