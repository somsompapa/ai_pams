"""CSV 거래 저장소 통합 테스트."""

from datetime import date
from pathlib import Path

import pytest

from pams.portfolio.domain import Transaction, TransactionRepository, TransactionType
from pams.portfolio.infrastructure import CsvDataError, CsvTransactionRepository
from pams.shared_kernel.domain import Currency, Money, Quantity

HEADER = "transaction_id,type,trade_date,asset_id,quantity,price,amount,fee,tax,currency,note"

VALID = f"""{HEADER}
t1,deposit,2026-01-02,,,,20000000,0,0,KRW,초기 입금
t2,buy,2026-01-05,KRX:005930,100,70000,,1050,0,KRW,
t3,dividend,2026-04-15,KRX:005930,,,36100,0,5558,KRW,
t4,buy,2026-05-06,NASDAQ:AAPL,0.5,200,,0,0,USD,소수점 매수
"""


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "transactions.csv"
    path.write_text(content, encoding="utf-8")
    return path


class TestAppend:
    def test_append_to_existing_file_and_read_back(self, tmp_path: Path) -> None:
        repo = CsvTransactionRepository(write(tmp_path, VALID))
        repo.append(
            Transaction(
                transaction_id="t5",
                transaction_type=TransactionType.SELL,
                trade_date=date(2026, 7, 15),
                asset_id="KRX:005930",
                quantity=Quantity.of("30"),
                price=Money.of("82000", Currency.KRW),
                note="일부 매도",
            )
        )
        transactions = repo.transactions_until(date(2026, 12, 31))
        assert [t.transaction_id for t in transactions] == ["t1", "t2", "t3", "t4", "t5"]
        sold = transactions[-1]
        assert sold.transaction_type is TransactionType.SELL
        assert sold.price is not None and str(sold.price.amount) == "82000"
        assert sold.note == "일부 매도"

    def test_append_creates_file_with_header_when_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "transactions.csv"
        repo = CsvTransactionRepository(path)
        repo.append(
            Transaction(
                transaction_id="t1",
                transaction_type=TransactionType.DEPOSIT,
                trade_date=date(2026, 7, 15),
                amount=Money.of("1000000", Currency.KRW),
            )
        )
        assert path.exists()
        assert path.read_text(encoding="utf-8").splitlines()[0] == HEADER
        assert repo.transactions_until(date(2026, 12, 31))[0].transaction_id == "t1"

    def test_append_rejects_duplicate_id(self, tmp_path: Path) -> None:
        repo = CsvTransactionRepository(write(tmp_path, VALID))
        with pytest.raises(CsvDataError, match="중복"):
            repo.append(
                Transaction(
                    transaction_id="t1",
                    transaction_type=TransactionType.DEPOSIT,
                    trade_date=date(2026, 7, 15),
                    amount=Money.of("1", Currency.KRW),
                )
            )


class TestListAll:
    def test_returns_all_transactions(self, tmp_path: Path) -> None:
        repo = CsvTransactionRepository(write(tmp_path, VALID))
        assert [t.transaction_id for t in repo.list_all()] == ["t1", "t2", "t3", "t4"]

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        repo = CsvTransactionRepository(tmp_path / "nope.csv")
        assert repo.list_all() == []


class TestUpdate:
    def test_replaces_matching_row(self, tmp_path: Path) -> None:
        repo = CsvTransactionRepository(write(tmp_path, VALID))
        repo.update(
            "t2",
            Transaction(
                transaction_id="t2",
                transaction_type=TransactionType.BUY,
                trade_date=date(2026, 1, 5),
                asset_id="KRX:005930",
                quantity=Quantity.of("120"),
                price=Money.of("71000", Currency.KRW),
                note="수량 정정",
            ),
        )
        transactions = repo.transactions_until(date(2026, 12, 31))
        assert [t.transaction_id for t in transactions] == ["t1", "t2", "t3", "t4"]
        edited = transactions[1]
        assert edited.quantity is not None and str(edited.quantity.value) == "120"
        assert edited.note == "수량 정정"

    def test_unknown_id_raises(self, tmp_path: Path) -> None:
        repo = CsvTransactionRepository(write(tmp_path, VALID))
        with pytest.raises(CsvDataError, match="찾을 수 없다"):
            repo.update(
                "nope",
                Transaction(
                    transaction_id="nope",
                    transaction_type=TransactionType.DEPOSIT,
                    trade_date=date(2026, 1, 1),
                    amount=Money.of("1", Currency.KRW),
                ),
            )

    def test_rejects_id_collision_with_other_row(self, tmp_path: Path) -> None:
        repo = CsvTransactionRepository(write(tmp_path, VALID))
        with pytest.raises(CsvDataError, match="중복"):
            repo.update(
                "t2",
                Transaction(
                    transaction_id="t3",
                    transaction_type=TransactionType.BUY,
                    trade_date=date(2026, 1, 5),
                    asset_id="KRX:005930",
                    quantity=Quantity.of("1"),
                    price=Money.of("1", Currency.KRW),
                ),
            )


class TestDelete:
    def test_removes_matching_row(self, tmp_path: Path) -> None:
        repo = CsvTransactionRepository(write(tmp_path, VALID))
        repo.delete("t2")
        assert [t.transaction_id for t in repo.transactions_until(date(2026, 12, 31))] == [
            "t1",
            "t3",
            "t4",
        ]

    def test_unknown_id_raises(self, tmp_path: Path) -> None:
        repo = CsvTransactionRepository(write(tmp_path, VALID))
        with pytest.raises(CsvDataError, match="찾을 수 없다"):
            repo.delete("nope")


class TestCsvTransactionRepository:
    def test_satisfies_port(self, tmp_path: Path) -> None:
        repository = CsvTransactionRepository(write(tmp_path, VALID))
        assert isinstance(repository, TransactionRepository)

    def test_parses_all_transaction_shapes(self, tmp_path: Path) -> None:
        repository = CsvTransactionRepository(write(tmp_path, VALID))
        transactions = repository.transactions_until(date(2026, 12, 31))
        assert [t.transaction_id for t in transactions] == ["t1", "t2", "t3", "t4"]
        buy = transactions[1]
        assert buy.transaction_type is TransactionType.BUY
        assert buy.quantity is not None and str(buy.quantity.value) == "100"
        fractional = transactions[3]
        assert fractional.quantity is not None and str(fractional.quantity.value) == "0.5"

    def test_filters_by_as_of(self, tmp_path: Path) -> None:
        repository = CsvTransactionRepository(write(tmp_path, VALID))
        until_january = repository.transactions_until(date(2026, 1, 31))
        assert [t.transaction_id for t in until_january] == ["t1", "t2"]

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(CsvDataError):
            CsvTransactionRepository(tmp_path / "nope.csv").transactions_until(date(2026, 1, 1))

    def test_bad_row_reports_row_number(self, tmp_path: Path) -> None:
        bad = f"{HEADER}\nt1,buy,2026-01-05,KRX:005930,100,,,,0,KRW,가격 누락\n"
        with pytest.raises(CsvDataError, match="2행"):
            CsvTransactionRepository(write(tmp_path, bad)).transactions_until(date(2026, 12, 31))

    def test_unknown_type_reports_value(self, tmp_path: Path) -> None:
        bad = f"{HEADER}\nt1,short_sell,2026-01-05,KRX:005930,100,70000,,0,0,KRW,\n"
        with pytest.raises(CsvDataError, match="short_sell"):
            CsvTransactionRepository(write(tmp_path, bad)).transactions_until(date(2026, 12, 31))

    def test_duplicate_id_rejected(self, tmp_path: Path) -> None:
        bad = (
            f"{HEADER}\n"
            "t1,deposit,2026-01-02,,,,1000,0,0,KRW,\n"
            "t1,deposit,2026-01-03,,,,1000,0,0,KRW,\n"
        )
        with pytest.raises(CsvDataError, match="t1"):
            CsvTransactionRepository(write(tmp_path, bad)).transactions_until(date(2026, 12, 31))
