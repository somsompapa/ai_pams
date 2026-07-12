"""종목별 절대가격 트리거 도메인 테스트.

한 종목에 세 가지 가격선을 둘 수 있다:
- 매수선(buy_at): 이하로 내려가면 매수
- 익절선(take_profit_at): 이상으로 올라가면 매도(이익 실현)
- 손절선(stop_loss_at): 이하로 내려가면 매도(손실 제한)
현재가가 선을 건드리면 신호를 낸다. 실행은 사용자가 한다.
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
    def test_buy_signal_at_or_below_buy_line(self) -> None:
        t = PriceTrigger("KRX:005930", buy_at=krw("70000"), take_profit_at=krw("90000"))
        assert t.signal(krw("68000")) is StockSignal.BUY
        assert t.signal(krw("70000")) is StockSignal.BUY

    def test_take_profit_sell_at_or_above(self) -> None:
        t = PriceTrigger("KRX:005930", buy_at=krw("70000"), take_profit_at=krw("90000"))
        assert t.signal(krw("92000")) is StockSignal.SELL
        assert t.signal(krw("90000")) is StockSignal.SELL

    def test_stop_loss_sell_at_or_below(self) -> None:
        t = PriceTrigger("KRX:005930", buy_at=None, stop_loss_at=krw("60000"))
        assert t.signal(krw("58000")) is StockSignal.SELL
        assert t.signal(krw("60000")) is StockSignal.SELL
        assert t.signal(krw("65000")) is StockSignal.HOLD

    def test_hold_between_lines(self) -> None:
        t = PriceTrigger(
            "KRX:005930",
            buy_at=krw("70000"),
            take_profit_at=krw("90000"),
            stop_loss_at=krw("60000"),
        )
        assert t.signal(krw("80000")) is StockSignal.HOLD

    def test_stop_loss_takes_priority_over_buy(self) -> None:
        # 손절선(60,000) 아래로 급락하면 매수선(70,000)보다 손절이 우선한다.
        t = PriceTrigger("KRX:005930", buy_at=krw("70000"), stop_loss_at=krw("60000"))
        hit = t.evaluate(krw("55000"))
        assert hit is not None
        assert hit.signal is StockSignal.SELL
        assert hit.label == "손절"

    def test_evaluate_labels(self) -> None:
        t = PriceTrigger(
            "X",
            buy_at=krw("70000"),
            take_profit_at=krw("90000"),
            stop_loss_at=krw("60000"),
        )
        assert t.evaluate(krw("69000")).label == "매수"
        assert t.evaluate(krw("91000")).label == "익절"
        assert t.evaluate(krw("59000")).label == "손절"
        assert t.evaluate(krw("80000")) is None  # 유지

    def test_requires_at_least_one_line(self) -> None:
        with pytest.raises(DomainValidationError, match="하나"):
            PriceTrigger("X", buy_at=None, take_profit_at=None, stop_loss_at=None)

    def test_stop_loss_must_be_below_take_profit(self) -> None:
        with pytest.raises(DomainValidationError, match="손절.*익절"):
            PriceTrigger("X", take_profit_at=krw("70000"), stop_loss_at=krw("90000"))

    def test_buy_must_be_below_take_profit(self) -> None:
        with pytest.raises(DomainValidationError, match="매수.*익절"):
            PriceTrigger("X", buy_at=krw("90000"), take_profit_at=krw("70000"))

    def test_stop_loss_must_be_below_buy(self) -> None:
        with pytest.raises(DomainValidationError, match="손절.*매수"):
            PriceTrigger("X", buy_at=krw("60000"), stop_loss_at=krw("70000"))

    def test_currency_mismatch_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            PriceTrigger("X", buy_at=krw("100"), take_profit_at=Money.of("200", Currency.USD))


class TestEvaluatePriceTriggers:
    def _plan(self) -> PriceTriggerPlan:
        return PriceTriggerPlan(
            triggers=(
                PriceTrigger(
                    "KRX:005930",
                    buy_at=krw("70000"),
                    take_profit_at=krw("90000"),
                    stop_loss_at=krw("60000"),
                ),
                PriceTrigger("NASDAQ:AAPL", buy_at=Money.of("180", Currency.USD)),
            )
        )

    def test_firing_filters_hold(self) -> None:
        prices = {
            "KRX:005930": krw("58000"),  # 손절선 이하 → SELL
            "NASDAQ:AAPL": Money.of("300", Currency.USD),  # 매수선 위 → HOLD
        }
        report = EvaluatePriceTriggers(self._plan()).execute(current_prices=prices)
        assert {r.asset_id for r in report.firing} == {"KRX:005930"}
        row = next(r for r in report.rows if r.asset_id == "KRX:005930")
        assert row.signal is StockSignal.SELL
        assert row.label == "손절"

    def test_duplicate_rejected(self) -> None:
        with pytest.raises(DomainValidationError, match="중복"):
            PriceTriggerPlan(
                triggers=(
                    PriceTrigger("X", buy_at=krw("100")),
                    PriceTrigger("X", buy_at=krw("90")),
                )
            )
