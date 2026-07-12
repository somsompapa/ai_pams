"""PDF 렌더러 통합 테스트.

한글 폰트(TTF) 경로를 주입받아 렌더링한다. 시스템에 한글 폰트가 없으면 skip.
"""

from datetime import date
from pathlib import Path

import pytest

from pams.reporting.domain import (
    KeyValueBlock,
    Paragraph,
    ReportDocument,
    ReportRenderer,
    Section,
    TableBlock,
)
from pams.reporting.infrastructure import PdfRenderer, find_korean_font

DOCUMENT = ReportDocument(
    title="월간 투자 보고서",
    as_of=date(2026, 7, 10),
    sections=(
        Section(
            heading="요약",
            blocks=(
                Paragraph(text="포트폴리오는 IPS를 준수하고 있다."),
                KeyValueBlock(items=(("총자산", "10,000,000 KRW"),)),
                TableBlock(headers=("자산군", "비중"), rows=(("미국주식", "40.00%"),)),
            ),
        ),
    ),
)

FONT = find_korean_font()
needs_font = pytest.mark.skipif(FONT is None, reason="한글 TTF 폰트가 시스템에 없다")


@needs_font
class TestPdfRenderer:
    def test_satisfies_port(self) -> None:
        assert FONT is not None
        assert isinstance(PdfRenderer(font_path=FONT), ReportRenderer)

    def test_renders_valid_pdf(self, tmp_path: Path) -> None:
        assert FONT is not None
        output = PdfRenderer(font_path=FONT).render(DOCUMENT)
        raw = output.encode("latin-1")
        assert raw.startswith(b"%PDF-")
        assert b"%%EOF" in raw[-1024:]
        # 파일로 저장했을 때도 유효해야 한다 (ReportSink 경유 시나리오)
        target = tmp_path / "report.pdf"
        target.write_bytes(raw)
        assert target.stat().st_size > 1000


class TestFontDiscovery:
    def test_missing_font_path_rejected(self, tmp_path: Path) -> None:
        from pams.reporting.infrastructure import PdfRenderError

        with pytest.raises(PdfRenderError):
            PdfRenderer(font_path=tmp_path / "nope.ttf").render(DOCUMENT)
