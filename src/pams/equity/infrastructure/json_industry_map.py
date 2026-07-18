"""업종분류 맵 파일 저장소. sync-industry CLI가 적재하고, 종목분석 API가 읽는다.

JSONL 시계열이 아니라 단순 맵이다(하루 1회 배치로 통째로 재작성) — 값 이력
저장소(JsonlValueHistoryRepository)와 달리 과거 시점을 남기지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

from pams.equity.domain.industry_classification import IndustryClassification


class JsonIndustryClassificationRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, IndustryClassification]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        result: dict[str, IndustryClassification] = {}
        for key, entry in raw.items():
            if not isinstance(entry, dict) or not entry.get("code"):
                continue
            result[key] = IndustryClassification(code=str(entry["code"]), name=entry.get("name"))
        return result

    def save(self, entries: dict[str, IndustryClassification]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            key: {"code": entry.code, "name": entry.name} for key, entry in sorted(entries.items())
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
