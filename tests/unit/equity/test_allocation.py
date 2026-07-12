"""주식 슬리브 내 종목별 목표비중·매수/매도 트리거 도메인 테스트.

Tier 1(IPS)이 '주식 = 자산 대비 N%'를 정하면, Tier 2(여기)는 그 주식 슬리브
안에서 '삼성전자 = 주식 대비 M%'를 정하고 밴드를 벗어나면 매수/매도 신호를 낸다.
시스템은 신호까지만 내고 실제 매매는 사용자가 한다.
"""

import pytest

from pams.equity.domain import (
    EvaluateStockAllocation,
    StockSignal,
    StockTarget,
    StockTargetPlan,
)
from pams.shared_kernel.domain import Currency, DomainValidationError, Money, Percentage


def pct(v: str) -> Percentage:
    return Percentage.from_percent(v)


class TestStockTarget:
    def test_triggers_from_target_and_bands(self) -> None:
        t = StockTarget(asset_id="X", target=pct("10"), buy_band=pct("2"), sell_band=pct("3"))
        assert t.buy_trigger == pct("8")  # target - buy_band
        assert t.sell_trigger == pct("13")  # target + sell_band

    def test_signal_buy_when_at_or_below_buy_trigger(self) -> None:
        t = StockTarget(asset_id="X", target=pct("10"), buy_band=pct("2"), sell_band=pct("2"))
        assert t.signal(pct("7")) is StockSignal.BUY
        assert t.signal(pct("8")) is StockSignal.BUY  # 경계 포함

    def test_signal_sell_when_at_or_above_sell_trigger(self) -> None:
        t = StockTarget(asset_id="X", target=pct("10"), buy_band=pct("2"), sell_band=pct("2"))
        assert t.signal(pct("13")) is StockSignal.SELL
        assert t.signal(pct("12")) is StockSignal.SELL  # 경계 포함

    def test_signal_hold_within_band(self) -> None:
        t = StockTarget(asset_id="X", target=pct("10"), buy_band=pct("2"), sell_band=pct("2"))
        assert t.signal(pct("10")) is StockSignal.HOLD
        assert t.signal(pct("9")) is StockSignal.HOLD

    def test_negative_band_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            StockTarget(asset_id="X", target=pct("10"), buy_band=pct("-1"), sell_band=pct("2"))

    def test_empty_asset_id_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            StockTarget(asset_id=" ", target=pct("10"), buy_band=pct("2"), sell_band=pct("2"))


class TestStockTargetPlan:
    def test_duplicate_asset_rejected(self) -> None:
        with pytest.raises(DomainValidationError, match="중복"):
            StockTargetPlan(
                targets=(
                    StockTarget("X", pct("10"), pct("2"), pct("2")),
                    StockTarget("X", pct("5"), pct("2"), pct("2")),
                )
            )

    def test_target_for_lookup(self) -> None:
        plan = StockTargetPlan(targets=(StockTarget("X", pct("10"), pct("2"), pct("2")),))
        assert plan.target_for("X") is not None
        assert plan.target_for("Y") is None


class TestEvaluateStockAllocation:
    def _plan(self) -> StockTargetPlan:
        return StockTargetPlan(
            targets=(
                StockTarget("KRX:005930", target=pct("50"), buy_band=pct("5"), sell_band=pct("5")),
                StockTarget("NASDAQ:AAPL", target=pct("50"), buy_band=pct("5"), sell_band=pct("5")),
            )
        )

    def test_weights_are_relative_to_equity_sleeve(self) -> None:
        # 삼성 300만 + 애플 100만 = 슬리브 400만. 삼성 75%, 애플 25%.
        holdings = {
            "KRX:005930": Money.of("3000000", Currency.KRW),
            "NASDAQ:AAPL": Money.of("1000000", Currency.KRW),
        }
        report = EvaluateStockAllocation(self._plan()).execute(
            holdings=holdings, base_currency=Currency.KRW
        )
        by_id = {r.asset_id: r for r in report.rows}
        assert by_id["KRX:005930"].current_weight == pct("75")
        assert by_id["NASDAQ:AAPL"].current_weight == pct("25")
        # 삼성 75% > 목표55% 상단 → 매도, 애플 25% < 45% 하단 → 매수
        assert by_id["KRX:005930"].signal is StockSignal.SELL
        assert by_id["NASDAQ:AAPL"].signal is StockSignal.BUY

    def test_adjust_amount_moves_toward_target(self) -> None:
        holdings = {
            "KRX:005930": Money.of("3000000", Currency.KRW),
            "NASDAQ:AAPL": Money.of("1000000", Currency.KRW),
        }
        report = EvaluateStockAllocation(self._plan()).execute(
            holdings=holdings, base_currency=Currency.KRW
        )
        by_id = {r.asset_id: r for r in report.rows}
        # 삼성 목표 50% × 400만 = 200만, 현재 300만 → -100만(매도)
        assert by_id["KRX:005930"].adjust_amount == Money.of("-1000000", Currency.KRW)
        # 애플 목표 200만, 현재 100만 → +100만(매수)
        assert by_id["NASDAQ:AAPL"].adjust_amount == Money.of("1000000", Currency.KRW)

    def test_sleeve_value_reported(self) -> None:
        holdings = {"KRX:005930": Money.of("3000000", Currency.KRW)}
        report = EvaluateStockAllocation(
            StockTargetPlan(targets=(StockTarget("KRX:005930", pct("100"), pct("5"), pct("5")),))
        ).execute(holdings=holdings, base_currency=Currency.KRW)
        assert report.sleeve_value == Money.of("3000000", Currency.KRW)

    def test_empty_holdings_yield_empty_report(self) -> None:
        report = EvaluateStockAllocation(self._plan()).execute(
            holdings={}, base_currency=Currency.KRW
        )
        assert report.rows == ()
        assert report.sleeve_value == Money.zero(Currency.KRW)

    def test_holding_without_target_is_hold_with_no_target(self) -> None:
        holdings = {"KRX:999999": Money.of("1000000", Currency.KRW)}
        report = EvaluateStockAllocation(self._plan()).execute(
            holdings=holdings, base_currency=Currency.KRW
        )
        row = report.rows[0]
        assert row.target is None
        assert row.signal is StockSignal.HOLD
        assert row.adjust_amount == Money.zero(Currency.KRW)
