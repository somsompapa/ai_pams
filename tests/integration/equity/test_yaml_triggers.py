"""config/triggers/*.yaml → PriceTriggerPlan 로더 통합 테스트."""

from pathlib import Path

import pytest

from pams.equity.infrastructure import PriceTriggerConfigError, YamlPriceTriggerLoader
from pams.shared_kernel.domain import Currency, Money

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PATH = PROJECT_ROOT / "config" / "triggers" / "default.yaml"


class TestLoadDefault:
    def test_default_config_loads(self) -> None:
        plan = YamlPriceTriggerLoader(DEFAULT_PATH).load()
        assert plan.triggers


class TestParsing:
    def _load(self, tmp_path: Path, body: str) -> object:
        path = tmp_path / "t.yaml"
        path.write_text(body, encoding="utf-8")
        return YamlPriceTriggerLoader(path).load()

    def test_parses_three_lines(self, tmp_path: Path) -> None:
        plan = self._load(
            tmp_path,
            """
triggers:
  - asset_id: "KRX:005930"
    currency: KRW
    buy_at: "70000"
    take_profit_at: "90000"
    stop_loss_at: "60000"
""",
        )
        t = plan.trigger_for("KRX:005930")
        assert t is not None
        assert t.buy_at == Money.of("70000", Currency.KRW)
        assert t.take_profit_at == Money.of("90000", Currency.KRW)
        assert t.stop_loss_at == Money.of("60000", Currency.KRW)

    def test_legacy_sell_at_maps_to_take_profit(self, tmp_path: Path) -> None:
        plan = self._load(
            tmp_path,
            'triggers:\n  - {asset_id: "X", currency: KRW, buy_at: "70000", sell_at: "90000"}\n',
        )
        t = plan.trigger_for("X")
        assert t is not None
        assert t.take_profit_at == Money.of("90000", Currency.KRW)

    def test_buy_only(self, tmp_path: Path) -> None:
        plan = self._load(
            tmp_path,
            """
triggers:
  - {asset_id: "X", currency: USD, buy_at: "180"}
""",
        )
        t = plan.trigger_for("X")
        assert t is not None
        assert t.take_profit_at is None
        assert t.stop_loss_at is None

    def test_missing_currency_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PriceTriggerConfigError, match="currency|통화"):
            self._load(tmp_path, 'triggers:\n  - {asset_id: "X", buy_at: "1"}\n')

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(PriceTriggerConfigError):
            YamlPriceTriggerLoader(tmp_path / "nope.yaml").load()
