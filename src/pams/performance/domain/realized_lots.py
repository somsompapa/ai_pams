"""거래 기록(Transaction)을 FIFO로 랏(lot) 매칭해 실현 CAGR·MDD를 계산한다.

ai_stock 프로젝트 journal.py(v1.5.4) match_fifo_lots()/compute_realized_performance()의
검증된 로직을 이식한다 — 다만 ai_stock은 별도 저널 텍스트 기록에 의존했지만, 여기서는
portfolio 컨텍스트가 이미 갖고 있는 권위 있는 거래 원장(Transaction)을 그대로 쓴다
(같은 데이터를 두 곳에 중복 입력하지 않는다).

PositionLedger(portfolio.domain.ledger)의 가중평균 원가법과는 별개의 관점이다 — 그건
실시간 보유원가/실현손익 회계용이고, 이건 "청산된 각 랏이 몇 년 보유돼 얼마의 CAGR을
냈는가"를 보기 위한 사후 성과분석용이다. 서로 다른 목적이라 병존한다.

CAGR/MDD는 risk.domain.measures의 cagr()/max_drawdown()을 재사용한다(중복 구현 금지,
CLAUDE.md 원칙 #7) — 둘 다 ValueSeries(날짜, Decimal) 기반이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from pams.portfolio.domain.transaction import Transaction, TransactionType
from pams.risk.domain.measures import cagr, max_drawdown
from pams.risk.domain.series import InsufficientDataError, ValueSeries
from pams.shared_kernel.domain import Currency, DomainValidationError

_DAYS_PER_YEAR = Decimal(365)


@dataclass(frozen=True, slots=True)
class ClosedLot:
    asset_id: str
    currency: Currency
    quantity: Decimal
    unit_cost: Decimal  # 매수 시 (금액+수수료+세금)/수량 — 전량원가 기준
    unit_proceeds: Decimal  # 매도 시 (금액-수수료-세금)/수량 — 순실수령 기준
    buy_date: date
    sell_date: date

    @property
    def cost(self) -> Decimal:
        return self.quantity * self.unit_cost

    @property
    def proceeds(self) -> Decimal:
        return self.quantity * self.unit_proceeds

    @property
    def realized_pnl(self) -> Decimal:
        return self.proceeds - self.cost


@dataclass(frozen=True, slots=True)
class OpenLot:
    asset_id: str
    currency: Currency
    quantity: Decimal
    unit_cost: Decimal
    buy_date: date


@dataclass(frozen=True, slots=True)
class SkippedTransaction:
    transaction_id: str
    asset_id: str
    trade_date: date
    reason: str


@dataclass(frozen=True, slots=True)
class FifoMatchResult:
    closed_lots: tuple[ClosedLot, ...]
    open_lots: tuple[OpenLot, ...]
    skipped: tuple[SkippedTransaction, ...]


@dataclass()
class _QueuedLot:
    quantity: Decimal
    unit_cost: Decimal
    buy_date: date


def match_fifo_lots(transactions: Sequence[Transaction]) -> FifoMatchResult:
    """자산별로 BUY를 큐에 쌓고 SELL이 오면 FIFO로 소진한다.

    매도 수량이 보유 랏 합계를 초과하면(거래 기록 누락 가능성) 해당 매도는 통째로
    건너뛰고 skipped에 사유와 함께 남긴다(임의 매칭 금지) — 이미 부분 소진된 랏이
    있었더라도 이 매도 건 자체는 무효로 취급해 되돌린다.
    """
    by_asset: dict[str, list[Transaction]] = {}
    for tx in transactions:
        if tx.transaction_type.is_trade:
            assert tx.asset_id is not None
            by_asset.setdefault(tx.asset_id, []).append(tx)

    closed: list[ClosedLot] = []
    skipped: list[SkippedTransaction] = []
    open_lots: list[OpenLot] = []

    for asset_id, txs in by_asset.items():
        queue: list[_QueuedLot] = []
        for tx in sorted(txs, key=lambda t: t.trade_date):
            assert tx.quantity is not None and tx.price is not None
            assert tx.fee is not None and tx.tax is not None
            qty = tx.quantity.value
            if tx.transaction_type is TransactionType.BUY:
                gross = tx.price.amount * qty
                unit_cost = (gross + tx.fee.amount + tx.tax.amount) / qty
                queue.append(_QueuedLot(quantity=qty, unit_cost=unit_cost, buy_date=tx.trade_date))
                continue

            # SELL
            gross = tx.price.amount * qty
            unit_proceeds = (gross - tx.fee.amount - tx.tax.amount) / qty
            available = sum((lot.quantity for lot in queue), Decimal(0))
            if qty > available:
                skipped.append(
                    SkippedTransaction(
                        transaction_id=tx.transaction_id,
                        asset_id=asset_id,
                        trade_date=tx.trade_date,
                        reason=(
                            f"매도 수량({qty})이 보유 랏 합계({available})보다 많음 — "
                            "거래 기록 누락/오류 가능성(판단 보류, 임의 매칭 안 함)"
                        ),
                    )
                )
                continue

            remaining = qty
            while remaining > 0 and queue:
                lot = queue[0]
                matched = min(remaining, lot.quantity)
                closed.append(
                    ClosedLot(
                        asset_id=asset_id,
                        currency=tx.currency,
                        quantity=matched,
                        unit_cost=lot.unit_cost,
                        unit_proceeds=unit_proceeds,
                        buy_date=lot.buy_date,
                        sell_date=tx.trade_date,
                    )
                )
                lot.quantity -= matched
                remaining -= matched
                if lot.quantity <= 0:
                    queue.pop(0)

        for lot in queue:
            open_lots.append(
                OpenLot(
                    asset_id=asset_id,
                    currency=txs[0].currency,
                    quantity=lot.quantity,
                    unit_cost=lot.unit_cost,
                    buy_date=lot.buy_date,
                )
            )

    return FifoMatchResult(
        closed_lots=tuple(closed), open_lots=tuple(open_lots), skipped=tuple(skipped)
    )


@dataclass(frozen=True, slots=True)
class RealizedPerformanceByCurrency:
    currency: Currency
    n_closed_lots: int
    total_cost: Decimal
    total_proceeds: Decimal
    total_realized_pnl: Decimal
    realized_return_pct: Decimal | None  # total_cost가 0이면 None
    capital_weighted_cagr: Decimal | None  # 원금(cost) 가중평균, 계산 불가 랏은 제외
    realized_pnl_drawdown_approx: Decimal | None  # 근사 MDD, 아래 note 참조


@dataclass(frozen=True, slots=True)
class RealizedPerformanceReport:
    by_currency: tuple[RealizedPerformanceByCurrency, ...]
    n_open_lots: int
    skipped: tuple[SkippedTransaction, ...]
    note: str = (
        "MDD는 청산시점 누적 실현손익 기준 근사치다 — 거래와 거래 사이의 미실현 평가변동"
        "(보유 중 가격 등락)은 반영되지 않는다. 진짜 일별 MDD가 아니라 "
        "'실현손익만 놓고 봤을 때 원금 대비 최대 낙폭'으로 해석할 것."
    )


def _weighted_cagr(lots: Sequence[ClosedLot]) -> Decimal | None:
    numerator = Decimal(0)
    denominator = Decimal(0)
    for lot in lots:
        try:
            series = ValueSeries.from_pairs(
                [(lot.buy_date, lot.unit_cost), (lot.sell_date, lot.unit_proceeds)]
            )
            lot_cagr = cagr(series)
        except (DomainValidationError, InsufficientDataError):
            continue  # 매수/매도가 같은 날이거나 원가가 0 이하 — 이 랏은 CAGR 계산 제외
        numerator += lot_cagr * lot.cost
        denominator += lot.cost
    if denominator <= 0:
        return None
    return numerator / denominator


def _realized_pnl_drawdown(lots: Sequence[ClosedLot], total_cost: Decimal) -> Decimal | None:
    if total_cost <= 0:
        return None
    baseline_date = min(lot.buy_date for lot in lots) - timedelta(days=1)

    by_date: dict[date, Decimal] = {}
    for lot in sorted(lots, key=lambda x: x.sell_date):
        by_date[lot.sell_date] = by_date.get(lot.sell_date, Decimal(0)) + lot.realized_pnl

    running = total_cost
    pairs = [(baseline_date, total_cost)]
    for sell_date in sorted(by_date):
        running += by_date[sell_date]
        pairs.append((sell_date, running))

    try:
        series = ValueSeries.from_pairs(pairs)
    except DomainValidationError:
        # 누적 평가액이 0 이하로 내려가면(전액 손실 초과) 근사 MDD를 정의하지 않는다.
        return None
    return max_drawdown(series)


def compute_realized_performance(transactions: Sequence[Transaction]) -> RealizedPerformanceReport:
    match = match_fifo_lots(transactions)
    by_ccy: dict[Currency, list[ClosedLot]] = {}
    for lot in match.closed_lots:
        by_ccy.setdefault(lot.currency, []).append(lot)

    results: list[RealizedPerformanceByCurrency] = []
    for currency, lots in by_ccy.items():
        total_cost = sum((lot.cost for lot in lots), Decimal(0))
        total_proceeds = sum((lot.proceeds for lot in lots), Decimal(0))
        total_pnl = sum((lot.realized_pnl for lot in lots), Decimal(0))
        results.append(
            RealizedPerformanceByCurrency(
                currency=currency,
                n_closed_lots=len(lots),
                total_cost=total_cost,
                total_proceeds=total_proceeds,
                total_realized_pnl=total_pnl,
                realized_return_pct=(
                    (total_pnl / total_cost * Decimal(100)) if total_cost > 0 else None
                ),
                capital_weighted_cagr=_weighted_cagr(lots),
                realized_pnl_drawdown_approx=_realized_pnl_drawdown(lots, total_cost),
            )
        )

    return RealizedPerformanceReport(
        by_currency=tuple(results),
        n_open_lots=len(match.open_lots),
        skipped=match.skipped,
    )
