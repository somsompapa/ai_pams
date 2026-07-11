"""JSONL 파일 기반 투자일지 저장소.

한 줄 = 한 엔트리. append 전용이라 과거 기록이 변조되지 않는다(감사 친화적).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pams.journal.domain import JournalEntry


class JsonlJournalRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, journal_entry: JournalEntry) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "entry_id": journal_entry.entry_id,
            "entry_date": journal_entry.entry_date.isoformat(),
            "title": journal_entry.title,
            "what": journal_entry.what,
            "why": journal_entry.why,
            "rule_basis": journal_entry.rule_basis,
            "ai_draft": journal_entry.ai_draft,
        }
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def list_all(self) -> list[JournalEntry]:
        if not self._path.exists():
            return []
        entries = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            entries.append(
                JournalEntry(
                    entry_id=record["entry_id"],
                    entry_date=date.fromisoformat(record["entry_date"]),
                    title=record["title"],
                    what=record["what"],
                    why=record["why"],
                    rule_basis=record.get("rule_basis", ""),
                    ai_draft=record.get("ai_draft"),
                )
            )
        return entries
