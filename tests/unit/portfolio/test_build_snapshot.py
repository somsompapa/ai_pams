"""BuildPortfolioSnapshot 유스케이스 테스트.

거래 저장소/자산 카탈로그/시세/환율 4개 포트를 인메모리 페이크로 채워
전체 흐름(거래 → 포지션 → 평가 → 지표)을 검증한다.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest

from pams.portfolio.application import BuildPortfolioSnapshot
from pams.portfolio.domain import (
    AssetCatalog,
    FxLookup,
    MissingMarketDataError,
    PriceLookup,
    Transaction,
    TransactionRepository,
    TransactionType,
)
from pams.shared_kernel.domain import Asset, AssetClass, Currency, Money, Quantity

AS_OF = date(2026, 7, 10)

SAMSUNG = Asset(
    asset_id="KRX:005930",
    name="삼성전자",
    asset_class=AssetClass.DOMESTIC_STOCK,
    currency=Currency.KRW,
    country="KR",
    sector="Information Technology",
)

TRANSACTIONS = [
    Transaction(
        transaction_id="t1",
        transaction_type=TransactionType.DEPOSIT,
        trade_date=date(2026, 1, 2),
        amount=Money.of("1000000", Currency.KRW),
    ),
    Transaction(
        transaction_id="t2",
        transaction_type=TransactionType.BUY,
        trade_date=date(2026, 1, 5),
        asset_id=SAMSUNG.asset_id,
        quantity=Quantity.of(10),
        price=Money.of("70000", Currency.KRW),
    ),
    Transaction(
        transaction_id="t3-future",
        transaction_type=TransactionType.BUY,
        trade_date=date(2027, 1, 1),  # as_of 이후 - 제외되어야 한다
        asset_id=SAMSUNG.asset_id,
        quantity=Quantity.of(100),
        price=Money.of("70000", Currency.KRW),
    ),
]


class InMemoryTransactions:
    def __init__(self, transactions: Sequence[Transaction]) -> None:
        self._transactions = list(transactions)

    def transactions_until(self, as_of: date) -> Sequence[Transaction]:
        return [t for t in self._transactions if t.trade_date <= as_of]


class InMemoryAssets:
    def get(self, asset_id: str) -> Asset | None:
        return {SAMSUNG.asset_id: SAMSUNG}.get(asset_id)


class InMemoryPrices:
    def __init__(self, prices: dict[str, Money]) -> None:
        self._prices = prices

    def price_of(self, asset_id: str, as_of: date) -> Money | None:
        return self._prices.get(asset_id)


class InMemoryFx:
    def rate_to(self, currency: Currency, base: Currency, as_of: date) -> Decimal | None:
        return Decimal("1300") if (currency, base) == (Currency.USD, Currency.KRW) else None


def make_use_case(prices: dict[str, Money] | None = None) -> BuildPortfolioSnapshot:
    return BuildPortfolioSnapshot(
        transactions=InMemoryTransactions(TRANSACTIONS),
        assets=InMemoryAssets(),
        prices=InMemoryPrices(
            prices if prices is not None else {SAMSUNG.asset_id: Money.of("75000", Currency.KRW)}
        ),
        fx=InMemoryFx(),
    )


class TestBuildPortfolioSnapshot:
    def test_fakes_satisfy_ports(self) -> None:
        assert isinstance(InMemoryTransactions([]), TransactionRepository)
        assert isinstance(InMemoryAssets(), AssetCatalog)
        assert isinstance(InMemoryPrices({}), PriceLookup)
        assert isinstance(InMemoryFx(), FxLookup)

    def test_end_to_end_snapshot(self) -> None:
        snapshot = make_use_case().execute(as_of=AS_OF, base_currency=Currency.KRW)
        # 예수금 1,000,000 - 700,000 = 300,000 / 삼성 10주 × 75,000 = 750,000
        assert snapshot.total_value == Money.of("1050000", Currency.KRW)
        assert snapshot.total_unrealized_pnl == Money.of("50000", Currency.KRW)
        assert snapshot.metrics()["equity_weight"] == Decimal("750000") / Decimal("1050000")

    def test_future_transactions_excluded(self) -> None:
        """as_of 이후 거래(t3-future, 100주 매수)는 스냅샷에 반영되지 않는다."""
        snapshot = make_use_case().execute(as_of=AS_OF, base_currency=Currency.KRW)
        by_id = {v.asset.asset_id: v for v in snapshot.valuations}
        assert by_id[SAMSUNG.asset_id].position.quantity == Quantity.of(10)

    def test_missing_price_surfaces_as_domain_error(self) -> None:
        with pytest.raises(MissingMarketDataError):
            make_use_case(prices={}).execute(as_of=AS_OF, base_currency=Currency.KRW)
