"""유스케이스: 설정(config/equity_scoring)과 입력값으로 기업 100점 점수를 산출한다."""

from __future__ import annotations

from dataclasses import dataclass

from pams.equity.domain.score import CompanyScoreReport
from pams.equity.domain.scoring_config import ScoringConfig
from pams.equity.domain.scoring_engine import CompanyScoreInputs, score_company


@dataclass(frozen=True, slots=True)
class ScoreCompany:
    config: ScoringConfig

    def execute(self, inputs: CompanyScoreInputs) -> CompanyScoreReport:
        return score_company(inputs, self.config)
