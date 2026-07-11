"""PDF 렌더러 (fpdf2 기반).

한글을 지원하려면 TTF 폰트 경로를 주입해야 한다 (find_korean_font()가
시스템에서 후보를 찾는다 - 하드코딩 없음).

주의: ReportRenderer 포트는 str을 반환하므로 PDF 바이너리는 latin-1로
매핑된 문자열로 반환한다. 파일로 저장할 때는 반드시
`render(document).encode("latin-1")`을 바이너리 모드로 써야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from pams.reporting.domain import (
    Block,
    KeyValueBlock,
    Paragraph,
    ReportDocument,
    TableBlock,
)

_FONT_FAMILY = "PamsKorean"

# 잘 알려진 한글 폰트 설치 경로 후보 (앞에서부터 탐색)
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
)


class PdfRenderError(Exception):
    """PDF 렌더링에 실패했다 (폰트 누락 등)."""


def find_korean_font() -> Path | None:
    """시스템에서 한글 TTF 폰트를 찾는다. 없으면 None."""
    for candidate in _FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file() and path.suffix.lower() == ".ttf":
            return path
    nanum_dir = Path("/usr/share/fonts/truetype/nanum")
    if nanum_dir.is_dir():
        fonts = sorted(nanum_dir.glob("*.ttf"))
        if fonts:
            return fonts[0]
    return None


@dataclass(frozen=True, slots=True)
class PdfRenderer:
    font_path: Path

    def render(self, document: ReportDocument) -> str:
        if not self.font_path.is_file():
            raise PdfRenderError(f"폰트 파일이 없다: {self.font_path}")

        pdf = FPDF()
        pdf.add_font(_FONT_FAMILY, "", str(self.font_path))
        pdf.add_font(_FONT_FAMILY, "B", str(self.font_path))
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        pdf.set_font(_FONT_FAMILY, "B", 18)
        pdf.multi_cell(0, 10, document.title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font(_FONT_FAMILY, "", 10)
        pdf.multi_cell(
            0, 8, f"기준일: {document.as_of.isoformat()}", new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
        pdf.ln(4)

        for section in document.sections:
            pdf.set_font(_FONT_FAMILY, "B", 13)
            pdf.multi_cell(0, 9, section.heading, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font(_FONT_FAMILY, "", 10)
            for block in section.blocks:
                self._render_block(pdf, block)
            pdf.ln(3)

        return bytes(pdf.output()).decode("latin-1")

    def _render_block(self, pdf: FPDF, block: Block) -> None:
        if isinstance(block, Paragraph):
            pdf.multi_cell(0, 7, block.text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1)
        elif isinstance(block, KeyValueBlock):
            for label, value in block.items:
                pdf.multi_cell(0, 7, f"· {label}: {value}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1)
        else:
            self._render_table(pdf, block)

    @staticmethod
    def _render_table(pdf: FPDF, table_block: TableBlock) -> None:
        with pdf.table() as table:
            header = table.row()
            for cell in table_block.headers:
                header.cell(cell)
            for cells in table_block.rows:
                row = table.row()
                for cell in cells:
                    row.cell(cell)
        pdf.ln(2)
