"""유스케이스: 설정(config/market_regime)과 지표 관측값으로 시장 국면(4장)을 판정한다."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pams.market_regime.domain.regime import (
    MarketRegimeConfig,
    MarketRegimeResult,
    grade_market_regime,
)


@dataclass(frozen=True, slots=True)
class GradeMarketRegime:
    config: MarketRegimeConfig

    def execute(
        self, observations: Mapping[str, Decimal | str | None], *, as_of: date | None = None
    ) -> MarketRegimeResult:
        return grade_market_regime(observations, self.config, as_of=as_of)
