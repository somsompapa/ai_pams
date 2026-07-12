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


class TestCapitalGainsTax:
    def test_below_exemption_is_zero(self) -> None:
        from pams.rebalancing.domain import CapitalGainsTax

        tax = CapitalGainsTax(
            rate=Percentage.from_ratio("0.22"),
            annual_exemption=Money.of("2500000", Currency.KRW),
        )
        # 차익 2,000,000 < 공제 2,500,000 → 0
        assert tax.on_gain(Money.of("2000000", Currency.KRW)) == Money.zero(Currency.KRW)

    def test_above_exemption_taxes_excess(self) -> None:
        from pams.rebalancing.domain import CapitalGainsTax

        tax = CapitalGainsTax(
            rate=Percentage.from_ratio("0.22"),
            annual_exemption=Money.of("2500000", Currency.KRW),
        )
        # (3,000,000 - 2,500,000) × 0.22 = 110,000
        assert tax.on_gain(Money.of("3000000", Currency.KRW)) == Money.of("110000", Currency.KRW)

    def test_loss_is_not_taxed(self) -> None:
        from pams.rebalancing.domain import CapitalGainsTax

        tax = CapitalGainsTax(
            rate=Percentage.from_ratio("0.22"),
            annual_exemption=Money.of("2500000", Currency.KRW),
        )
        assert tax.on_gain(Money.of("-500000", Currency.KRW)) == Money.zero(Currency.KRW)

    def test_negative_rate_or_exemption_rejected(self) -> None:
        from pams.rebalancing.domain import CapitalGainsTax

        with pytest.raises(DomainValidationError):
            CapitalGainsTax(
                rate=Percentage.from_ratio("-0.1"),
                annual_exemption=Money.of("2500000", Currency.KRW),
            )
        with pytest.raises(DomainValidationError):
            CapitalGainsTax(
                rate=Percentage.from_ratio("0.22"),
                annual_exemption=Money.of("-1", Currency.KRW),
            )
