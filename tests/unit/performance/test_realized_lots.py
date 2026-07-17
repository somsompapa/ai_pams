"""match_fifo_lots()/compute_realized_performance() 테스트.

ai_stock journal.py(v1.5.4)의 FIFO 매칭 로직을 이식 — portfolio.domain.Transaction을
입력으로 쓴다는 점만 다르다(전용 저널이 아니라 실제 거래 원장을 그대로 씀).
"""

from datetime import date
from decimal import Decimal

from pams.performance.domain.realized_lots import compute_realized_performance, match_fifo_lots
from pams.portfolio.domain import Transaction, TransactionType
from pams.shared_kernel.domain import Currency, Money, Quantity

ASSET = "KRX:005930"


def tx(
    tx_id: str,
    tx_type: TransactionType,
    trade_date: date,
    *,
    quantity: str,
    price: str,
    fee: str = "0",
    tax: str = "0",
    currency: Currency = Currency.KRW,
) -> Transaction:
    return Transaction(
        transaction_id=tx_id,
        transaction_type=tx_type,
        trade_date=trade_date,
        asset_id=ASSET,
        quantity=Quantity.of(quantity),
        price=Money.of(price, currency),
        fee=Money.of(fee, currency),
        tax=Money.of(tax, currency),
    )


class TestFifoMatching:
    def test_full_sell_of_single_lot(self) -> None:
        txs = [
            tx("b1", TransactionType.BUY, date(2023, 1, 1), quantity="10", price="100"),
            tx("s1", TransactionType.SELL, date(2024, 1, 1), quantity="10", price="150"),
        ]
        result = match_fifo_lots(txs)
        assert len(result.closed_lots) == 1
        lot = result.closed_lots[0]
        assert lot.quantity == 10
        assert lot.cost == 1000
        assert lot.proceeds == 1500
        assert lot.realized_pnl == 500
        assert len(result.open_lots) == 0

    def test_partial_sell_consumes_oldest_lot_first(self) -> None:
        txs = [
            tx("b1", TransactionType.BUY, date(2023, 1, 1), quantity="5", price="100"),
            tx("b2", TransactionType.BUY, date(2023, 6, 1), quantity="5", price="200"),
            tx("s1", TransactionType.SELL, date(2024, 1, 1), quantity="7", price="300"),
        ]
        result = match_fifo_lots(txs)
        assert len(result.closed_lots) == 2
        first, second = result.closed_lots
        assert first.quantity == 5  # 오래된 랏(100원) 전량 먼저 소진
        assert first.unit_cost == 100
        assert second.quantity == 2  # 최근 랏(200원)에서 나머지 2개
        assert second.unit_cost == 200
        assert len(result.open_lots) == 1
        assert result.open_lots[0].quantity == 3  # 5-2 남음

    def test_fee_and_tax_included_in_unit_cost_and_proceeds(self) -> None:
        txs = [
            tx("b1", TransactionType.BUY, date(2023, 1, 1), quantity="10", price="100", fee="10"),
            tx(
                "s1",
                TransactionType.SELL,
                date(2024, 1, 1),
                quantity="10",
                price="150",
                fee="5",
                tax="5",
            ),
        ]
        result = match_fifo_lots(txs)
        lot = result.closed_lots[0]
        assert lot.unit_cost == Decimal("101")  # (1000+10)/10
        assert lot.unit_proceeds == Decimal("149")  # (1500-5-5)/10

    def test_sell_exceeding_holdings_is_skipped_not_partially_matched(self) -> None:
        txs = [
            tx("b1", TransactionType.BUY, date(2023, 1, 1), quantity="5", price="100"),
            tx("s1", TransactionType.SELL, date(2024, 1, 1), quantity="10", price="150"),
        ]
        result = match_fifo_lots(txs)
        assert len(result.closed_lots) == 0
        assert len(result.skipped) == 1
        assert "보유 랏 합계" in result.skipped[0].reason
        assert len(result.open_lots) == 1  # 매도가 무효 처리돼 원래 랏 그대로 남음

    def test_currency_kept_separate(self) -> None:
        txs = [
            tx("b1", TransactionType.BUY, date(2023, 1, 1), quantity="10", price="100"),
            tx("s1", TransactionType.SELL, date(2024, 1, 1), quantity="10", price="150"),
            tx(
                "b2",
                TransactionType.BUY,
                date(2023, 1, 1),
                quantity="10",
                price="10",
                currency=Currency.USD,
            ),
            tx(
                "s2",
                TransactionType.SELL,
                date(2024, 1, 1),
                quantity="10",
                price="15",
                currency=Currency.USD,
            ),
        ]
        report = compute_realized_performance(txs)
        currencies = {r.currency for r in report.by_currency}
        assert currencies == {Currency.KRW, Currency.USD}


class TestRealizedPerformance:
    def test_capital_weighted_cagr_matches_hand_calculation(self) -> None:
        """1년 보유, 원금 1000→1500(50% 수익) → CAGR 정확히 50%."""
        txs = [
            tx("b1", TransactionType.BUY, date(2023, 1, 1), quantity="10", price="100"),
            tx("s1", TransactionType.SELL, date(2024, 1, 1), quantity="10", price="150"),
        ]
        report = compute_realized_performance(txs)
        result = report.by_currency[0]
        assert result.total_cost == 1000
        assert result.total_realized_pnl == 500
        assert result.realized_return_pct == 50
        assert result.capital_weighted_cagr is not None
        assert abs(result.capital_weighted_cagr - Decimal("0.5")) < Decimal("0.001")

    def test_same_day_buy_sell_excluded_from_cagr_not_crash(self) -> None:
        """매수·매도가 같은 날이면 보유기간이 0이라 CAGR을 정의할 수 없다 —
        회귀 테스트: 이 랏 하나 때문에 전체 계산이 죽으면 안 된다."""
        txs = [
            tx("b1", TransactionType.BUY, date(2024, 1, 1), quantity="10", price="100"),
            tx("s1", TransactionType.SELL, date(2024, 1, 1), quantity="10", price="150"),
        ]
        report = compute_realized_performance(txs)
        result = report.by_currency[0]
        assert result.total_realized_pnl == 500  # 손익 자체는 정상 계산
        assert result.capital_weighted_cagr is None  # CAGR만 정의 불가로 제외

    def test_realized_pnl_drawdown_reflects_a_loss_then_recovery(self) -> None:
        txs = [
            tx("b1", TransactionType.BUY, date(2023, 1, 1), quantity="10", price="100"),
            tx("s1", TransactionType.SELL, date(2023, 6, 1), quantity="10", price="50"),  # 손실
            tx("b2", TransactionType.BUY, date(2023, 7, 1), quantity="10", price="50"),
            tx("s2", TransactionType.SELL, date(2024, 1, 1), quantity="10", price="200"),  # 만회
        ]
        report = compute_realized_performance(txs)
        result = report.by_currency[0]
        assert result.realized_pnl_drawdown_approx is not None
        assert result.realized_pnl_drawdown_approx > 0  # 중간에 낙폭이 있었다

    def test_no_closed_lots_yields_empty_by_currency(self) -> None:
        txs = [tx("b1", TransactionType.BUY, date(2023, 1, 1), quantity="10", price="100")]
        report = compute_realized_performance(txs)
        assert report.by_currency == ()
        assert report.n_open_lots == 1
