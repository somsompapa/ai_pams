"""거래비용 YAML 로더 통합 테스트."""

from pathlib import Path

import pytest

from pams.rebalancing.infrastructure import CostConfigError, YamlCostModelLoader
from pams.shared_kernel.domain import AssetClass, Percentage

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PATH = PROJECT_ROOT / "config" / "costs" / "default.yaml"


class TestLoadDefault:
    def test_load_succeeds(self) -> None:
        model = YamlCostModelLoader(DEFAULT_PATH).load()
        domestic = model.rates_for(AssetClass.DOMESTIC_STOCK)
        assert domestic.sell_tax_rate > Percentage.zero()
        # 정의되지 않은 자산군은 default로 폴백
        assert model.rates_for(AssetClass.PENSION) == model.default


class TestErrors:
    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(CostConfigError):
            YamlCostModelLoader(tmp_path / "nope.yaml").load()

    def test_missing_default_section(self, tmp_path: Path) -> None:
        bad = tmp_path / "costs.yaml"
        bad.write_text("costs: []\n", encoding="utf-8")
        with pytest.raises(CostConfigError, match="default"):
            YamlCostModelLoader(bad).load()

    def test_unknown_asset_class(self, tmp_path: Path) -> None:
        bad = tmp_path / "costs.yaml"
        bad.write_text(
            """
default:
  fee_rate: "0"
  sell_tax_rate: "0"
costs:
  - asset_class: real_estate
    fee_rate: "0.001"
    sell_tax_rate: "0"
""",
            encoding="utf-8",
        )
        with pytest.raises(CostConfigError, match="real_estate"):
            YamlCostModelLoader(bad).load()
