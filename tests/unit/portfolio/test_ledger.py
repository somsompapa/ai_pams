"""PositionLedger/CashLedger 테스트.

계약:
- 포지션은 이동평균법. 매수 수수료·세금은 매입원가에 산입한다.
- 매도 실현손익 = 순매도대금(원금-수수료-세금) - 평균원가×매도수량
- 보유량 초과 매도는 거부한다.
- 예수금은 모든 거래의 signed_cash_flow를 통화별로 합산한 결과다.
"""

from datetime import date

import pytest

from pams.portfolio.domain import CashLedger, PositionLedger, Transaction, TransactionType
from pams.shared_kernel.domain import (
    Currency,
    DomainValidationError,
    Money,
    Quantity,
)

D1, D2, D3 = date(2026, 1, 5), date(2026, 2, 3), date(2026, 3, 2)
SAMSUNG = "KRX:005930"


def tx(
    tx_id: str,
    tx_type: TransactionType,
    trade_date: date,
    *,
    asset_id: str | None = SAMSUNG,
    quantity: str | None = None,
    price: str | None = None,
    amount: str | None = None,
    fee: str = "0",
    tax: str = "0",
    currency: Currency = Currency.KRW,
) -> Transaction:
    return Transaction(
        transaction_id=tx_id,
        transaction_type=tx_type,
        trade_date=trade_date,
        asset_id=asset_id,
        quantity=Quantity.of(quantity) if quantity is not None else None,
        price=Money.of(price, currency) if price is not None else None,
        amount=Money.of(amount, currency) if amount is not None else None,
        fee=Money.of(fee, currency),
        tax=Money.of(tax, currency),
    )


class TestPositionLedger:
    def test_single_buy_includes_fee_in_cost_basis(self) -> None:
        positions = PositionLedger().build(
            [tx("t1", TransactionType.BUY, D1, quantity="10", price="70000", fee="105")]
        )
        position = positions[SAMSUNG]
        assert position.quantity == Quantity.of(10)
        assert position.cost_basis == Money.of("700105", Currency.KRW)
        assert position.average_cost == Money.of("70010.5", Currency.KRW)

    def test_multiple_buys_use_moving_average(self) -> None:
        positions = PositionLedger().build(
            [
                tx("t1", TransactionType.BUY, D1, quantity="10", price="70000", fee="105"),
                tx("t2", TransactionType.BUY, D2, quantity="10", price="72000", fee="108"),
            ]
        )
        position = positions[SAMSUNG]
        assert position.quantity == Quantity.of(20)
        assert position.cost_basis == Money.of("1420213", Currency.KRW)

    def test_sell_realizes_pnl_and_reduces_quantity(self) -> None:
        positions = PositionLedger().build(
            [
                tx("t1", TransactionType.BUY, D1, quantity="10", price="70000", fee="105"),
                tx("t2", TransactionType.BUY, D2, quantity="10", price="72000", fee="108"),
                tx(
                    "t3",
                    TransactionType.SELL,
                    D3,
                    quantity="5",
                    price="75000",
                    fee="100",
                    tax="200",
                ),
            ]
        )
        position = positions[SAMSUNG]
        assert position.quantity == Quantity.of(15)
        # 매도 원가 = 1,420,213 × 5/20 = 355,053.25
        assert position.cost_basis == Money.of("1065159.75", Currency.KRW)
        # 실현손익 = (375,000 - 100 - 200) - 355,053.25 = 19,646.75
        assert position.realized_pnl == Money.of("19646.75", Currency.KRW)

    def test_sell_more_than_held_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            PositionLedger().build(
                [
                    tx("t1", TransactionType.BUY, D1, quantity="10", price="70000"),
                    tx("t2", TransactionType.SELL, D2, quantity="11", price="70000"),
                ]
            )

    def test_sell_without_prior_buy_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            PositionLedger().build(
                [tx("t1", TransactionType.SELL, D1, quantity="1", price="70000")]
            )

    def test_transactions_processed_in_date_order(self) -> None:
        """입력 순서가 뒤섞여도 거래일 기준으로 처리한다."""
        positions = PositionLedger().build(
            [
                tx("t2", TransactionType.SELL, D2, quantity="5", price="75000"),
                tx("t1", TransactionType.BUY, D1, quantity="10", price="70000"),
            ]
        )
        assert positions[SAMSUNG].quantity == Quantity.of(10 - 5)

    def test_dividend_does_not_change_position(self) -> None:
        positions = PositionLedger().build(
            [
                tx("t1", TransactionType.BUY, D1, quantity="10", price="70000"),
                tx("t2", TransactionType.DIVIDEND, D2, amount="36100", tax="5558"),
            ]
        )
        assert positions[SAMSUNG].quantity == Quantity.of(10)
        assert positions[SAMSUNG].realized_pnl == Money.zero(Currency.KRW)

    def test_fully_sold_position_is_dropped_but_pnl_survives(self) -> None:
        """전량 매도해도 실현손익은 남는다."""
        positions = PositionLedger().build(
            [
                tx("t1", TransactionType.BUY, D1, quantity="10", price="70000"),
                tx("t2", TransactionType.SELL, D2, quantity="10", price="75000"),
            ]
        )
        position = positions[SAMSUNG]
        assert position.quantity.is_zero
        assert position.realized_pnl == Money.of("50000", Currency.KRW)

    def test_currency_mixing_per_asset_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            PositionLedger().build(
                [
                    tx("t1", TransactionType.BUY, D1, quantity="10", price="70000"),
                    tx(
                        "t2",
                        TransactionType.BUY,
                        D2,
                        quantity="10",
                        price="50",
                        currency=Currency.USD,
                    ),
                ]
            )


class TestCashLedger:
    def test_balances_accumulate_by_currency(self) -> None:
        balances = CashLedger().build(
            [
                tx(
                    "t1",
                    TransactionType.DEPOSIT,
                    D1,
                    asset_id=None,
                    amount="1000000",
                ),
                tx("t2", TransactionType.BUY, D2, quantity="10", price="70000", fee="105"),
                tx(
                    "t3",
                    TransactionType.DEPOSIT,
                    D1,
                    asset_id=None,
                    amount="1000",
                    currency=Currency.USD,
                ),
            ]
        )
        assert balances[Currency.KRW] == Money.of("299895", Currency.KRW)
        assert balances[Currency.USD] == Money.of("1000", Currency.USD)

    def test_dividend_increases_cash(self) -> None:
        balances = CashLedger().build(
            [tx("t1", TransactionType.DIVIDEND, D1, amount="36100", tax="5558")]
        )
        assert balances[Currency.KRW] == Money.of("30542", Currency.KRW)
