"""DCF 도메인 테스트. ai_stock 프로젝트에서 검증된 케이스를 이식(같은 값으로 회귀 검증)."""

from decimal import Decimal

import pytest

from pams.equity.domain.dcf import (
    DcfAssumptions,
    ValuationError,
    calculate_dcf,
    dcf_sensitivity,
    project_fcf,
    trigger_zones,
    valuation_gap,
)


class TestProjectFcf:
    def test_applies_growth_sequentially(self) -> None:
        fcfs = project_fcf(Decimal(100), [Decimal("0.10"), Decimal("0.10")])
        assert fcfs == (Decimal("110.0"), Decimal("121.00"))

    def test_empty_growth_path_rejected(self) -> None:
        with pytest.raises(ValuationError):
            project_fcf(Decimal(100), [])


class TestDcfAssumptions:
    def test_wacc_not_greater_than_terminal_growth_rejected(self) -> None:
        with pytest.raises(ValuationError):
            DcfAssumptions(
                base_fcf=Decimal(100),
                wacc=Decimal("0.02"),
                terminal_growth=Decimal("0.025"),
                growth_path=(Decimal("0.1"),),
            )

    def test_zero_shares_outstanding_rejected(self) -> None:
        with pytest.raises(ValuationError):
            DcfAssumptions(
                base_fcf=Decimal(100),
                wacc=Decimal("0.085"),
                terminal_growth=Decimal("0.025"),
                growth_path=(Decimal("0.1"),),
                shares_outstanding=Decimal(0),
            )


class TestCalculateDcf:
    def test_matches_ai_stock_reference_value(self) -> None:
        """ai_stock python/valuation.py __main__ 자기점검과 동일한 입력·기대값으로 회귀 검증
        (base_fcf=1000, wacc=8.5%, g=2.5%, growth_path=[12%,12%,10%,8%,8%](5년),
        net_debt=-500(순현금), shares=100 → fair_value_per_share ≈ 241.09, ai_stock에서
        실제로 산출·확인된 값과 동일해야 두 구현이 일치한다고 볼 수 있다)."""
        assumptions = DcfAssumptions(
            base_fcf=Decimal(1000),
            wacc=Decimal("0.085"),
            terminal_growth=Decimal("0.025"),
            growth_path=(
                Decimal("0.12"),
                Decimal("0.12"),
                Decimal("0.10"),
                Decimal("0.08"),
                Decimal("0.08"),
            ),
            net_debt=Decimal("-500"),
            shares_outstanding=Decimal(100),
        )
        result = calculate_dcf(assumptions)
        assert result.fair_value_per_share is not None
        assert abs(result.fair_value_per_share - Decimal("241.09")) < Decimal("0.05")

    def test_no_shares_outstanding_gives_no_per_share_value(self) -> None:
        assumptions = DcfAssumptions(
            base_fcf=Decimal(100),
            wacc=Decimal("0.085"),
            terminal_growth=Decimal("0.025"),
            growth_path=(Decimal("0.1"),),
        )
        result = calculate_dcf(assumptions)
        assert result.fair_value_per_share is None
        assert result.equity_value == result.enterprise_value  # net_debt 기본값 0


class TestDcfSensitivity:
    def test_nine_scenarios_and_center_matches_base_case(self) -> None:
        assumptions = DcfAssumptions(
            base_fcf=Decimal(100),
            wacc=Decimal("0.085"),
            terminal_growth=Decimal("0.025"),
            growth_path=(Decimal("0.1"),) * 5,
            shares_outstanding=Decimal(10),
        )
        grid = dcf_sensitivity(assumptions)
        assert len(grid) == 9
        assert grid["wacc0/g0"] == calculate_dcf(assumptions).fair_value_per_share


class TestValuationGap:
    def test_deeply_undervalued_scores_ten(self) -> None:
        gap = valuation_gap(Decimal(70), Decimal(100))
        assert gap.score == Decimal(10)
        assert gap.label == "크게 저평가"
        assert gap.buy_price_condition_met is True

    def test_overvalued_scores_zero_and_blocks_buy_condition(self) -> None:
        gap = valuation_gap(Decimal(120), Decimal(100))
        assert gap.score == Decimal(0)
        assert gap.buy_price_condition_met is False

    def test_fair_value_zero_or_negative_raises_instead_of_lying(self) -> None:
        """ai_stock v1.1에서 실제로 잡은 버그: 음수 fair_value가 그대로 계산되면
        '크게 저평가·10점'처럼 잘못된 매수신호가 나왔다. 여기서는 조용히 넘어가지 않고
        예외를 던져야 한다."""
        with pytest.raises(ValuationError):
            valuation_gap(Decimal(100), Decimal(-50))
        with pytest.raises(ValuationError):
            valuation_gap(Decimal(100), Decimal(0))


class TestTriggerZones:
    def test_zones_ordered_around_central_fair_value(self) -> None:
        assumptions = DcfAssumptions(
            base_fcf=Decimal(100),
            wacc=Decimal("0.085"),
            terminal_growth=Decimal("0.025"),
            growth_path=(Decimal("0.1"),) * 5,
            shares_outstanding=Decimal(10),
        )
        zones = trigger_zones(dcf_sensitivity(assumptions))
        assert zones.buy_high_confidence_upper <= zones.buy_base_case_upper
        assert zones.watch_lower <= zones.central_fair_value <= zones.watch_upper
        assert zones.sell_25pct_lower < zones.sell_50pct_lower

    def test_empty_grid_rejected(self) -> None:
        with pytest.raises(ValuationError):
            trigger_zones({"wacc0/g0": None})
