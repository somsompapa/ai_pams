"""유스케이스: 오늘의 포트폴리오 총자산을 가치 이력에 적재한다.

매일 실행하면(cron 또는 `make snapshot`) 리스크/성과 엔진의 시계열이 쌓인다.
당일 입출금은 net_flow로 함께 기록해 TWR 왜곡을 막는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pams.performance.domain import ValuationPoint, ValueHistoryRepository
from pams.portfolio.application.build_snapshot import BuildPortfolioSnapshot
from pams.portfolio.domain import MissingMarketDataError, TransactionType
from pams.shared_kernel.domain import Currency

_FLOW_TYPES = frozenset({TransactionType.DEPOSIT, TransactionType.WITHDRAWAL})


@dataclass(frozen=True, slots=True)
class RecordDailyValuation:
    snapshot_builder: BuildPortfolioSnapshot
    history: ValueHistoryRepository

    def execute(self, *, as_of: date, base_currency: Currency) -> ValuationPoint:
        snapshot = self.snapshot_builder.execute(as_of=as_of, base_currency=base_currency)
        point = ValuationPoint(
            point_date=as_of,
            value=snapshot.total_value.amount,
            net_flow=self._net_external_flow(as_of, base_currency),
        )
        self.history.append(point)
        return point

    def _net_external_flow(self, as_of: date, base_currency: Currency) -> Decimal:
        """당일 입출금(외부 현금흐름)의 기준통화 합계. 입금 +, 출금 -."""
        total = Decimal(0)
        for transaction in self.snapshot_builder.transactions.transactions_until(as_of):
            if transaction.trade_date != as_of:
                continue
            if transaction.transaction_type not in _FLOW_TYPES:
                continue
            flow = transaction.signed_cash_flow
            if flow.currency is base_currency:
                total += flow.amount
                continue
            rate = self.snapshot_builder.fx.rate_to(flow.currency, base_currency, as_of)
            if rate is None:
                raise MissingMarketDataError(
                    f"환율이 없어 당일 입출금을 환산할 수 없다: {flow.currency}→{base_currency}"
                )
            total += flow.amount * rate
        return total
