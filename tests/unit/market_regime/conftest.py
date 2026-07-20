"""market_regime 도메인 테스트 공용 픽스처 — market_analysis_rules.md 4-1 실제 임계값으로
구성한 MarketRegimeConfig. config/market_regime/default.yaml과 값이 같아야 한다."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pams.market_regime.domain.regime import MarketRegimeConfig
from pams.shared_kernel.domain import (
    Band,
    BandDirection,
    BandTable,
    CategoricalOption,
    CategoricalTable,
)


@pytest.fixture
def regime_config() -> MarketRegimeConfig:
    return MarketRegimeConfig(
        vix=BandTable(
            metric="VIX",
            max_score=Decimal(4),
            direction=BandDirection.LOWER_IS_BETTER,
            bands=(
                Band(bound=Decimal(15), score=Decimal(0), label="A:<15"),
                Band(bound=Decimal(20), score=Decimal(1), label="B:15~20"),
                Band(bound=Decimal(25), score=Decimal(2), label="C:20~25"),
                Band(bound=Decimal(35), score=Decimal(3), label="D:25~35"),
                Band(bound=Decimal("Infinity"), score=Decimal(4), label="E:>35"),
            ),
        ),
        circuit_breaker=BandTable(
            metric="서킷브레이커",
            max_score=Decimal(4),
            direction=BandDirection.HIGHER_IS_BETTER,
            bands=(
                Band(bound=Decimal("-5.0"), score=Decimal(2), label="C:급락 없음(중립)"),
                Band(bound=Decimal("-8.0"), score=Decimal(3), label="D:-5%~-8% 미만"),
                Band(bound=Decimal("-Infinity"), score=Decimal(4), label="E:-8% 이상"),
            ),
        ),
        treasury_10y=CategoricalTable(
            metric="미국 10년물 금리 변화",
            max_score=Decimal(4),
            options={
                "stable_or_down": CategoricalOption(score=Decimal(0), label="A:안정/하락"),
                "mild_up": CategoricalOption(score=Decimal(1), label="B:완만 상승"),
                "flat": CategoricalOption(score=Decimal(2), label="C:횡보"),
                "spike": CategoricalOption(score=Decimal(3), label="D:급등(+30bp↑)"),
                "spike_continued": CategoricalOption(score=Decimal(4), label="E:급등 지속"),
            },
        ),
        sp500_per=CategoricalTable(
            metric="S&P500 PER",
            max_score=Decimal(4),
            options={
                "lower_mid": CategoricalOption(score=Decimal(0), label="A:밴드 하단~중단"),
                "mid": CategoricalOption(score=Decimal(1), label="B:중단"),
                "upper_mid": CategoricalOption(score=Decimal(2), label="C:중상단"),
                "near_upper": CategoricalOption(score=Decimal(3), label="D:상단 근접"),
                "above_upper": CategoricalOption(score=Decimal(4), label="E:상단 초과"),
            },
        ),
        kospi_foreign_flow=CategoricalTable(
            metric="KOSPI 외국인 수급",
            max_score=Decimal(4),
            options={
                "net_buy": CategoricalOption(score=Decimal(0), label="A:순매수 지속"),
                "turning_buy": CategoricalOption(score=Decimal(1), label="B:순매수 전환"),
                "mixed": CategoricalOption(score=Decimal(2), label="C:혼조"),
                "turning_sell": CategoricalOption(score=Decimal(3), label="D:순매도 전환"),
                "heavy_sell": CategoricalOption(score=Decimal(4), label="E:대량 순매도"),
            },
        ),
        sources={
            "vix": "yfinance ^VIX",
            "circuit_breaker": "KOSPI 등락률 파생",
            "treasury_10y": "yfinance/수동",
            "sp500_per": "yfinance 근사/수동",
            "kospi_foreign_flow": "수동/대화 검색",
        },
    )
