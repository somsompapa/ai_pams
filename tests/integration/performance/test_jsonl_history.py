"""JSONL 가치 이력 저장소 통합 테스트."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from pams.performance.domain import ValuationPoint, ValueHistoryRepository
from pams.performance.infrastructure import JsonlValueHistoryRepository


def point(day: str, value: str, flow: str = "0") -> ValuationPoint:
    return ValuationPoint(
        point_date=date.fromisoformat(day), value=Decimal(value), net_flow=Decimal(flow)
    )


class TestJsonlValueHistory:
    def test_satisfies_port(self, tmp_path: Path) -> None:
        repository = JsonlValueHistoryRepository(tmp_path / "history.jsonl")
        assert isinstance(repository, ValueHistoryRepository)

    def test_empty_returns_none(self, tmp_path: Path) -> None:
        assert JsonlValueHistoryRepository(tmp_path / "history.jsonl").load() is None

    def test_append_and_load_sorted(self, tmp_path: Path) -> None:
        repository = JsonlValueHistoryRepository(tmp_path / "history.jsonl")
        repository.append(point("2026-07-10", "27900000"))
        repository.append(point("2026-07-09", "27800000", flow="100000"))
        history = repository.load()
        assert history is not None
        assert history.points[0].point_date == date(2026, 7, 9)
        assert history.points[0].net_flow == Decimal("100000")

    def test_same_date_upserts(self, tmp_path: Path) -> None:
        """같은 날 재실행하면 마지막 값으로 교체된다 (하루 1점)."""
        repository = JsonlValueHistoryRepository(tmp_path / "history.jsonl")
        repository.append(point("2026-07-10", "27900000"))
        repository.append(point("2026-07-10", "28000000"))
        history = repository.load()
        assert history is not None
        assert len(history.points) == 1
        assert history.points[0].value == Decimal("28000000")

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "history.jsonl"
        JsonlValueHistoryRepository(path).append(point("2026-07-10", "27900000"))
        loaded = JsonlValueHistoryRepository(path).load()
        assert loaded is not None and len(loaded.points) == 1
