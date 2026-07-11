"""RiskEngine/RiskReport 테스트."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from pams.risk.application import ComputeRiskReport
from pams.risk.domain import RiskEngine, RiskParameters, ValueSeries
from pams.shared_kernel.domain import DomainValidationError

START = date(2025, 1, 1)

PORTFOLIO = ValueSeries.from_pairs(
    [
        (START, Decimal("1000000")),
        (START + timedelta(days=91), Decimal("1100000")),
        (START + timedelta(days=182), Decimal("990000")),
        (START + timedelta(days=273), Decimal("1150000")),
        (START + timedelta(days=365), Decimal("1080000")),
    ]
)
BENCHMARK = ValueSeries.from_pairs(
    [
        (START, Decimal("100")),
        (START + timedelta(days=91), Decimal("105")),
        (START + timedelta(days=182), Decimal("98")),
        (START + timedelta(days=273), Decimal("110")),
        (START + timedelta(days=365), Decimal("107")),
    ]
)
PARAMS = RiskParameters(
    periods_per_year=4, risk_free_rate=Decimal("0.02"), var_confidence=Decimal("0.75")
)


class TestRiskParameters:
    def test_invalid_confidence_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            RiskParameters(
                periods_per_year=252, risk_free_rate=Decimal(0), var_confidence=Decimal("1.5")
            )

    def test_invalid_periods_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            RiskParameters(
                periods_per_year=0, risk_free_rate=Decimal(0), var_confidence=Decimal("0.95")
            )

    def test_float_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            RiskParameters(
                periods_per_year=252,
                risk_free_rate=0.02,  # type: ignore[arg-type]
                var_confidence=Decimal("0.95"),
            )


class TestRiskEngine:
    def test_base_metrics_present(self) -> None:
        report = RiskEngine().analyze(portfolio_values=PORTFOLIO, parameters=PARAMS)
        expected_keys = {
            "mdd",
            "drawdown",
            "cagr",
            "volatility",
            "sharpe",
            "sortino",
            "calmar",
            "var",
            "cvar",
        }
        assert expected_keys <= set(report.metrics)
        for value in report.metrics.values():
            assert isinstance(value, Decimal)

    def test_drawdown_metric_matches_rule_config_semantics(self) -> None:
        """config/rules의 drawdown 지표: 고점(1,150,000) 대비 현재(1,080,000) 낙폭."""
        report = RiskEngine().analyze(portfolio_values=PORTFOLIO, parameters=PARAMS)
        assert report.metrics["drawdown"] == (Decimal("70000") / Decimal("1150000"))
        # MDD는 고점 1,100,000 → 저점 990,000 구간과 비교해 더 큰 쪽
        assert report.metrics["mdd"] == Decimal("110000") / Decimal("1100000")

    def test_benchmark_metrics_added_when_given(self) -> None:
        report = RiskEngine().analyze(
            portfolio_values=PORTFOLIO, parameters=PARAMS, benchmark_values=BENCHMARK
        )
        assert {"beta", "alpha", "correlation", "tracking_error"} <= set(report.metrics)

    def test_concentration_added_when_weights_given(self) -> None:
        report = RiskEngine().analyze(
            portfolio_values=PORTFOLIO,
            parameters=PARAMS,
            position_weights={"A": Decimal("0.6"), "B": Decimal("0.4")},
        )
        assert report.metrics["concentration_hhi"] == Decimal("0.52")

    def test_as_of_is_series_end(self) -> None:
        report = RiskEngine().analyze(portfolio_values=PORTFOLIO, parameters=PARAMS)
        assert report.as_of == START + timedelta(days=365)


class TestComputeRiskReportUseCase:
    def test_execute_delegates_to_engine(self) -> None:
        report = ComputeRiskReport().execute(
            portfolio_values=PORTFOLIO, parameters=PARAMS, benchmark_values=BENCHMARK
        )
        assert report.metrics["beta"] > 0
