"""파일 시스템 보고서 저장소 (reports/ 디렉토리)."""

from __future__ import annotations

from pathlib import Path


class FileSystemReportSink:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def save(self, filename: str, content: str) -> Path:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        target = self._base_dir / filename
        target.write_text(content, encoding="utf-8")
        return target
