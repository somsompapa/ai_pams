"""evaluate_liquidity() 테스트 — portfolio_rules.md P-5(v1.6.1 신규) 유동성 스크리닝.
자동 차단이 아니라 판단 보조라는 점, 최소 기준(1차 매수 예정 금액의 20배)을 확인한다."""

from datetime import date
from decimal import Decimal

from pams.equity.domain.liquidity import evaluate_liquidity
from pams.market_data.domain import DailyBar


def _bar(day: int, close: str, volume: int) -> DailyBar:
    return DailyBar(quote_date=date(2026, 1, day), close=Decimal(close), volume=volume)


class TestEvaluateLiquidity:
    def test_sufficient_when_average_trading_value_meets_20x_multiple(self) -> None:
        # 거래대금 = 100 * 1,000,000 = 1억, 20일 평균도 1억 → 1차 매수 500만원의 20배(1억) 충족
        bars = tuple(_bar(d, "100", 1_000_000) for d in range(1, 21))
        result = evaluate_liquidity(
            planned_first_tranche_amount=Decimal(5_000_000), daily_bars=bars
        )
        assert result.sufficient is True
        assert result.average_daily_trading_value == Decimal(100_000_000)
        assert result.required_minimum == Decimal(100_000_000)

    def test_insufficient_when_below_20x_multiple(self) -> None:
        bars = tuple(_bar(d, "100", 100_000) for d in range(1, 21))  # 거래대금 1천만
        result = evaluate_liquidity(
            planned_first_tranche_amount=Decimal(5_000_000), daily_bars=bars
        )
        assert result.sufficient is False

    def test_uses_custom_multiple_when_provided(self) -> None:
        bars = tuple(_bar(d, "100", 1_000_000) for d in range(1, 21))
        result = evaluate_liquidity(
            planned_first_tranche_amount=Decimal(5_000_000),
            daily_bars=bars,
            multiple=Decimal(10),
        )
        assert result.required_minimum == Decimal(50_000_000)
        assert result.sufficient is True

    def test_empty_bars_returns_none_with_note(self) -> None:
        """거래대금 이력 조회 실패는 '부족'이 아니라 '판정 불가'로 정직하게 구분한다."""
        result = evaluate_liquidity(planned_first_tranche_amount=Decimal(5_000_000), daily_bars=())
        assert result.sufficient is None
        assert result.average_daily_trading_value is None
        assert result.note is not None

    def test_days_observed_reflects_bar_count(self) -> None:
        bars = tuple(_bar(d, "100", 1_000_000) for d in range(1, 6))
        result = evaluate_liquidity(planned_first_tranche_amount=Decimal(1), daily_bars=bars)
        assert result.days_observed == 5
