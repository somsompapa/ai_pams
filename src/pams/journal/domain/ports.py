"""journal 컨텍스트의 포트: 일지 저장소."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pams.journal.domain.entry import JournalEntry


@runtime_checkable
class JournalRepository(Protocol):
    def append(self, journal_entry: JournalEntry) -> None: ...

    def list_all(self) -> Sequence[JournalEntry]: ...
