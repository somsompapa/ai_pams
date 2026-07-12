"""감사 기록 유스케이스."""

from __future__ import annotations

from dataclasses import dataclass

from pams.audit.domain import AuditEvent, AuditTrail
from pams.shared_kernel.domain import DomainValidationError


@dataclass(frozen=True, slots=True)
class RecordAuditEvent:
    trail: AuditTrail

    def execute(self, *, event: AuditEvent) -> AuditEvent:
        if any(e.event_id == event.event_id for e in self.trail.list_all()):
            raise DomainValidationError(f"이미 존재하는 감사 기록 id: {event.event_id}")
        self.trail.append(event)
        return event


@dataclass(frozen=True, slots=True)
class ListAuditEvents:
    trail: AuditTrail

    def execute(self) -> list[AuditEvent]:
        return sorted(self.trail.list_all(), key=lambda e: (e.occurred_at, e.event_id))
