"""journal 컨텍스트 테스트: 투자일지 엔트리와 기록/조회 유스케이스."""

from datetime import date

import pytest

from pams.journal.application import ListJournalEntries, RecordJournalEntry
from pams.journal.domain import JournalEntry, JournalRepository
from pams.shared_kernel.domain import DomainValidationError

ENTRY_DATE = date(2026, 7, 10)


def entry(**overrides: object) -> JournalEntry:
    defaults: dict[str, object] = {
        "entry_id": "2026-07-10-001",
        "entry_date": ENTRY_DATE,
        "title": "삼성전자 일부 매도",
        "what": "삼성전자 30주 매도 @75,000",
        "why": "단일 종목 비중 26.9%로 max-single-position 규칙(20%) 위반",
        "rule_basis": "max-single-position",
        "ai_draft": None,
    }
    defaults.update(overrides)
    return JournalEntry(**defaults)  # type: ignore[arg-type]


class TestJournalEntry:
    def test_valid_entry(self) -> None:
        journal_entry = entry()
        assert journal_entry.rule_basis == "max-single-position"

    def test_what_and_why_required(self) -> None:
        """일지의 존재 이유: 무엇을/왜 없이는 기록이 아니다."""
        with pytest.raises(DomainValidationError):
            entry(what=" ")
        with pytest.raises(DomainValidationError):
            entry(why="")

    def test_empty_id_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            entry(entry_id="")


class InMemoryJournal:
    def __init__(self) -> None:
        self.entries: list[JournalEntry] = []

    def append(self, journal_entry: JournalEntry) -> None:
        self.entries.append(journal_entry)

    def list_all(self) -> list[JournalEntry]:
        return list(self.entries)


class TestUseCases:
    def test_fake_satisfies_port(self) -> None:
        assert isinstance(InMemoryJournal(), JournalRepository)

    def test_record_and_list(self) -> None:
        repository = InMemoryJournal()
        recorded = RecordJournalEntry(repository=repository).execute(entry=entry())
        entries = ListJournalEntries(repository=repository).execute()
        assert entries == [recorded]

    def test_duplicate_id_rejected(self) -> None:
        repository = InMemoryJournal()
        use_case = RecordJournalEntry(repository=repository)
        use_case.execute(entry=entry())
        with pytest.raises(DomainValidationError):
            use_case.execute(entry=entry())
