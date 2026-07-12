"""위험지표 계산 함수 테스트.

Decimal 정확값이 나오도록 설계된 시나리오를 사용하고,
무리수 결과는 quantize로 비교한다.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from pams.risk.domain import (
    InsufficientDataError,
    ReturnSeries,
    RiskCalculationError,
    ValueSeries,
    measures,
)

START = date(2026, 1, 1)


def value_series(*values: str) -> ValueSeries:
    return ValueSeries.from_pairs(
        [(START + timedelta(days=i), Decimal(v)) for i, v in enumerate(values)]
    )


def return_series(*values: str) -> ReturnSeries:
    return ReturnSeries.from_pairs(
        [(START + timedelta(days=i), Decimal(v)) for i, v in enumerate(values)]
    )


def q(value: Decimal, places: str = "0.000001") -> Decimal:
    return value.quantize(Decimal(places))


class TestDrawdown:
    def test_max_drawdown(self) -> None:
        """고점 120→90 (25%), 고점 150→105 (30%) → MDD 30%."""
        series = value_series("100", "120", "90", "150", "105")
        assert measures.max_drawdown(series) == Decimal("0.30")

    def test_max_drawdown_monotonic_rise_is_zero(self) -> None:
        assert measures.max_drawdown(value_series("100", "110", "120")) == Decimal(0)

    def test_current_drawdown(self) -> None:
        series = value_series("100", "150", "105", "120")
        assert measures.current_drawdown(series) == Decimal("0.20")


class TestCagr:
    def test_two_year_double_digit(self) -> None:
        """730일(2년) 동안 100→121 → CAGR 10%."""
        series = ValueSeries.from_pairs(
            [(START, Decimal(100)), (START + timedelta(days=730), Decimal(121))]
        )
        assert q(measures.cagr(series)) == Decimal("0.100000")

    def test_negative_cagr(self) -> None:
        series = ValueSeries.from_pairs(
            [(START, Decimal(100)), (START + timedelta(days=365), Decimal(90))]
        )
        assert q(measures.cagr(series)) == Decimal("-0.100000")

    def test_needs_two_points(self) -> None:
        with pytest.raises(InsufficientDataError):
            measures.cagr(value_series("100"))


class TestVolatilityAndRatios:
    def test_annualized_volatility_annual_periods(self) -> None:
        """periods_per_year=1이면 연환산 = 표본표준편차 그대로."""
        returns = return_series("0.05", "0.15", "0.10")
        assert measures.annualized_volatility(returns, 1) == Decimal("0.05")

    def test_annualized_volatility_scales_by_sqrt_periods(self) -> None:
        returns = return_series("0.05", "0.15", "0.10")
        expected = Decimal("0.05") * Decimal(252).sqrt()
        assert q(measures.annualized_volatility(returns, 252)) == q(expected)

    def test_sharpe_ratio(self) -> None:
        """(평균 0.10 - 무위험 0.02) / 표준편차 0.05 = 1.6 (연 단위 데이터)."""
        returns = return_series("0.05", "0.15", "0.10")
        assert measures.sharpe_ratio(returns, Decimal("0.02"), 1) == Decimal("1.6")

    def test_sharpe_zero_volatility_rejected(self) -> None:
        with pytest.raises(RiskCalculationError):
            measures.sharpe_ratio(return_series("0.05", "0.05", "0.05"), Decimal(0), 1)

    def test_sortino_ratio(self) -> None:
        """평균 0.04 / 하방편차 0.05 = 0.8 (무위험 0, 연 단위)."""
        returns = return_series("0.10", "-0.06", "0.20", "-0.08")
        assert measures.sortino_ratio(returns, Decimal(0), 1) == Decimal("0.8")

    def test_calmar_ratio(self) -> None:
        """CAGR 10% / MDD 20% = 0.5."""
        series = ValueSeries.from_pairs(
            [
                (START, Decimal(100)),
                (START + timedelta(days=100), Decimal(125)),
                (START + timedelta(days=200), Decimal(100)),  # 고점 125 대비 -20%
                (START + timedelta(days=730), Decimal(121)),
            ]
        )
        assert q(measures.calmar_ratio(series)) == Decimal("0.500000")


class TestVarCvar:
    RETURNS = return_series(
        "-0.12", "0.03", "-0.05", "0.08", "0.01", "0.02", "-0.01", "0.04", "0.06", "0.05"
    )

    def test_var_90(self) -> None:
        """하위 10% 분위(최악 1개) → VaR = 12% 손실."""
        assert measures.historical_var(self.RETURNS, Decimal("0.90")) == Decimal("0.12")

    def test_var_80(self) -> None:
        """하위 20% 분위(최악 2개 중 2번째) → VaR = 5% 손실."""
        assert measures.historical_var(self.RETURNS, Decimal("0.80")) == Decimal("0.05")

    def test_cvar_80(self) -> None:
        """최악 2개(-12%, -5%)의 평균 → CVaR = 8.5% 손실."""
        assert measures.historical_cvar(self.RETURNS, Decimal("0.80")) == Decimal("0.085")


class TestBenchmarkRelative:
    BENCHMARK = return_series("0.01", "-0.02", "0.03", "0.02")
    PORTFOLIO = return_series("0.02", "-0.04", "0.06", "0.04")  # 정확히 2배

    def test_beta(self) -> None:
        assert q(measures.beta(self.PORTFOLIO, self.BENCHMARK)) == Decimal("2.000000")

    def test_alpha_of_pure_leverage_is_zero(self) -> None:
        """rf=0이고 포트폴리오가 벤치마크의 순수 2배라면 젠센 알파는 0."""
        alpha = measures.alpha(self.PORTFOLIO, self.BENCHMARK, Decimal(0), 1)
        assert q(alpha) == Decimal("0.000000")

    def test_correlation_perfect(self) -> None:
        corr = measures.correlation(self.PORTFOLIO, self.BENCHMARK)
        assert q(corr) == Decimal("1.000000")

    def test_tracking_error(self) -> None:
        """p-b = b 이므로 TE = 벤치마크 표준편차와 같다."""
        expected = self.BENCHMARK.sample_std
        assert q(measures.tracking_error(self.PORTFOLIO, self.BENCHMARK, 1)) == q(expected)

    def test_misaligned_series_use_common_dates_only(self) -> None:
        shifted = ReturnSeries.from_pairs(
            [(START + timedelta(days=i), v) for i, v in enumerate([Decimal("0.99")], start=100)]
        )
        with pytest.raises(InsufficientDataError):
            measures.beta(self.PORTFOLIO, shifted)


class TestConcentration:
    def test_herfindahl_index(self) -> None:
        weights = [Decimal("0.5"), Decimal("0.3"), Decimal("0.2")]
        assert measures.herfindahl_index(weights) == Decimal("0.38")

    def test_single_asset_is_max_concentration(self) -> None:
        assert measures.herfindahl_index([Decimal(1)]) == Decimal(1)
