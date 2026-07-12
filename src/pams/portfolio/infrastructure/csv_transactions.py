"""CSV 파일 기반 거래 저장소.

data/transactions.csv 형식 (헤더 필수):
transaction_id,type,trade_date,asset_id,quantity,price,amount,fee,tax,currency,note

- type: buy/sell/dividend/interest/deposit/withdrawal/fee/tax
- 빈 칸은 해당 없음(None). 금액/수량은 문자열 그대로 Decimal로 읽는다 (float 무경유).
- 잘못된 행은 행 번호와 함께 CsvDataError로 실패한다 - 자산 계산의 원천이므로
  일부만 조용히 읽는 일은 없다.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from pams.portfolio.domain import Transaction, TransactionType
from pams.shared_kernel.domain import Currency, DomainError, Money, Quantity

_HEADER = [
    "transaction_id",
    "type",
    "trade_date",
    "asset_id",
    "quantity",
    "price",
    "amount",
    "fee",
    "tax",
    "currency",
    "note",
]


class CsvDataError(Exception):
    """CSV 데이터 파일을 도메인 객체로 변환하는 데 실패했다."""


def _optional(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


class CsvTransactionRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def transactions_until(self, as_of: date) -> list[Transaction]:
        transactions = self._load_all()
        return [t for t in transactions if t.trade_date <= as_of]

    def append(self, transaction: Transaction) -> None:
        """거래 한 건을 파일 끝에 추가한다. 거래내역이 유일한 원천이므로,
        기존 행은 건드리지 않고 append만 한다. 파일이 없으면 헤더부터 만든다.
        """
        if self._path.exists():
            existing_ids = {t.transaction_id for t in self._load_all()}
            if transaction.transaction_id in existing_ids:
                raise CsvDataError(f"중복된 transaction_id '{transaction.transaction_id}'")
            need_header = self._path.read_text(encoding="utf-8-sig").strip() == ""
        else:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            need_header = True

        with self._path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if need_header:
                writer.writerow(_HEADER)
            writer.writerow(self._to_row(transaction))

    @staticmethod
    def _to_row(t: Transaction) -> list[str]:
        def num(value: object) -> str:
            return "" if value is None else str(value)

        return [
            t.transaction_id,
            t.transaction_type.value,
            t.trade_date.isoformat(),
            t.asset_id or "",
            num(t.quantity.value) if t.quantity is not None else "",
            num(t.price.amount) if t.price is not None else "",
            num(t.amount.amount) if t.amount is not None else "",
            num(t.fee.amount) if t.fee is not None else "",
            num(t.tax.amount) if t.tax is not None else "",
            t.currency.value,
            t.note,
        ]

    def _load_all(self) -> list[Transaction]:
        try:
            text = self._path.read_text(encoding="utf-8-sig")
        except OSError as error:
            raise CsvDataError(f"거래 파일을 읽을 수 없다: {self._path}") from error

        transactions: list[Transaction] = []
        seen_ids: set[str] = set()
        reader = csv.DictReader(text.splitlines())
        for row_number, row in enumerate(reader, start=2):  # 파일 행 번호 (1행 = 헤더)
            transaction = self._parse_row(row, row_number)
            if transaction.transaction_id in seen_ids:
                raise CsvDataError(
                    f"{self._path} {row_number}행: 중복된 transaction_id "
                    f"'{transaction.transaction_id}'"
                )
            seen_ids.add(transaction.transaction_id)
            transactions.append(transaction)
        return transactions

    def _parse_row(self, row: dict[str, str | None], row_number: int) -> Transaction:
        where = f"{self._path} {row_number}행"
        raw_type = _optional(row.get("type"))
        try:
            transaction_type = TransactionType(raw_type or "")
        except ValueError:
            raise CsvDataError(f"{where}: 알 수 없는 거래 유형 {raw_type!r}") from None

        raw_currency = _optional(row.get("currency"))
        try:
            currency = Currency(raw_currency or "")
        except ValueError:
            raise CsvDataError(f"{where}: 알 수 없는 통화 {raw_currency!r}") from None

        raw_date = _optional(row.get("trade_date"))
        try:
            trade_date = date.fromisoformat(raw_date or "")
        except ValueError:
            raise CsvDataError(f"{where}: 잘못된 날짜 {raw_date!r}") from None

        def money_of(field: str) -> Money | None:
            value = _optional(row.get(field))
            if value is None:
                return None
            try:
                return Money.of(value, currency)
            except DomainError as error:
                raise CsvDataError(f"{where}: {field} 값 오류: {error}") from error

        quantity_raw = _optional(row.get("quantity"))
        try:
            quantity = Quantity.of(quantity_raw) if quantity_raw is not None else None
        except DomainError as error:
            raise CsvDataError(f"{where}: quantity 값 오류: {error}") from error

        try:
            return Transaction(
                transaction_id=_optional(row.get("transaction_id")) or "",
                transaction_type=transaction_type,
                trade_date=trade_date,
                asset_id=_optional(row.get("asset_id")),
                quantity=quantity,
                price=money_of("price"),
                amount=money_of("amount"),
                fee=money_of("fee"),
                tax=money_of("tax"),
                note=_optional(row.get("note")) or "",
            )
        except DomainError as error:
            raise CsvDataError(f"{where}: {error}") from error
