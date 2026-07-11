"""JSONL 파일 기반 감사 기록 저장소 (append-only, 변조 방지 친화)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pams.audit.domain import AuditEvent


class JsonlAuditTrail:
    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, audit_event: AuditEvent) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "event_id": audit_event.event_id,
            "occurred_at": audit_event.occurred_at.isoformat(),
            "actor": audit_event.actor,
            "action": audit_event.action,
            "detail": audit_event.detail,
            "reason": audit_event.reason,
        }
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def list_all(self) -> list[AuditEvent]:
        if not self._path.exists():
            return []
        events = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            events.append(
                AuditEvent(
                    event_id=record["event_id"],
                    occurred_at=datetime.fromisoformat(record["occurred_at"]),
                    actor=record["actor"],
                    action=record["action"],
                    detail=record["detail"],
                    reason=record["reason"],
                )
            )
        return events
