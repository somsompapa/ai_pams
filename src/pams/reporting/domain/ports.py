"""reporting 컨텍스트의 포트: 렌더러와 저장소."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pams.reporting.domain.document import ReportDocument


@runtime_checkable
class ReportRenderer(Protocol):
    def render(self, document: ReportDocument) -> str:
        """문서를 특정 형식(Markdown/HTML/PDF 등)의 문자열로 변환한다."""
        ...


@runtime_checkable
class ReportSink(Protocol):
    def save(self, filename: str, content: str) -> Path:
        """렌더링 결과를 저장하고 저장 위치를 반환한다."""
        ...
