"""종목별 절대가격 매수/매도 트리거 도메인 테스트.

사용자가 눈으로 보던 "삼성전자 7만원 이하면 매수, 9만원 이상이면 매도"를
규칙으로 옮긴 것. 현재가가 선을 건드리면 신호를 낸다. 실행은 사용자가 한다.
"""

import pytest

from pams.equity.domain import (
    EvaluatePriceTriggers,
    PriceTrigger,
    PriceTriggerPlan,
    StockSignal,
)
from pams.shared_kernel.domain import Currency, DomainValidationError, Money


def krw(v: str) -> Money:
    return Money.of(v, Currency.KRW)


class TestPriceTrigger:
    def test_buy_signal_at_or_below_buy_price(self) -> None:
        t = PriceTrigger(asset_id="KRX:005930", buy_at=krw("70000"), sell_at=krw("90000"))
        assert t.signal(krw("68000")) is StockSignal.BUY
        assert t.signal(krw("70000")) is StockSignal.BUY  # 경계 포함

    def test_sell_signal_at_or_above_sell_price(self) -> None:
        t = PriceTrigger(asset_id="KRX:005930", buy_at=krw("70000"), sell_at=krw("90000"))
        assert t.signal(krw("92000")) is StockSignal.SELL
        assert t.signal(krw("90000")) is StockSignal.SELL  # 경계 포함

    def test_hold_between(self) -> None:
        t = PriceTrigger(asset_id="KRX:005930", buy_at=krw("70000"), sell_at=krw("90000"))
        assert t.signal(krw("80000")) is StockSignal.HOLD

    def test_buy_only_trigger(self) -> None:
        t = PriceTrigger(asset_id="X", buy_at=krw("100"), sell_at=None)
        assert t.signal(krw("90")) is StockSignal.BUY
        assert t.signal(krw("200")) is StockSignal.HOLD  # 매도선 없음

    def test_requires_at_least_one_bound(self) -> None:
        with pytest.raises(DomainValidationError, match="buy_at|sell_at|하나"):
            PriceTrigger(asset_id="X", buy_at=None, sell_at=None)

    def test_buy_must_be_below_sell(self) -> None:
        with pytest.raises(DomainValidationError, match="매수.*매도|buy.*sell"):
            PriceTrigger(asset_id="X", buy_at=krw("90000"), sell_at=krw("70000"))

    def test_currency_mismatch_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            PriceTrigger(asset_id="X", buy_at=krw("100"), sell_at=Money.of("200", Currency.USD))


class TestEvaluatePriceTriggers:
    def _plan(self) -> PriceTriggerPlan:
        return PriceTriggerPlan(
            triggers=(
                PriceTrigger("KRX:005930", buy_at=krw("70000"), sell_at=krw("90000")),
                PriceTrigger("NASDAQ:AAPL", buy_at=Money.of("180", Currency.USD), sell_at=None),
            )
        )

    def test_only_firing_signals_returned_when_current_prices_cross(self) -> None:
        prices = {
            "KRX:005930": krw("68000"),  # 매수선 이하 → BUY
            "NASDAQ:AAPL": Money.of("300", Currency.USD),  # 매수선 위 → HOLD
        }
        report = EvaluatePriceTriggers(self._plan()).execute(current_prices=prices)
        by_id = {r.asset_id: r for r in report.rows}
        assert by_id["KRX:005930"].signal is StockSignal.BUY
        assert by_id["NASDAQ:AAPL"].signal is StockSignal.HOLD
        # firing만 필터
        assert {r.asset_id for r in report.firing} == {"KRX:005930"}

    def test_missing_price_is_skipped(self) -> None:
        report = EvaluatePriceTriggers(self._plan()).execute(current_prices={})
        assert report.rows == ()

    def test_duplicate_trigger_rejected(self) -> None:
        with pytest.raises(DomainValidationError, match="중복"):
            PriceTriggerPlan(
                triggers=(
                    PriceTrigger("X", buy_at=krw("100"), sell_at=None),
                    PriceTrigger("X", buy_at=krw("90"), sell_at=None),
                )
            )
