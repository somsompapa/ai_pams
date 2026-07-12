"""거래 기록에서 보유 상태를 파생 계산하는 도메인 서비스.

거래(Transaction)가 유일한 원천이고, 포지션·예수금은 언제나 재계산 가능하다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pams.portfolio.domain.position import Position
from pams.portfolio.domain.transaction import Transaction, TransactionType
from pams.shared_kernel.domain import Currency, DomainValidationError, Money, Quantity


def _in_date_order(transactions: Iterable[Transaction]) -> list[Transaction]:
    return sorted(transactions, key=lambda t: t.trade_date)


class PositionLedger:
    """트레이드(BUY/SELL)를 거래일 순서로 적용해 자산별 Position을 만든다."""

    def build(self, transactions: Iterable[Transaction]) -> dict[str, Position]:
        positions: dict[str, Position] = {}
        for transaction in _in_date_order(transactions):
            if not transaction.transaction_type.is_trade:
                continue
            assert transaction.asset_id is not None  # 트레이드 검증에서 보장
            current = positions.get(transaction.asset_id)
            positions[transaction.asset_id] = self._apply(current, transaction)
        return positions

    def _apply(self, current: Position | None, transaction: Transaction) -> Position:
        assert transaction.asset_id is not None
        assert transaction.quantity is not None and transaction.fee is not None
        assert transaction.tax is not None

        if current is None:
            currency = transaction.currency
            current = Position(
                asset_id=transaction.asset_id,
                quantity=Quantity.of(0),
                cost_basis=Money.zero(currency),
                realized_pnl=Money.zero(currency),
            )
        if transaction.currency is not current.cost_basis.currency:
            raise DomainValidationError(
                f"자산 {transaction.asset_id}의 거래 통화가 일관되지 않다: "
                f"{current.cost_basis.currency} vs {transaction.currency}"
            )

        if transaction.transaction_type is TransactionType.BUY:
            return self._apply_buy(current, transaction)
        return self._apply_sell(current, transaction)

    @staticmethod
    def _apply_buy(current: Position, transaction: Transaction) -> Position:
        assert transaction.quantity is not None
        assert transaction.fee is not None and transaction.tax is not None
        acquisition_cost = transaction.gross_amount + transaction.fee + transaction.tax
        return Position(
            asset_id=current.asset_id,
            quantity=current.quantity + transaction.quantity,
            cost_basis=current.cost_basis + acquisition_cost,
            realized_pnl=current.realized_pnl,
        )

    @staticmethod
    def _apply_sell(current: Position, transaction: Transaction) -> Position:
        assert transaction.quantity is not None
        assert transaction.fee is not None and transaction.tax is not None
        if transaction.quantity > current.quantity:
            raise DomainValidationError(
                f"자산 {current.asset_id}: 보유 수량({current.quantity.value})보다 많은 "
                f"매도({transaction.quantity.value})는 불가능하다"
            )
        cost_removed = Money(
            current.cost_basis.amount * transaction.quantity.value / current.quantity.value,
            current.cost_basis.currency,
        )
        net_proceeds = transaction.gross_amount - transaction.fee - transaction.tax
        return Position(
            asset_id=current.asset_id,
            quantity=current.quantity - transaction.quantity,
            cost_basis=current.cost_basis - cost_removed,
            realized_pnl=current.realized_pnl + (net_proceeds - cost_removed),
        )


class CashLedger:
    """모든 거래의 signed_cash_flow를 통화별로 합산해 예수금 잔고를 만든다."""

    def build(self, transactions: Sequence[Transaction]) -> dict[Currency, Money]:
        balances: dict[Currency, Money] = {}
        for transaction in _in_date_order(transactions):
            flow = transaction.signed_cash_flow
            current = balances.get(flow.currency, Money.zero(flow.currency))
            balances[flow.currency] = current + flow
        return balances
