"""AuditEvent: 누가/언제/무엇을/왜 실행했는지의 불변 기록."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pams.shared_kernel.domain import DomainValidationError


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    occurred_at: datetime  # 타임존 필수
    actor: str  # 누가: user / system / rule-engine ...
    action: str  # 무엇을: "journal.recorded", "report.generated" 등 점 표기 관례
    detail: str  # 무엇을 (상세)
    reason: str  # 왜

    def __post_init__(self) -> None:
        for name, value in (
            ("event_id", self.event_id),
            ("actor", self.actor),
            ("action", self.action),
            ("detail", self.detail),
            ("reason", self.reason),
        ):
            if not value.strip():
                raise DomainValidationError(f"감사 기록의 {name}은 비어 있을 수 없다")
        if self.occurred_at.tzinfo is None:
            raise DomainValidationError("감사 기록의 시각에는 타임존이 필요하다")
