"""AI 해설 도메인.

절대 원칙: AI(Claude)는 계산하지도, 판단하지도 않는다.
- 입력은 엔진이 이미 계산한 '사실(facts)' 문자열뿐이다.
- 출력은 해설 텍스트(Narrative)뿐이며, 어떤 엔진도 이 출력을 입력으로 삼지 않는다.
프롬프트의 제약 조항이 이 원칙을 모델에게 강제한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Protocol, runtime_checkable

from pams.shared_kernel.domain import DomainValidationError


@unique
class AnalysisKind(StrEnum):
    SUMMARY = "summary"  # 포트폴리오 현황 요약/설명
    RISK = "risk"  # 리스크 지표 해설
    MARKET = "market"  # 시장 지표가 포트폴리오에 미치는 영향 설명
    JOURNAL_DRAFT = "journal_draft"  # 투자일지 초안


@dataclass(frozen=True, slots=True)
class Narrative:
    """AI가 생성한 해설. 참고 자료일 뿐 어떤 계산/판정에도 쓰이지 않는다."""

    kind: AnalysisKind
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise DomainValidationError("해설 텍스트가 비어 있다")


@runtime_checkable
class TextCompletion(Protocol):
    """LLM 어댑터 포트. 구현은 infrastructure(Anthropic API 등)가 담당한다."""

    def complete(self, *, system_prompt: str, user_prompt: str) -> str: ...


_SYSTEM_PROMPT = """당신은 개인 자산운용 시스템(PAMS)의 분석 해설자다.

반드시 지켜야 하는 제약:
1. [사실] 목록에 있는 숫자만 인용한다. 새로운 숫자를 만들거나 재계산하지 않는다.
2. 매수/매도/비중 변경을 스스로 판단하거나 권유하지 않는다.
   리밸런싱 제안이 [사실]에 포함되어 있으면 그 내용을 설명만 한다.
3. 모든 판정은 Rule Engine이 이미 내렸다. 판정을 뒤집거나 재해석하지 않는다.
4. 한국어로, 간결하고 중립적으로 쓴다."""

_INSTRUCTIONS: dict[AnalysisKind, str] = {
    AnalysisKind.SUMMARY: "위 사실을 바탕으로 포트폴리오 현황을 요약해서 설명하라.",
    AnalysisKind.RISK: (
        "위 사실에 포함된 리스크 지표의 의미를 초보 투자자도 이해할 수 있게 설명하라."
    ),
    AnalysisKind.MARKET: "위 사실에 포함된 시장 지표가 이 포트폴리오에 미치는 영향을 설명하라.",
    AnalysisKind.JOURNAL_DRAFT: (
        "위 사실을 근거로 투자일지 초안을 작성하라. 무엇을/왜(규칙 근거)를 명확히 구분하라."
    ),
}


class PromptBuilder:
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def user_prompt(
        self, *, kind: AnalysisKind, facts: Sequence[str], note: str | None = None
    ) -> str:
        cleaned = [fact.strip() for fact in facts if fact.strip()]
        if not cleaned:
            raise DomainValidationError(
                "사실(facts)이 비어 있다 - AI가 숫자를 지어내는 것을 막기 위해 거부한다"
            )
        lines = ["[사실]", *[f"- {fact}" for fact in cleaned]]
        if note is not None and note.strip():
            lines += ["", "[사용자 메모]", note.strip()]
        lines += ["", "[요청]", _INSTRUCTIONS[kind]]
        return "\n".join(lines)
