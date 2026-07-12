"""데모 데이터 소스.

실계좌/실시세 연동(증권사 API 등) 전까지 대시보드를 검증하기 위한
인메모리 구현이다. portfolio 컨텍스트의 포트(TransactionRepository,
AssetCatalog, PriceLookup, FxLookup)를 그대로 구현하므로, 실제 어댑터로
교체해도 서비스 코드는 변하지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from pams.performance.domain import PerformanceHistory, ValuationPoint
from pams.portfolio.domain import Transaction, TransactionType
from pams.risk.domain import ValueSeries
from pams.shared_kernel.domain import Asset, AssetClass, Currency, Money, Quantity

AS_OF = date(2026, 7, 10)
DEMO_VIX = Decimal("24.5")

_ASSETS = {
    asset.asset_id: asset
    for asset in (
        Asset(
            asset_id="KRX:005930",
            name="삼성전자",
            asset_class=AssetClass.DOMESTIC_STOCK,
            currency=Currency.KRW,
            country="KR",
            sector="Information Technology",
        ),
        Asset(
            asset_id="NASDAQ:AAPL",
            name="Apple Inc.",
            asset_class=AssetClass.US_STOCK,
            currency=Currency.USD,
            country="US",
            sector="Information Technology",
        ),
        Asset(
            asset_id="KRX:069500",
            name="KODEX 200",
            asset_class=AssetClass.ETF,
            currency=Currency.KRW,
            country="KR",
            sector=None,
        ),
        Asset(
            asset_id="KRX:114260",
            name="KOSEF 국고채10년",
            asset_class=AssetClass.BOND,
            currency=Currency.KRW,
            country="KR",
            sector=None,
        ),
        Asset(
            asset_id="KRX:GOLD",
            name="KRX 금현물 (1g)",
            asset_class=AssetClass.GOLD,
            currency=Currency.KRW,
            country="KR",
            sector=None,
        ),
    )
}

_PRICES = {
    "KRX:005930": Money.of("75000", Currency.KRW),
    "NASDAQ:AAPL": Money.of("220", Currency.USD),
    "KRX:069500": Money.of("36000", Currency.KRW),
    "KRX:114260": Money.of("101000", Currency.KRW),
    "KRX:GOLD": Money.of("98000", Currency.KRW),
}

_USD_KRW = Decimal("1380")


def _tx(
    tx_id: str,
    tx_type: TransactionType,
    day: str,
    *,
    asset_id: str | None = None,
    quantity: str | None = None,
    price: str | None = None,
    amount: str | None = None,
    fee: str = "0",
    currency: Currency = Currency.KRW,
) -> Transaction:
    return Transaction(
        transaction_id=tx_id,
        transaction_type=tx_type,
        trade_date=date.fromisoformat(day),
        asset_id=asset_id,
        quantity=Quantity.of(quantity) if quantity is not None else None,
        price=Money.of(price, currency) if price is not None else None,
        amount=Money.of(amount, currency) if amount is not None else None,
        fee=Money.of(fee, currency),
    )


_TRANSACTIONS = (
    _tx("d1", TransactionType.DEPOSIT, "2026-01-02", amount="20000000"),
    _tx("d2", TransactionType.DEPOSIT, "2026-01-02", amount="5000", currency=Currency.USD),
    _tx(
        "b1",
        TransactionType.BUY,
        "2026-01-05",
        asset_id="KRX:005930",
        quantity="100",
        price="70000",
        fee="1050",
    ),
    _tx(
        "b2",
        TransactionType.BUY,
        "2026-01-06",
        asset_id="NASDAQ:AAPL",
        quantity="15",
        price="200",
        fee="7.5",
        currency=Currency.USD,
    ),
    _tx(
        "b3",
        TransactionType.BUY,
        "2026-02-03",
        asset_id="KRX:069500",
        quantity="30",
        price="33000",
        fee="150",
    ),
    _tx(
        "b4",
        TransactionType.BUY,
        "2026-02-10",
        asset_id="KRX:114260",
        quantity="20",
        price="100000",
        fee="600",
    ),
    _tx(
        "b5",
        TransactionType.BUY,
        "2026-03-04",
        asset_id="KRX:GOLD",
        quantity="10",
        price="95000",
        fee="2850",
    ),
    _tx(
        "dv1",
        TransactionType.DIVIDEND,
        "2026-04-15",
        asset_id="KRX:005930",
        amount="36100",
    ),
)

# 일별 적재가 붙기 전까지의 데모 가치 이력 (월말 + 최근 2일)
_VALUE_POINTS = (
    ("2026-01-02", "26500000", "0"),
    ("2026-01-30", "26800000", "0"),
    ("2026-02-27", "27000000", "0"),
    ("2026-03-31", "26200000", "0"),
    ("2026-04-30", "27400000", "0"),
    ("2026-05-29", "28100000", "0"),
    ("2026-06-30", "27600000", "0"),
    ("2026-07-09", "27800000", "0"),
    ("2026-07-10", "27900000", "0"),
)
_BENCHMARK_POINTS = (
    ("2026-01-02", "2500", "0"),
    ("2026-01-30", "2530", "0"),
    ("2026-02-27", "2550", "0"),
    ("2026-03-31", "2480", "0"),
    ("2026-04-30", "2600", "0"),
    ("2026-05-29", "2650", "0"),
    ("2026-06-30", "2620", "0"),
    ("2026-07-09", "2660", "0"),
    ("2026-07-10", "2670", "0"),
)


class DemoTransactionRepository:
    def transactions_until(self, as_of: date) -> Sequence[Transaction]:
        return [t for t in _TRANSACTIONS if t.trade_date <= as_of]


class DemoAssetCatalog:
    def get(self, asset_id: str) -> Asset | None:
        return _ASSETS.get(asset_id)


class DemoPriceLookup:
    def price_of(self, asset_id: str, as_of: date) -> Money | None:
        return _PRICES.get(asset_id)


class DemoFxLookup:
    def rate_to(self, currency: Currency, base: Currency, as_of: date) -> Decimal | None:
        if (currency, base) == (Currency.USD, Currency.KRW):
            return _USD_KRW
        return None


def _history(points: tuple[tuple[str, str, str], ...]) -> PerformanceHistory:
    return PerformanceHistory.from_points(
        [
            ValuationPoint(
                point_date=date.fromisoformat(day), value=Decimal(value), net_flow=Decimal(flow)
            )
            for day, value, flow in points
        ]
    )


def demo_performance_history() -> PerformanceHistory:
    return _history(_VALUE_POINTS)


def demo_benchmark_history() -> PerformanceHistory:
    return _history(_BENCHMARK_POINTS)


def demo_value_series() -> ValueSeries:
    return ValueSeries.from_pairs(
        [(date.fromisoformat(day), Decimal(value)) for day, value, _flow in _VALUE_POINTS]
    )


def demo_benchmark_series() -> ValueSeries:
    return ValueSeries.from_pairs(
        [(date.fromisoformat(day), Decimal(value)) for day, value, _flow in _BENCHMARK_POINTS]
    )
