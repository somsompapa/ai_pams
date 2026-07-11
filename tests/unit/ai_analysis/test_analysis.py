"""ai_analysis 컨텍스트 테스트.

핵심 계약:
- 프롬프트에 '계산/판단 금지' 제약이 항상 포함된다.
- AI에게는 엔진이 계산한 사실(facts)만 전달된다. 사실이 없으면 실패한다.
- 유스케이스는 TextCompletion 포트에만 의존한다.
"""

import pytest

from pams.ai_analysis.application import GenerateAnalysis
from pams.ai_analysis.domain import (
    AnalysisKind,
    Narrative,
    PromptBuilder,
    TextCompletion,
)
from pams.shared_kernel.domain import DomainValidationError

FACTS = (
    "총자산: 27,900,000 KRW",
    "주식성 자산 비중: 47.05%",
    "발동 규칙: max-single-position (단일 종목 비중 20% 초과)",
)


class TestPromptBuilder:
    def test_system_prompt_contains_hard_constraints(self) -> None:
        system = PromptBuilder().system_prompt()
        assert "계산" in system  # 재계산 금지
        assert "숫자" in system  # 숫자 창조 금지
        assert "판단" in system or "권유" in system  # 매매 판단/권유 금지

    def test_user_prompt_lists_facts(self) -> None:
        prompt = PromptBuilder().user_prompt(kind=AnalysisKind.SUMMARY, facts=FACTS)
        for fact in FACTS:
            assert fact in prompt

    def test_each_kind_has_distinct_instruction(self) -> None:
        builder = PromptBuilder()
        prompts = {kind: builder.user_prompt(kind=kind, facts=FACTS) for kind in AnalysisKind}
        assert len(set(prompts.values())) == len(AnalysisKind)

    def test_note_is_appended(self) -> None:
        prompt = PromptBuilder().user_prompt(
            kind=AnalysisKind.JOURNAL_DRAFT, facts=FACTS, note="IPS 규칙에 따라 매도했다"
        )
        assert "IPS 규칙에 따라 매도했다" in prompt

    def test_empty_facts_rejected(self) -> None:
        """사실 없이 생성하면 AI가 스스로 숫자를 지어낼 위험이 있다 - 금지."""
        with pytest.raises(DomainValidationError):
            PromptBuilder().user_prompt(kind=AnalysisKind.SUMMARY, facts=())
        with pytest.raises(DomainValidationError):
            PromptBuilder().user_prompt(kind=AnalysisKind.SUMMARY, facts=(" ",))


class RecordingCompletion:
    """TextCompletion 포트의 페이크 - 받은 프롬프트를 기록한다."""

    def __init__(self, reply: str = "포트폴리오는 안정적이다.") -> None:
        self.reply = reply
        self.system_prompts: list[str] = []
        self.user_prompts: list[str] = []

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompts.append(system_prompt)
        self.user_prompts.append(user_prompt)
        return self.reply


class TestGenerateAnalysis:
    def test_fake_satisfies_port(self) -> None:
        assert isinstance(RecordingCompletion(), TextCompletion)

    def test_returns_narrative(self) -> None:
        completion = RecordingCompletion()
        narrative = GenerateAnalysis(completion=completion).execute(
            kind=AnalysisKind.SUMMARY, facts=FACTS
        )
        assert isinstance(narrative, Narrative)
        assert narrative.kind is AnalysisKind.SUMMARY
        assert narrative.text == "포트폴리오는 안정적이다."

    def test_constraints_always_sent(self) -> None:
        completion = RecordingCompletion()
        GenerateAnalysis(completion=completion).execute(kind=AnalysisKind.RISK, facts=FACTS)
        assert len(completion.system_prompts) == 1
        assert "숫자" in completion.system_prompts[0]
        assert FACTS[0] in completion.user_prompts[0]

    def test_blank_reply_rejected(self) -> None:
        completion = RecordingCompletion(reply="   ")
        with pytest.raises(DomainValidationError):
            GenerateAnalysis(completion=completion).execute(kind=AnalysisKind.SUMMARY, facts=FACTS)
