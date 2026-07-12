"""표현 중립 보고서 문서 모델.

문서는 렌더링 방식(Markdown/HTML/PDF)을 알지 못한다. 렌더러는 이 모델만
소비하므로, 새 출력 형식은 ReportRenderer 어댑터 추가만으로 지원된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pams.shared_kernel.domain import DomainValidationError


@dataclass(frozen=True, slots=True)
class Paragraph:
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise DomainValidationError("문단은 비어 있을 수 없다")


@dataclass(frozen=True, slots=True)
class KeyValueBlock:
    """라벨-값 목록 (예: 총자산: 10,000,000 KRW)."""

    items: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.items:
            raise DomainValidationError("키-값 블록이 비어 있다")


@dataclass(frozen=True, slots=True)
class TableBlock:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        if not self.headers:
            raise DomainValidationError("표에 헤더가 없다")
        for row in self.rows:
            if len(row) != len(self.headers):
                raise DomainValidationError(
                    f"표 행의 칸 수({len(row)})가 헤더 수({len(self.headers)})와 다르다: {row}"
                )


Block = Paragraph | KeyValueBlock | TableBlock


@dataclass(frozen=True, slots=True)
class Section:
    heading: str
    blocks: tuple[Block, ...]

    def __post_init__(self) -> None:
        if not self.heading.strip():
            raise DomainValidationError("섹션 제목은 비어 있을 수 없다")
        if not self.blocks:
            raise DomainValidationError(f"섹션 '{self.heading}'에 내용이 없다")


@dataclass(frozen=True, slots=True)
class ReportDocument:
    title: str
    as_of: date
    sections: tuple[Section, ...]

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise DomainValidationError("보고서 제목은 비어 있을 수 없다")
        if not self.sections:
            raise DomainValidationError("보고서에 섹션이 하나도 없다")
