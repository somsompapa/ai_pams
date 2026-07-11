"""JSONL 가치 이력 저장소. 하루 1점(같은 날짜는 마지막 값으로 교체)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from pams.performance.domain import PerformanceHistory, ValuationPoint


class JsonlValueHistoryRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, point: ValuationPoint) -> None:
        points = {p.point_date: p for p in self._read()}
        points[point.point_date] = point
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as file:
            for entry in sorted(points.values(), key=lambda p: p.point_date):
                record = {
                    "date": entry.point_date.isoformat(),
                    "value": str(entry.value),
                    "net_flow": str(entry.net_flow),
                }
                file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load(self) -> PerformanceHistory | None:
        points = self._read()
        return PerformanceHistory.from_points(points) if points else None

    def _read(self) -> list[ValuationPoint]:
        if not self._path.exists():
            return []
        points = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            points.append(
                ValuationPoint(
                    point_date=date.fromisoformat(record["date"]),
                    value=Decimal(record["value"]),
                    net_flow=Decimal(record["net_flow"]),
                )
            )
        return points
