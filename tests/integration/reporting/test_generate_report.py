"""GenerateReport 유스케이스 + 파일 저장 통합 테스트."""

from datetime import date
from pathlib import Path

from pams.reporting.application import GenerateReport
from pams.reporting.domain import Paragraph, ReportDocument, ReportSink, Section
from pams.reporting.infrastructure import (
    FileSystemReportSink,
    HtmlRenderer,
    MarkdownRenderer,
)

DOCUMENT = ReportDocument(
    title="월간 투자 보고서",
    as_of=date(2026, 7, 10),
    sections=(Section(heading="요약", blocks=(Paragraph(text="테스트 보고서."),)),),
)


class TestFileSystemSink:
    def test_satisfies_port_and_saves(self, tmp_path: Path) -> None:
        sink = FileSystemReportSink(base_dir=tmp_path / "reports")
        assert isinstance(sink, ReportSink)
        saved = sink.save("2026-07-report.md", "# 내용")
        assert saved.read_text(encoding="utf-8") == "# 내용"
        assert saved.parent == tmp_path / "reports"


class TestGenerateReport:
    def test_markdown_report_written(self, tmp_path: Path) -> None:
        use_case = GenerateReport(
            renderer=MarkdownRenderer(), sink=FileSystemReportSink(base_dir=tmp_path)
        )
        saved = use_case.execute(document=DOCUMENT, filename="2026-07-report.md")
        content = saved.read_text(encoding="utf-8")
        assert content.startswith("# 월간 투자 보고서")

    def test_html_report_written(self, tmp_path: Path) -> None:
        use_case = GenerateReport(
            renderer=HtmlRenderer(), sink=FileSystemReportSink(base_dir=tmp_path)
        )
        saved = use_case.execute(document=DOCUMENT, filename="2026-07-report.html")
        assert "<h1>월간 투자 보고서</h1>" in saved.read_text(encoding="utf-8")
