"""가격 트리거 저장(upsert) 통합 테스트."""

from pathlib import Path

from pams.equity.domain import PriceTrigger
from pams.equity.infrastructure import YamlPriceTriggerLoader, save_price_trigger
from pams.shared_kernel.domain import Currency, Money


def krw(v: str) -> Money:
    return Money.of(v, Currency.KRW)


class TestSavePriceTrigger:
    def test_create_file_and_add(self, tmp_path: Path) -> None:
        path = tmp_path / "triggers.yaml"
        save_price_trigger(
            path,
            PriceTrigger(
                "KRX:005930",
                buy_at=krw("70000"),
                take_profit_at=krw("90000"),
                stop_loss_at=krw("60000"),
            ),
        )
        plan = YamlPriceTriggerLoader(path).load()
        t = plan.trigger_for("KRX:005930")
        assert t is not None
        assert t.buy_at == krw("70000")
        assert t.take_profit_at == krw("90000")
        assert t.stop_loss_at == krw("60000")

    def test_upsert_replaces_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "triggers.yaml"
        save_price_trigger(path, PriceTrigger("KRX:005930", buy_at=krw("70000")))
        save_price_trigger(
            path, PriceTrigger("KRX:005930", buy_at=krw("65000"), take_profit_at=krw("88000"))
        )
        plan = YamlPriceTriggerLoader(path).load()
        assert len([t for t in plan.triggers if t.asset_id == "KRX:005930"]) == 1
        t = plan.trigger_for("KRX:005930")
        assert t is not None and t.buy_at == krw("65000") and t.take_profit_at == krw("88000")

    def test_keeps_other_triggers(self, tmp_path: Path) -> None:
        path = tmp_path / "triggers.yaml"
        save_price_trigger(path, PriceTrigger("KRX:005930", buy_at=krw("70000")))
        save_price_trigger(path, PriceTrigger("NASDAQ:AAPL", buy_at=Money.of("180", Currency.USD)))
        plan = YamlPriceTriggerLoader(path).load()
        assert {t.asset_id for t in plan.triggers} == {"KRX:005930", "NASDAQ:AAPL"}
