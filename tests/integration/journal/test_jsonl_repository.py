"""JSONL 파일 기반 투자일지 저장소 통합 테스트."""

from datetime import date
from pathlib import Path

from pams.journal.domain import JournalEntry, JournalRepository
from pams.journal.infrastructure import JsonlJournalRepository


def entry(entry_id: str, ai_draft: str | None = None) -> JournalEntry:
    return JournalEntry(
        entry_id=entry_id,
        entry_date=date(2026, 7, 10),
        title="삼성전자 일부 매도",
        what="삼성전자 30주 매도 @75,000",
        why="단일 종목 비중 규칙 위반 해소",
        rule_basis="max-single-position",
        ai_draft=ai_draft,
    )


class TestJsonlJournalRepository:
    def test_satisfies_port(self, tmp_path: Path) -> None:
        assert isinstance(JsonlJournalRepository(tmp_path / "journal.jsonl"), JournalRepository)

    def test_roundtrip(self, tmp_path: Path) -> None:
        repository = JsonlJournalRepository(tmp_path / "journal.jsonl")
        first = entry("e1", ai_draft="AI 초안: 규칙 위반 해소를 위한 기계적 매도였다.")
        second = entry("e2")
        repository.append(first)
        repository.append(second)
        assert repository.list_all() == [first, second]

    def test_empty_file_lists_nothing(self, tmp_path: Path) -> None:
        repository = JsonlJournalRepository(tmp_path / "journal.jsonl")
        assert repository.list_all() == []

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "journal.jsonl"
        JsonlJournalRepository(path).append(entry("e1"))
        assert [e.entry_id for e in JsonlJournalRepository(path).list_all()] == ["e1"]
