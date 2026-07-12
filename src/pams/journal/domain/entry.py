"""JournalEntry: 투자일지 - 무엇을, 왜(규칙 근거) 실행했는지의 기록."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pams.shared_kernel.domain import DomainValidationError


@dataclass(frozen=True, slots=True)
class JournalEntry:
    entry_id: str
    entry_date: date
    title: str
    what: str  # 무엇을 실행했는가
    why: str  # 왜 실행했는가 (판단 근거)
    rule_basis: str = ""  # 근거가 된 Rule id (기계적 실행이었다면 필수적으로 남긴다)
    ai_draft: str | None = None  # AI가 작성한 초안 (참고용 - 최종 기록은 사용자 몫)

    def __post_init__(self) -> None:
        if not self.entry_id.strip():
            raise DomainValidationError("entry_id는 비어 있을 수 없다")
        if not self.what.strip():
            raise DomainValidationError("'무엇을'(what)이 비어 있는 일지는 기록이 아니다")
        if not self.why.strip():
            raise DomainValidationError("'왜'(why)가 비어 있는 일지는 기록이 아니다")
