"""ReportDocument(표현 중립 보고서 문서 모델) 테스트."""

from datetime import date

import pytest

from pams.reporting.domain import (
    KeyValueBlock,
    Paragraph,
    ReportDocument,
    Section,
    TableBlock,
)
from pams.shared_kernel.domain import DomainValidationError

AS_OF = date(2026, 7, 10)


def section() -> Section:
    return Section(
        heading="요약",
        blocks=(
            Paragraph(text="2026년 7월 보고서."),
            KeyValueBlock(items=(("총자산", "10,000,000 KRW"),)),
            TableBlock(headers=("자산군", "비중"), rows=(("미국주식", "40.00%"),)),
        ),
    )


class TestValidation:
    def test_valid_document(self) -> None:
        document = ReportDocument(title="월간 투자 보고서", as_of=AS_OF, sections=(section(),))
        assert document.sections[0].heading == "요약"

    def test_empty_title_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            ReportDocument(title=" ", as_of=AS_OF, sections=(section(),))

    def test_document_without_sections_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            ReportDocument(title="보고서", as_of=AS_OF, sections=())

    def test_empty_heading_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            Section(heading="", blocks=(Paragraph(text="x"),))

    def test_table_row_width_must_match_headers(self) -> None:
        with pytest.raises(DomainValidationError):
            TableBlock(headers=("a", "b"), rows=(("only-one",),))

    def test_empty_paragraph_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            Paragraph(text="  ")
