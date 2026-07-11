"""투자일지 기록/조회 유스케이스."""

from __future__ import annotations

from dataclasses import dataclass

from pams.journal.domain import JournalEntry, JournalRepository
from pams.shared_kernel.domain import DomainValidationError


@dataclass(frozen=True, slots=True)
class RecordJournalEntry:
    repository: JournalRepository

    def execute(self, *, entry: JournalEntry) -> JournalEntry:
        existing_ids = {e.entry_id for e in self.repository.list_all()}
        if entry.entry_id in existing_ids:
            raise DomainValidationError(f"이미 존재하는 일지 id: {entry.entry_id}")
        self.repository.append(entry)
        return entry


@dataclass(frozen=True, slots=True)
class ListJournalEntries:
    repository: JournalRepository

    def execute(self) -> list[JournalEntry]:
        return sorted(self.repository.list_all(), key=lambda e: (e.entry_date, e.entry_id))
