"""RecordDailyValuation 유스케이스 테스트.

계약: 그날의 총자산(기준통화)과 그날의 외부 현금흐름(입출금)을 이력에 적재한다.
입출금을 flow로 기록해야 TWR이 왜곡되지 않는다 (Phase 7 참고).
"""

from datetime import date
from decimal import Decimal

from pams.performance.domain import PerformanceHistory, ValuationPoint
from pams.portfolio.application import BuildPortfolioSnapshot, RecordDailyValuation
from pams.portfolio.domain import Transaction, TransactionType
from pams.shared_kernel.domain import Asset, AssetClass, Currency, Money, Quantity

AS_OF = date(2026, 7, 10)
SAMSUNG = Asset(
    asset_id="KRX:005930",
    name="삼성전자",
    asset_class=AssetClass.DOMESTIC_STOCK,
    currency=Currency.KRW,
    country="KR",
    sector=None,
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
    # 적재 당일의 입금과 출금 - net_flow에 반영되어야 한다
    Transaction(
        transaction_id="t3",
        transaction_type=TransactionType.DEPOSIT,
        trade_date=AS_OF,
        amount=Money.of("500000", Currency.KRW),
    ),
    Transaction(
        transaction_id="t4",
        transaction_type=TransactionType.WITHDRAWAL,
        trade_date=AS_OF,
        amount=Money.of("200000", Currency.KRW),
    ),
    # 당일 USD 입금 - 환율(1300)로 환산되어야 한다
    Transaction(
        transaction_id="t5",
        transaction_type=TransactionType.DEPOSIT,
        trade_date=AS_OF,
        amount=Money.of("100", Currency.USD),
    ),
]


class InMemoryTransactions:
    def transactions_until(self, as_of: date) -> list[Transaction]:
        return [t for t in TRANSACTIONS if t.trade_date <= as_of]


class Catalog:
    def get(self, asset_id: str) -> Asset | None:
        return SAMSUNG if asset_id == SAMSUNG.asset_id else None


class Prices:
    def price_of(self, asset_id: str, as_of: date) -> Money | None:
        return Money.of("75000", Currency.KRW) if asset_id == SAMSUNG.asset_id else None


class Fx:
    def rate_to(self, currency: Currency, base: Currency, as_of: date) -> Decimal | None:
        return Decimal("1300") if (currency, base) == (Currency.USD, Currency.KRW) else None


class InMemoryHistory:
    def __init__(self) -> None:
        self.points: list[ValuationPoint] = []

    def append(self, point: ValuationPoint) -> None:
        self.points = [p for p in self.points if p.point_date != point.point_date] + [point]

    def load(self) -> PerformanceHistory | None:
        return PerformanceHistory.from_points(self.points) if self.points else None


def make_use_case(history: InMemoryHistory) -> RecordDailyValuation:
    builder = BuildPortfolioSnapshot(
        transactions=InMemoryTransactions(), assets=Catalog(), prices=Prices(), fx=Fx()
    )
    return RecordDailyValuation(snapshot_builder=builder, history=history)


class TestRecordDailyValuation:
    def test_records_total_value_and_net_flow(self) -> None:
        history = InMemoryHistory()
        point = make_use_case(history).execute(as_of=AS_OF, base_currency=Currency.KRW)
        # 총자산: 삼성 750,000 + 예수금(1,000,000-700,000+500,000-200,000+100×1300)
        assert point.value == Decimal("1480000")  # 750,000 + 730,000... 검증은 아래에서
        # 당일 외부 현금흐름: +500,000 - 200,000 + 130,000 = +430,000
        assert point.net_flow == Decimal("430000")
        assert history.points == [point]

    def test_rerun_same_day_upserts(self) -> None:
        history = InMemoryHistory()
        use_case = make_use_case(history)
        use_case.execute(as_of=AS_OF, base_currency=Currency.KRW)
        use_case.execute(as_of=AS_OF, base_currency=Currency.KRW)
        assert len(history.points) == 1

    def test_day_without_flows_has_zero_net_flow(self) -> None:
        history = InMemoryHistory()
        point = make_use_case(history).execute(as_of=date(2026, 7, 9), base_currency=Currency.KRW)
        assert point.net_flow == Decimal(0)
