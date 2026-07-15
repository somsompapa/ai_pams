"""config/stock_targets/*.yaml → StockTargetPlan 로더 통합 테스트."""

from pathlib import Path

import pytest

from pams.equity.domain import StockTarget
from pams.equity.infrastructure import (
    StockTargetConfigError,
    YamlStockTargetLoader,
    delete_stock_target,
    save_stock_target,
)
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


class TestSaveStockTarget:
    def test_create_file_and_add(self, tmp_path: Path) -> None:
        path = tmp_path / "targets.yaml"
        save_stock_target(
            path,
            StockTarget(
                asset_id="KRX:005930",
                target=Percentage.from_percent("40"),
                buy_band=Percentage.from_percent("8"),
                sell_band=Percentage.from_percent("10"),
            ),
        )
        plan = YamlStockTargetLoader(path).load()
        t = plan.target_for("KRX:005930")
        assert t is not None
        assert t.target == Percentage.from_percent("40")
        assert t.buy_band == Percentage.from_percent("8")
        assert t.sell_band == Percentage.from_percent("10")

    def test_upsert_replaces_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "targets.yaml"
        save_stock_target(
            path,
            StockTarget(
                asset_id="KRX:005930",
                target=Percentage.from_percent("40"),
                buy_band=Percentage.from_percent("8"),
                sell_band=Percentage.from_percent("8"),
            ),
        )
        save_stock_target(
            path,
            StockTarget(
                asset_id="KRX:005930",
                target=Percentage.from_percent("50"),
                buy_band=Percentage.from_percent("5"),
                sell_band=Percentage.from_percent("5"),
            ),
        )
        plan = YamlStockTargetLoader(path).load()
        assert len([t for t in plan.targets if t.asset_id == "KRX:005930"]) == 1
        t = plan.target_for("KRX:005930")
        assert t is not None and t.target == Percentage.from_percent("50")

    def test_keeps_other_targets(self, tmp_path: Path) -> None:
        path = tmp_path / "targets.yaml"
        save_stock_target(
            path,
            StockTarget(
                asset_id="KRX:005930",
                target=Percentage.from_percent("40"),
                buy_band=Percentage.from_percent("8"),
                sell_band=Percentage.from_percent("8"),
            ),
        )
        save_stock_target(
            path,
            StockTarget(
                asset_id="NASDAQ:AAPL",
                target=Percentage.from_percent("60"),
                buy_band=Percentage.from_percent("8"),
                sell_band=Percentage.from_percent("8"),
            ),
        )
        plan = YamlStockTargetLoader(path).load()
        assert {t.asset_id for t in plan.targets} == {"KRX:005930", "NASDAQ:AAPL"}


class TestDeleteStockTarget:
    def test_removes_matching_target(self, tmp_path: Path) -> None:
        path = tmp_path / "targets.yaml"
        save_stock_target(
            path,
            StockTarget(
                asset_id="KRX:005930",
                target=Percentage.from_percent("40"),
                buy_band=Percentage.from_percent("8"),
                sell_band=Percentage.from_percent("8"),
            ),
        )
        save_stock_target(
            path,
            StockTarget(
                asset_id="NASDAQ:AAPL",
                target=Percentage.from_percent("60"),
                buy_band=Percentage.from_percent("8"),
                sell_band=Percentage.from_percent("8"),
            ),
        )
        delete_stock_target(path, "KRX:005930")
        plan = YamlStockTargetLoader(path).load()
        assert {t.asset_id for t in plan.targets} == {"NASDAQ:AAPL"}

    def test_unknown_asset_id_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "targets.yaml"
        save_stock_target(
            path,
            StockTarget(
                asset_id="KRX:005930",
                target=Percentage.from_percent("40"),
                buy_band=Percentage.from_percent("8"),
                sell_band=Percentage.from_percent("8"),
            ),
        )
        with pytest.raises(StockTargetConfigError, match="찾을 수 없다"):
            delete_stock_target(path, "NOPE")

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(StockTargetConfigError, match="찾을 수 없다"):
            delete_stock_target(tmp_path / "nope.yaml", "KRX:005930")
