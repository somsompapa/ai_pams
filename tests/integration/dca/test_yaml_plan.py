"""config/dca/*.yaml → DcaPlan 로더 통합 테스트."""

from datetime import date
from pathlib import Path

import pytest

from pams.dca.infrastructure import DcaConfigError, YamlDcaPlanLoader
from pams.shared_kernel.domain import Currency, Money

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PATH = PROJECT_ROOT / "config" / "dca" / "default.yaml"


class TestLoadDefault:
    def test_default_config_loads(self) -> None:
        plan = YamlDcaPlanLoader(DEFAULT_PATH).load()
        assert plan.entries  # 비어 있지 않다


class TestParsing:
    def _load(self, tmp_path: Path, body: str) -> object:
        path = tmp_path / "dca.yaml"
        path.write_text(body, encoding="utf-8")
        return YamlDcaPlanLoader(path).load()

    def test_amount_and_weekly_quantity(self, tmp_path: Path) -> None:
        plan = self._load(
            tmp_path,
            """
entries:
  - asset_id: "NYSEARCA:SCHD"
    frequency: daily
    amount: "70000"
    currency: KRW
  - asset_id: "KRX:069500"
    frequency: weekly
    weekday: monday
    quantity: "1"
""",
        )
        monday = date(2026, 7, 13)
        tuesday = date(2026, 7, 14)
        assert {o.asset_id for o in plan.due_on(monday)} == {"NYSEARCA:SCHD", "KRX:069500"}
        assert {o.asset_id for o in plan.due_on(tuesday)} == {"NYSEARCA:SCHD"}
        assert plan.amount_totals()[Currency.KRW] == Money.of("70000", Currency.KRW)

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(DcaConfigError):
            YamlDcaPlanLoader(tmp_path / "nope.yaml").load()

    def test_amount_without_currency_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(DcaConfigError, match="currency|통화"):
            self._load(
                tmp_path,
                """
entries:
  - asset_id: "X"
    frequency: daily
    amount: "1000"
""",
            )

    def test_unknown_weekday_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(DcaConfigError, match="weekday|요일"):
            self._load(
                tmp_path,
                """
entries:
  - asset_id: "X"
    frequency: weekly
    weekday: funday
    quantity: "1"
""",
            )

    def test_amount_and_quantity_together_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(DcaConfigError):
            self._load(
                tmp_path,
                """
entries:
  - asset_id: "X"
    frequency: daily
    amount: "1000"
    currency: KRW
    quantity: "1"
""",
            )
