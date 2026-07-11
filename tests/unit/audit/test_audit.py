"""audit 컨텍스트 테스트: 누가/언제/무엇을/왜의 감사 기록."""

from datetime import UTC, datetime

import pytest

from pams.audit.application import ListAuditEvents, RecordAuditEvent
from pams.audit.domain import AuditEvent, AuditTrail
from pams.shared_kernel.domain import DomainValidationError

OCCURRED_AT = datetime(2026, 7, 10, 9, 30, tzinfo=UTC)


def event(**overrides: object) -> AuditEvent:
    defaults: dict[str, object] = {
        "event_id": "evt-001",
        "occurred_at": OCCURRED_AT,
        "actor": "user",
        "action": "journal.recorded",
        "detail": "투자일지 2026-07-10-001 기록",
        "reason": "리밸런싱 실행 근거 보존",
    }
    defaults.update(overrides)
    return AuditEvent(**defaults)  # type: ignore[arg-type]


class TestAuditEvent:
    def test_valid_event(self) -> None:
        assert event().action == "journal.recorded"

    def test_required_fields(self) -> None:
        for field in ("event_id", "actor", "action", "detail", "reason"):
            with pytest.raises(DomainValidationError):
                event(**{field: "  "})

    def test_naive_datetime_rejected(self) -> None:
        """감사 기록의 시각은 반드시 타임존이 있어야 한다 (언제인지가 모호하면 안 됨)."""
        with pytest.raises(DomainValidationError):
            event(occurred_at=datetime(2026, 7, 10, 9, 30))


class InMemoryTrail:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def append(self, audit_event: AuditEvent) -> None:
        self.events.append(audit_event)

    def list_all(self) -> list[AuditEvent]:
        return list(self.events)


class TestUseCases:
    def test_fake_satisfies_port(self) -> None:
        assert isinstance(InMemoryTrail(), AuditTrail)

    def test_record_and_list_sorted_by_time(self) -> None:
        trail = InMemoryTrail()
        recorder = RecordAuditEvent(trail=trail)
        later = event(event_id="evt-002", occurred_at=OCCURRED_AT.replace(hour=10))
        recorder.execute(event=later)
        recorder.execute(event=event())
        events = ListAuditEvents(trail=trail).execute()
        assert [e.event_id for e in events] == ["evt-001", "evt-002"]

    def test_duplicate_id_rejected(self) -> None:
        trail = InMemoryTrail()
        recorder = RecordAuditEvent(trail=trail)
        recorder.execute(event=event())
        with pytest.raises(DomainValidationError):
            recorder.execute(event=event())
