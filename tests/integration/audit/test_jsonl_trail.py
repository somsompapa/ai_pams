"""JSONL 감사 기록 저장소 통합 테스트."""

from datetime import UTC, datetime
from pathlib import Path

from pams.audit.domain import AuditEvent, AuditTrail
from pams.audit.infrastructure import JsonlAuditTrail


def event(event_id: str, hour: int = 9) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        occurred_at=datetime(2026, 7, 10, hour, 0, tzinfo=UTC),
        actor="system",
        action="report.generated",
        detail="월간 보고서 생성",
        reason="정기 보고 주기 도래",
    )


class TestJsonlAuditTrail:
    def test_satisfies_port(self, tmp_path: Path) -> None:
        assert isinstance(JsonlAuditTrail(tmp_path / "audit.jsonl"), AuditTrail)

    def test_roundtrip_preserves_timezone(self, tmp_path: Path) -> None:
        trail = JsonlAuditTrail(tmp_path / "audit.jsonl")
        trail.append(event("e1"))
        trail.append(event("e2", hour=10))
        events = trail.list_all()
        assert [e.event_id for e in events] == ["e1", "e2"]
        assert events[0].occurred_at.tzinfo is not None

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        JsonlAuditTrail(path).append(event("e1"))
        assert [e.event_id for e in JsonlAuditTrail(path).list_all()] == ["e1"]
