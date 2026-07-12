"""리스크 파라미터 YAML 로더 통합 테스트."""

from decimal import Decimal
from pathlib import Path

import pytest

from pams.risk.infrastructure import RiskConfigError, YamlRiskParametersLoader

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PATH = PROJECT_ROOT / "config" / "risk" / "default.yaml"


class TestLoadDefault:
    def test_load_succeeds(self) -> None:
        params = YamlRiskParametersLoader(DEFAULT_PATH).load()
        assert params.periods_per_year == 252
        assert isinstance(params.risk_free_rate, Decimal)
        assert Decimal("0.5") < params.var_confidence < Decimal(1)


class TestErrors:
    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(RiskConfigError):
            YamlRiskParametersLoader(tmp_path / "nope.yaml").load()

    def test_missing_key(self, tmp_path: Path) -> None:
        bad = tmp_path / "risk.yaml"
        bad.write_text("periods_per_year: 252\n", encoding="utf-8")
        with pytest.raises(RiskConfigError, match="risk_free_rate"):
            YamlRiskParametersLoader(bad).load()

    def test_domain_violation_wrapped(self, tmp_path: Path) -> None:
        bad = tmp_path / "risk.yaml"
        bad.write_text(
            'periods_per_year: 252\nrisk_free_rate: "0.03"\nvar_confidence: "1.5"\n',
            encoding="utf-8",
        )
        with pytest.raises(RiskConfigError):
            YamlRiskParametersLoader(bad).load()
