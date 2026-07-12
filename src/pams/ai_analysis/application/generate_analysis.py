"""유스케이스: 엔진이 계산한 사실 목록으로 AI 해설을 생성한다."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pams.ai_analysis.domain import AnalysisKind, Narrative, PromptBuilder, TextCompletion


@dataclass(frozen=True, slots=True)
class GenerateAnalysis:
    completion: TextCompletion
    prompts: PromptBuilder = field(default_factory=PromptBuilder)

    def execute(
        self, *, kind: AnalysisKind, facts: Sequence[str], note: str | None = None
    ) -> Narrative:
        text = self.completion.complete(
            system_prompt=self.prompts.system_prompt(),
            user_prompt=self.prompts.user_prompt(kind=kind, facts=facts, note=note),
        )
        return Narrative(kind=kind, text=text)
