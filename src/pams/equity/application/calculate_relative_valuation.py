"""유스케이스: PER/PBR 5년 밴드 백분위 + PEG로 상대지표 점수를 산출한다."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pams.equity.domain.relative_valuation import (
    RelativeValuationConfig,
    RelativeValuationResult,
    relative_valuation_score,
)


@dataclass(frozen=True, slots=True)
class CalculateRelativeValuation:
    config: RelativeValuationConfig

    def execute(
        self,
        *,
        per_band_percentile: Decimal | None,
        pbr_band_percentile: Decimal | None,
        peg: Decimal | None,
    ) -> RelativeValuationResult:
        return relative_valuation_score(per_band_percentile, pbr_band_percentile, peg, self.config)
