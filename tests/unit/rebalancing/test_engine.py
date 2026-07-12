"""RebalancingEngine 테스트.

시나리오: 총자산 10,000,000 KRW
- 목표: 미국주식 40%±5, 채권 40%±5, 현금 20%±5
- 현재: 미국주식 5,500,000(55%) / 채권 2,500,000(25%) / 현금 2,000,000(20%)
→ 미국주식 1,500,000 매도, 채권 1,500,000 매수, 현금은 잔여이므로 액션 없음
"""

from datetime import date

import pytest

from pams.rebalancing.domain import (
    CostModel,
    RebalancingEngine,
    TradeDirection,
    TradingCostRates,
)
from pams.shared_kernel.domain import (
    AllocationTarget,
    AssetClass,
    Currency,
    DomainValidationError,
    Money,
    Percentage,
)

AS_OF = date(2026, 7, 10)
KRW = Currency.KRW


def target(asset_class: AssetClass, percent: str, band: str = "5") -> AllocationTarget:
    return AllocationTarget(
        asset_class=asset_class,
        target=Percentage.from_percent(percent),
        band=Percentage.from_percent(band),
    )


TARGETS = (
    target(AssetClass.US_STOCK, "40"),
    target(AssetClass.BOND, "40"),
    target(AssetClass.CASH, "20"),
)
COSTS = CostModel(
    rates={
        AssetClass.US_STOCK: TradingCostRates(
            fee_rate=Percentage.from_ratio("0.001"),
            sell_tax_rate=Percentage.from_ratio("0.0005"),
        ),
        AssetClass.BOND: TradingCostRates(
            fee_rate=Percentage.from_ratio("0.0003"),
            sell_tax_rate=Percentage.zero(),
        ),
    },
    default=TradingCostRates(fee_rate=Percentage.zero(), sell_tax_rate=Percentage.zero()),
)


def propose(current: dict[AssetClass, str], targets: tuple[AllocationTarget, ...] = TARGETS):  # type: ignore[no-untyped-def]
    return RebalancingEngine().propose(
        as_of=AS_OF,
        base_currency=KRW,
        current_values={ac: Money.of(v, KRW) for ac, v in current.items()},
        targets=targets,
        costs=COSTS,
    )


OUT_OF_BAND = {
    AssetClass.US_STOCK: "5500000",
    AssetClass.BOND: "2500000",
    AssetClass.CASH: "2000000",
}
WITHIN_BAND = {
    AssetClass.US_STOCK: "4200000",
    AssetClass.BOND: "3900000",
    AssetClass.CASH: "1900000",
}


class TestNoActionCases:
    def test_within_band_produces_no_actions(self) -> None:
        proposal = propose(WITHIN_BAND)
        assert not proposal.is_rebalancing_needed
        assert proposal.actions == ()

    def test_exact_target_produces_no_actions(self) -> None:
        proposal = propose(
            {AssetClass.US_STOCK: "4000000", AssetClass.BOND: "4000000", AssetClass.CASH: "2000000"}
        )
        assert not proposal.is_rebalancing_needed


class TestOutOfBandRebalancing:
    def test_sell_overweight_to_target(self) -> None:
        proposal = propose(OUT_OF_BAND)
        sells = [a for a in proposal.actions if a.direction is TradeDirection.SELL]
        assert len(sells) == 1
        sell = sells[0]
        assert sell.asset_class is AssetClass.US_STOCK
        assert sell.amount == Money.of("1500000", KRW)
        assert sell.estimated_fee == Money.of("1500", KRW)
        assert sell.estimated_tax == Money.of("750", KRW)
        assert sell.current_weight == Percentage.from_percent(55)
        assert sell.target_weight == Percentage.from_percent(40)

    def test_buy_underweight_to_target(self) -> None:
        proposal = propose(OUT_OF_BAND)
        buys = [a for a in proposal.actions if a.direction is TradeDirection.BUY]
        assert len(buys) == 1
        buy = buys[0]
        assert buy.asset_class is AssetClass.BOND
        assert buy.amount == Money.of("1500000", KRW)
        assert buy.estimated_fee == Money.of("450", KRW)
        assert buy.estimated_tax == Money.zero(KRW)  # 매수에는 거래세가 없다

    def test_cash_class_never_generates_action(self) -> None:
        """현금은 매도/매수의 잔여로 조정된다 - '현금 매수' 액션은 없다."""
        proposal = propose(
            {AssetClass.US_STOCK: "4000000", AssetClass.BOND: "4000000", AssetClass.CASH: "2000000"}
        )
        cash_actions = [a for a in proposal.actions if a.asset_class.is_cash_like]
        assert cash_actions == []

    def test_sells_come_before_buys(self) -> None:
        """실행순서: 매도로 현금을 확보한 뒤 매수한다."""
        proposal = propose(OUT_OF_BAND)
        directions = [a.direction for a in proposal.actions]
        assert directions == sorted(directions, key=lambda d: 0 if d is TradeDirection.SELL else 1)

    def test_totals(self) -> None:
        proposal = propose(OUT_OF_BAND)
        assert proposal.total_sell_amount == Money.of("1500000", KRW)
        assert proposal.total_buy_amount == Money.of("1500000", KRW)
        assert proposal.total_estimated_cost == Money.of("2700", KRW)
        assert proposal.is_rebalancing_needed

    def test_buy_from_zero_position(self) -> None:
        """보유가 전혀 없는 자산군도 목표가 있으면 매수 제안된다."""
        proposal = propose({AssetClass.US_STOCK: "8000000", AssetClass.CASH: "2000000"})
        buys = {a.asset_class: a for a in proposal.actions if a.direction is TradeDirection.BUY}
        assert AssetClass.BOND in buys
        assert buys[AssetClass.BOND].amount == Money.of("4000000", KRW)
        assert buys[AssetClass.BOND].current_weight == Percentage.zero()


class TestValidation:
    def test_held_class_without_target_rejected(self) -> None:
        """목표에 없는 자산군 보유 = 정책 공백 - 조용히 무시하지 않는다."""
        with pytest.raises(DomainValidationError, match="crypto"):
            propose(
                {
                    AssetClass.US_STOCK: "4000000",
                    AssetClass.BOND: "3000000",
                    AssetClass.CRYPTO: "1000000",
                    AssetClass.CASH: "2000000",
                }
            )

    def test_zero_total_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            propose({})

    def test_multiple_actions_sorted_by_amount_desc(self) -> None:
        targets = (
            target(AssetClass.US_STOCK, "30", "2"),
            target(AssetClass.DOMESTIC_STOCK, "30", "2"),
            target(AssetClass.BOND, "20", "2"),
            target(AssetClass.GOLD, "10", "2"),
            target(AssetClass.CASH, "10", "2"),
        )
        proposal = propose(
            {
                AssetClass.US_STOCK: "5000000",  # 50% → -20%p 매도 2,000,000
                AssetClass.DOMESTIC_STOCK: "3600000",  # 36% → 매도 600,000
                AssetClass.BOND: "500000",  # 5% → 매수 1,500,000
                AssetClass.GOLD: "0400000",  # 4% → 매수 600,000
                AssetClass.CASH: "500000",
            },
            targets=targets,
        )
        sells = [a for a in proposal.actions if a.direction is TradeDirection.SELL]
        buys = [a for a in proposal.actions if a.direction is TradeDirection.BUY]
        assert [s.amount.amount for s in sells] == sorted(
            (s.amount.amount for s in sells), reverse=True
        )
        assert [b.amount.amount for b in buys] == sorted(
            (b.amount.amount for b in buys), reverse=True
        )
        assert len(sells) == 2 and len(buys) == 2


class TestCapitalGainsTax:
    """해외주식 매도 시 차익 기반 양도세: (차익 - 연공제) × 세율.

    시나리오: 총자산 10,000,000, 미국주식 목표 20%±0.
    미국주식 현재 6,000,000(60%) → 4,000,000 매도. 매도비율 2/3.
    """

    from pams.rebalancing.domain import CapitalGainsTax

    TARGETS_CG = (
        target(AssetClass.US_STOCK, "20", "0"),
        target(AssetClass.CASH, "80", "0"),
    )

    def costs_with_cg(self, exemption: str) -> CostModel:
        from pams.rebalancing.domain import CapitalGainsTax

        return CostModel(
            rates={
                AssetClass.US_STOCK: TradingCostRates(
                    fee_rate=Percentage.from_ratio("0.0025"),
                    sell_tax_rate=Percentage.zero(),
                    capital_gains=CapitalGainsTax(
                        rate=Percentage.from_ratio("0.22"),
                        annual_exemption=Money.of(exemption, KRW),
                    ),
                )
            },
            default=TradingCostRates(fee_rate=Percentage.zero(), sell_tax_rate=Percentage.zero()),
        )

    def propose_cg(self, cost_basis: str, exemption: str = "2500000"):  # type: ignore[no-untyped-def]
        return RebalancingEngine().propose(
            as_of=AS_OF,
            base_currency=KRW,
            current_values={
                AssetClass.US_STOCK: Money.of("6000000", KRW),
                AssetClass.CASH: Money.of("4000000", KRW),
            },
            targets=self.TARGETS_CG,
            costs=self.costs_with_cg(exemption),
            cost_bases={AssetClass.US_STOCK: Money.of(cost_basis, KRW)},
        )

    def test_gain_below_exemption_no_capital_gains_tax(self) -> None:
        # 취득원가 3,000,000 → 처분원가 2,000,000, 차익 2,000,000 < 공제 → 양도세 0
        action = self.propose_cg("3000000").actions[0]
        assert action.estimated_tax == Money.zero(KRW)
        assert action.estimated_fee == Money.of("10000", KRW)  # 4,000,000 × 0.0025

    def test_gain_above_exemption_taxed(self) -> None:
        # 취득원가 1,500,000 → 처분원가 1,000,000, 차익 3,000,000
        # 과세표준 3,000,000 - 2,500,000 = 500,000 × 0.22 = 110,000
        action = self.propose_cg("1500000").actions[0]
        assert action.estimated_tax == Money.of("110000", KRW)

    def test_no_cost_basis_falls_back_to_transaction_tax_only(self) -> None:
        """취득원가를 모르면 양도세를 추정하지 않는다 (거래세만)."""
        proposal = RebalancingEngine().propose(
            as_of=AS_OF,
            base_currency=KRW,
            current_values={
                AssetClass.US_STOCK: Money.of("6000000", KRW),
                AssetClass.CASH: Money.of("4000000", KRW),
            },
            targets=self.TARGETS_CG,
            costs=self.costs_with_cg("2500000"),
        )
        assert proposal.actions[0].estimated_tax == Money.zero(KRW)  # sell_tax_rate=0

    def test_buy_never_incurs_capital_gains(self) -> None:
        proposal = RebalancingEngine().propose(
            as_of=AS_OF,
            base_currency=KRW,
            current_values={
                AssetClass.US_STOCK: Money.of("1000000", KRW),
                AssetClass.CASH: Money.of("9000000", KRW),
            },
            targets=self.TARGETS_CG,
            costs=self.costs_with_cg("2500000"),
            cost_bases={AssetClass.US_STOCK: Money.of("500000", KRW)},
        )
        buy = proposal.actions[0]
        assert buy.direction is TradeDirection.BUY
        assert buy.estimated_tax == Money.zero(KRW)
