"""config/stock_targets/*.yaml → StockTargetPlan 로더 통합 테스트."""

from pathlib import Path

import pytest

from pams.equity.infrastructure import StockTargetConfigError, YamlStockTargetLoader
from pams.shared_kernel.domain import Percentage

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PATH = PROJECT_ROOT / "config" / "stock_targets" / "default.yaml"


class TestLoadDefault:
    def test_default_config_loads(self) -> None:
        plan = YamlStockTargetLoader(DEFAULT_PATH).load()
        assert plan.targets


class TestParsing:
    def _load(self, tmp_path: Path, body: str) -> object:
        path = tmp_path / "st.yaml"
        path.write_text(body, encoding="utf-8")
        return YamlStockTargetLoader(path).load()

    def test_parses_target_and_bands(self, tmp_path: Path) -> None:
        plan = self._load(
            tmp_path,
            """
targets:
  - asset_id: "NASDAQ:AAPL"
    target_percent: "40"
    buy_band: "5"
    sell_band: "8"
""",
        )
        t = plan.target_for("NASDAQ:AAPL")
        assert t is not None
        assert t.target == Percentage.from_percent("40")
        assert t.buy_trigger == Percentage.from_percent("35")
        assert t.sell_trigger == Percentage.from_percent("48")

    def test_band_defaults_to_symmetric_when_only_band_given(self, tmp_path: Path) -> None:
        plan = self._load(
            tmp_path,
            """
targets:
  - asset_id: "X"
    target_percent: "10"
    band: "3"
""",
        )
        t = plan.target_for("X")
        assert t is not None
        assert t.buy_band == Percentage.from_percent("3")
        assert t.sell_band == Percentage.from_percent("3")

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(StockTargetConfigError):
            YamlStockTargetLoader(tmp_path / "nope.yaml").load()

    def test_missing_target_percent_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(StockTargetConfigError, match="target_percent|목표"):
            self._load(
                tmp_path,
                """
targets:
  - asset_id: "X"
    band: "3"
""",
            )
