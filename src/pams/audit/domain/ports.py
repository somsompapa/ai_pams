"""audit 컨텍스트의 포트: 감사 기록 저장소."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pams.audit.domain.event import AuditEvent


@runtime_checkable
class AuditTrail(Protocol):
    def append(self, audit_event: AuditEvent) -> None: ...

    def list_all(self) -> Sequence[AuditEvent]: ...
