"""Transaction: 모든 자산 이동의 원천 기록.

실현손익/예수금/보유수량은 전부 거래 기록에서 파생 계산되므로,
거래는 생성 시점에 유형별 필수 필드와 통화 일관성을 엄격히 검증한다.

두 가지 유형이 있다.
- 트레이드(BUY/SELL): quantity·price 필수, 금액은 price×quantity로 계산 (이중 입력 금지)
- 현금성(DIVIDEND/INTEREST/DEPOSIT/WITHDRAWAL/FEE/TAX): amount 필수, 방향은 유형이 결정
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum, unique

from pams.shared_kernel.domain import (
    Currency,
    CurrencyMismatchError,
    DomainValidationError,
    Money,
    Quantity,
)


@unique
class TransactionType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"  # 배당
    INTEREST = "interest"  # 이자
    DEPOSIT = "deposit"  # 입금
    WITHDRAWAL = "withdrawal"  # 출금
    FEE = "fee"  # 계좌 수수료 등 거래에 귀속되지 않는 비용
    TAX = "tax"  # 거래에 귀속되지 않는 세금 (예: 종합소득세 원천징수)

    @property
    def is_trade(self) -> bool:
        return self in (TransactionType.BUY, TransactionType.SELL)

    @property
    def is_cash_inflow(self) -> bool:
        """현금성 거래 중 현금이 들어오는 유형."""
        return self in (
            TransactionType.DIVIDEND,
            TransactionType.INTEREST,
            TransactionType.DEPOSIT,
        )


# 자산에 귀속되어야만 의미가 있는 현금성 거래
_ASSET_BOUND_CASH_TYPES = frozenset({TransactionType.DIVIDEND, TransactionType.INTEREST})


@dataclass(frozen=True, slots=True)
class Transaction:
    transaction_id: str
    transaction_type: TransactionType
    trade_date: date
    currency: Currency = field(init=False)  # 아래 필드들에서 유도
    asset_id: str | None = None
    quantity: Quantity | None = None
    price: Money | None = None
    amount: Money | None = None  # 현금성 거래 금액 (항상 양수, 방향은 유형이 결정)
    fee: Money | None = None  # 미지정 시 0
    tax: Money | None = None  # 미지정 시 0
    note: str = ""

    def __post_init__(self) -> None:
        if not self.transaction_id.strip():
            raise DomainValidationError("transaction_id는 비어 있을 수 없다")

        if self.transaction_type.is_trade:
            self._validate_trade()
            base = self.price
        else:
            self._validate_cash()
            base = self.amount

        assert base is not None  # 위 검증에서 보장됨
        object.__setattr__(self, "currency", base.currency)

        if self.fee is None:
            object.__setattr__(self, "fee", Money.zero(self.currency))
        if self.tax is None:
            object.__setattr__(self, "tax", Money.zero(self.currency))

        for label, money in (("fee", self.fee), ("tax", self.tax)):
            assert money is not None
            if money.currency is not self.currency:
                raise CurrencyMismatchError(
                    f"{label}의 통화({money.currency})가 거래 통화({self.currency})와 다르다"
                )
            if money.is_negative:
                raise DomainValidationError(f"{label}는 음수가 될 수 없다")

    def _validate_trade(self) -> None:
        if self.asset_id is None or not self.asset_id.strip():
            raise DomainValidationError("트레이드에는 asset_id가 필요하다")
        if self.price is None:
            raise DomainValidationError("트레이드에는 price가 필요하다")
        if not self.price.is_positive:
            raise DomainValidationError("트레이드 가격은 양수여야 한다")
        if self.quantity is None or self.quantity.is_zero:
            raise DomainValidationError("트레이드에는 0보다 큰 quantity가 필요하다")
        if self.amount is not None:
            raise DomainValidationError(
                "트레이드 금액은 price×quantity로 계산한다 - amount를 직접 지정할 수 없다"
            )

    def _validate_cash(self) -> None:
        if self.amount is None:
            raise DomainValidationError(f"{self.transaction_type} 거래에는 amount가 필요하다")
        if not self.amount.is_positive:
            raise DomainValidationError("현금성 거래 금액은 양수여야 한다 (방향은 유형이 결정)")
        if self.price is not None or self.quantity is not None:
            raise DomainValidationError("현금성 거래에는 price/quantity를 지정할 수 없다")
        if self.transaction_type in _ASSET_BOUND_CASH_TYPES and self.asset_id is None:
            raise DomainValidationError(f"{self.transaction_type} 거래에는 asset_id가 필요하다")

    @property
    def gross_amount(self) -> Money:
        """수수료/세금을 제외한 원금."""
        if self.transaction_type.is_trade:
            assert self.price is not None and self.quantity is not None
            return self.price * self.quantity.value
        assert self.amount is not None
        return self.amount

    @property
    def signed_cash_flow(self) -> Money:
        """이 거래로 인한 현금 증감 (+유입 / -유출). 예수금 계산의 기초."""
        assert self.fee is not None and self.tax is not None
        costs = self.fee + self.tax
        if self.transaction_type is TransactionType.BUY:
            return -(self.gross_amount + costs)
        if self.transaction_type is TransactionType.SELL:
            return self.gross_amount - costs
        if self.transaction_type.is_cash_inflow:
            return self.gross_amount - costs
        # WITHDRAWAL / FEE / TAX: 유출
        return -(self.gross_amount + costs)
