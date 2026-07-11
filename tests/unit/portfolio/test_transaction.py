"""Transaction(거래) 도메인 모델 테스트.

거래는 실현손익/예수금/보유수량 계산의 유일한 원천(source of truth)이므로
생성 시점에 유형별 필수 필드와 통화 일관성을 엄격하게 검증한다.
"""

from datetime import date
from decimal import Decimal

import pytest

from pams.portfolio.domain import Transaction, TransactionType
from pams.shared_kernel.domain import (
    Currency,
    CurrencyMismatchError,
    DomainValidationError,
    Money,
    Quantity,
)

TRADE_DATE = date(2026, 7, 10)


def buy(**overrides: object) -> Transaction:
    defaults: dict[str, object] = {
        "transaction_id": "tx-001",
        "transaction_type": TransactionType.BUY,
        "trade_date": TRADE_DATE,
        "asset_id": "KRX:005930",
        "quantity": Quantity.of(10),
        "price": Money.of("70000", Currency.KRW),
        "fee": Money.of("105", Currency.KRW),
        "tax": Money.zero(Currency.KRW),
    }
    defaults.update(overrides)
    return Transaction(**defaults)  # type: ignore[arg-type]


def dividend(**overrides: object) -> Transaction:
    defaults: dict[str, object] = {
        "transaction_id": "tx-002",
        "transaction_type": TransactionType.DIVIDEND,
        "trade_date": TRADE_DATE,
        "asset_id": "KRX:005930",
        "amount": Money.of("36100", Currency.KRW),
        "tax": Money.of("5558", Currency.KRW),
    }
    defaults.update(overrides)
    return Transaction(**defaults)  # type: ignore[arg-type]


class TestTradeTransactions:
    def test_valid_buy(self) -> None:
        tx = buy()
        assert tx.gross_amount == Money.of("700000", Currency.KRW)

    def test_buy_cash_flow_is_negative(self) -> None:
        """매수 = 현금 유출 (원금 + 수수료 + 세금)."""
        tx = buy()
        assert tx.signed_cash_flow == Money.of("-700105", Currency.KRW)

    def test_sell_cash_flow_is_positive(self) -> None:
        """매도 = 현금 유입 (원금 - 수수료 - 세금)."""
        tx = buy(
            transaction_type=TransactionType.SELL,
            fee=Money.of("105", Currency.KRW),
            tax=Money.of("1260", Currency.KRW),
        )
        assert tx.signed_cash_flow == Money.of("698635", Currency.KRW)

    def test_trade_requires_price(self) -> None:
        with pytest.raises(DomainValidationError):
            buy(price=None)

    def test_trade_requires_positive_quantity(self) -> None:
        with pytest.raises(DomainValidationError):
            buy(quantity=Quantity.of(0))

    def test_trade_requires_asset(self) -> None:
        with pytest.raises(DomainValidationError):
            buy(asset_id=None)

    def test_trade_must_not_carry_amount(self) -> None:
        """트레이드 금액은 price×quantity로 계산한다 - 이중 입력은 불일치 위험이므로 금지."""
        with pytest.raises(DomainValidationError):
            buy(amount=Money.of("700000", Currency.KRW))


class TestCashTransactions:
    def test_valid_dividend(self) -> None:
        tx = dividend()
        assert tx.signed_cash_flow == Money.of("30542", Currency.KRW)

    def test_dividend_requires_asset(self) -> None:
        with pytest.raises(DomainValidationError):
            dividend(asset_id=None)

    def test_deposit_and_withdrawal(self) -> None:
        deposit = dividend(
            transaction_type=TransactionType.DEPOSIT,
            asset_id=None,
            amount=Money.of("1000000", Currency.KRW),
            tax=None,
        )
        withdrawal = dividend(
            transaction_type=TransactionType.WITHDRAWAL,
            asset_id=None,
            amount=Money.of("300000", Currency.KRW),
            tax=None,
        )
        assert deposit.signed_cash_flow == Money.of("1000000", Currency.KRW)
        assert withdrawal.signed_cash_flow == Money.of("-300000", Currency.KRW)

    def test_cash_transaction_requires_amount(self) -> None:
        with pytest.raises(DomainValidationError):
            dividend(amount=None)

    def test_cash_transaction_must_not_carry_price_or_quantity(self) -> None:
        with pytest.raises(DomainValidationError):
            dividend(price=Money.of("70000", Currency.KRW))
        with pytest.raises(DomainValidationError):
            dividend(quantity=Quantity.of(1))

    def test_negative_amount_rejected(self) -> None:
        """방향은 transaction_type이 결정한다 - 금액은 항상 양수."""
        with pytest.raises(DomainValidationError):
            dividend(amount=Money.of("-100", Currency.KRW))


class TestConsistency:
    def test_currency_mismatch_rejected(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            buy(fee=Money.of("0.05", Currency.USD))

    def test_fee_and_tax_default_to_zero(self) -> None:
        tx = dividend(tax=None)
        assert tx.fee == Money.zero(Currency.KRW)
        assert tx.tax == Money.zero(Currency.KRW)

    def test_empty_transaction_id_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            buy(transaction_id=" ")

    def test_fractional_share_buy(self) -> None:
        """미국주식 소수점 매매 지원."""
        tx = buy(
            asset_id="NASDAQ:AAPL",
            quantity=Quantity.of("0.5"),
            price=Money.of("200", Currency.USD),
            fee=Money.zero(Currency.USD),
            tax=Money.zero(Currency.USD),
        )
        assert tx.gross_amount == Money.of("100", Currency.USD)
        assert tx.gross_amount.amount == Decimal("100.0")
