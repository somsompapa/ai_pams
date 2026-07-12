"""유스케이스: 보고서 문서를 렌더링해 저장한다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pams.reporting.domain import ReportDocument, ReportRenderer, ReportSink


@dataclass(frozen=True, slots=True)
class GenerateReport:
    renderer: ReportRenderer
    sink: ReportSink

    def execute(self, *, document: ReportDocument, filename: str) -> Path:
        return self.sink.save(filename, self.renderer.render(document))
