"""Markdown/HTML 렌더러 테스트."""

from datetime import date

from pams.reporting.domain import (
    KeyValueBlock,
    Paragraph,
    ReportDocument,
    ReportRenderer,
    Section,
    TableBlock,
)
from pams.reporting.infrastructure import HtmlRenderer, MarkdownRenderer

DOCUMENT = ReportDocument(
    title="월간 투자 보고서",
    as_of=date(2026, 7, 10),
    sections=(
        Section(
            heading="요약",
            blocks=(
                Paragraph(text="포트폴리오는 IPS를 준수하고 있다."),
                KeyValueBlock(items=(("총자산", "10,000,000 KRW"), ("누적수익률", "21.00%"))),
            ),
        ),
        Section(
            heading="자산배분",
            blocks=(
                TableBlock(
                    headers=("자산군", "현재비중", "목표비중"),
                    rows=(("미국주식", "55.00%", "40.00%"), ("채권", "25.00%", "40.00%")),
                ),
            ),
        ),
    ),
)


class TestMarkdownRenderer:
    def test_satisfies_port(self) -> None:
        assert isinstance(MarkdownRenderer(), ReportRenderer)

    def test_structure(self) -> None:
        output = MarkdownRenderer().render(DOCUMENT)
        assert "# 월간 투자 보고서" in output
        assert "기준일: 2026-07-10" in output
        assert "## 요약" in output
        assert "- **총자산**: 10,000,000 KRW" in output
        assert "| 자산군 | 현재비중 | 목표비중 |" in output
        assert "| 미국주식 | 55.00% | 40.00% |" in output

    def test_pipe_in_cell_is_escaped(self) -> None:
        document = ReportDocument(
            title="t",
            as_of=date(2026, 7, 10),
            sections=(
                Section(
                    heading="h",
                    blocks=(TableBlock(headers=("이름",), rows=(("a|b",),)),),
                ),
            ),
        )
        output = MarkdownRenderer().render(document)
        assert "a\\|b" in output


class TestHtmlRenderer:
    def test_satisfies_port(self) -> None:
        assert isinstance(HtmlRenderer(), ReportRenderer)

    def test_structure(self) -> None:
        output = HtmlRenderer().render(DOCUMENT)
        assert "<!doctype html>" in output.lower()
        assert "<h1>월간 투자 보고서</h1>" in output
        assert "<h2>요약</h2>" in output
        assert "<td>미국주식</td>" in output
        assert "<th>자산군</th>" in output
        assert "<dt>총자산</dt>" in output
        assert "<dd>10,000,000 KRW</dd>" in output

    def test_html_is_escaped(self) -> None:
        document = ReportDocument(
            title="<script>alert(1)</script>",
            as_of=date(2026, 7, 10),
            sections=(Section(heading="h", blocks=(Paragraph(text="a < b & c"),)),),
        )
        output = HtmlRenderer().render(document)
        assert "<script>" not in output
        assert "&lt;script&gt;" in output
        assert "a &lt; b &amp; c" in output
