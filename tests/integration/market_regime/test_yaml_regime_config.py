"""config/market_regime/default.yaml이 실제로 파싱되고, 도메인 테스트의 in-Python
픽스처(tests/unit/market_regime/conftest.py)와 동일한 판정 결과를 내는지 확인한다."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from pams.market_regime.domain.grade import Grade
from pams.market_regime.domain.regime import (
    CIRCUIT_BREAKER,
    KOSPI_FOREIGN_FLOW,
    SP500_PER,
    TREASURY_10Y,
    VIX,
    grade_market_regime,
)
from pams.market_regime.infrastructure.yaml_regime_config import YamlMarketRegimeConfigLoader

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "market_regime" / "default.yaml"


class TestYamlMarketRegimeConfigLoader:
    def test_loads_and_reproduces_rulebook_example_1(self) -> None:
        config = YamlMarketRegimeConfigLoader(_CONFIG_PATH).load()
        observations = {
            VIX: Decimal("13"),
            TREASURY_10Y: "stable_or_down",
            SP500_PER: "mid",
            KOSPI_FOREIGN_FLOW: "net_buy",
            CIRCUIT_BREAKER: Decimal("0"),
        }
        result = grade_market_regime(observations, config, as_of=date(2026, 7, 17))
        assert result.final_grade == Grade.A

    def test_loads_and_reproduces_rulebook_example_2_tie(self) -> None:
        config = YamlMarketRegimeConfigLoader(_CONFIG_PATH).load()
        observations = {
            VIX: Decimal("22"),
            TREASURY_10Y: "spike",
            SP500_PER: "near_upper",
            KOSPI_FOREIGN_FLOW: "turning_buy",
            CIRCUIT_BREAKER: Decimal("0"),
        }
        result = grade_market_regime(observations, config, as_of=date(2026, 7, 17))
        assert result.final_grade == Grade.D
        assert result.tie_broken is True

    def test_min_indicators_required_defaults_to_three(self) -> None:
        config = YamlMarketRegimeConfigLoader(_CONFIG_PATH).load()
        assert config.min_indicators_required == 3
