"""CostModel(거래비용 모델) 테스트."""

import pytest

from pams.rebalancing.domain import CostModel, TradingCostRates
from pams.shared_kernel.domain import (
    AssetClass,
    Currency,
    DomainValidationError,
    Money,
    Percentage,
)


def rates(fee: str, sell_tax: str) -> TradingCostRates:
    return TradingCostRates(
        fee_rate=Percentage.from_ratio(fee), sell_tax_rate=Percentage.from_ratio(sell_tax)
    )


class TestTradingCostRates:
    def test_negative_rate_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            rates("-0.001", "0")
        with pytest.raises(DomainValidationError):
            rates("0", "-0.001")


class TestCostModel:
    MODEL = CostModel(
        rates={AssetClass.DOMESTIC_STOCK: rates("0.00015", "0.0018")},
        default=rates("0.001", "0"),
    )

    def test_known_asset_class_uses_specific_rates(self) -> None:
        found = self.MODEL.rates_for(AssetClass.DOMESTIC_STOCK)
        assert found.fee_rate == Percentage.from_ratio("0.00015")
        assert found.sell_tax_rate == Percentage.from_ratio("0.0018")

    def test_unknown_asset_class_falls_back_to_default(self) -> None:
        found = self.MODEL.rates_for(AssetClass.GOLD)
        assert found.fee_rate == Percentage.from_ratio("0.001")

    def test_cost_estimation(self) -> None:
        amount = Money.of("1000000", Currency.KRW)
        cost_rates = self.MODEL.rates_for(AssetClass.DOMESTIC_STOCK)
        assert cost_rates.fee_rate.of(amount) == Money.of("150", Currency.KRW)
        assert cost_rates.sell_tax_rate.of(amount) == Money.of("1800", Currency.KRW)
