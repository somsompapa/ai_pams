"""RiskEngine: 가치 시계열 → 표준 위험지표 보고서."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pams.risk.domain import measures
from pams.risk.domain.measures import RiskCalculationError
from pams.risk.domain.series import ValueSeries
from pams.shared_kernel.domain import DomainValidationError


@dataclass(frozen=True, slots=True)
class RiskParameters:
    """리스크 계산 파라미터. 값은 config/risk/*.yaml에서 로드한다 (하드코딩 금지)."""

    periods_per_year: int  # 일별 데이터면 252, 월별이면 12
    risk_free_rate: Decimal  # 연 무위험수익률 (비율)
    var_confidence: Decimal  # VaR/CVaR 신뢰수준 (예: 0.95)

    def __post_init__(self) -> None:
        if self.periods_per_year < 1:
            raise DomainValidationError(
                f"periods_per_year는 1 이상이어야 한다: {self.periods_per_year}"
            )
        if not isinstance(self.risk_free_rate, Decimal) or not isinstance(
            self.var_confidence, Decimal
        ):
            raise DomainValidationError("리스크 파라미터는 Decimal이어야 한다 (float 금지)")
        if not (Decimal(0) < self.var_confidence < Decimal(1)):
            raise DomainValidationError(
                f"var_confidence는 0과 1 사이여야 한다: {self.var_confidence}"
            )


@dataclass(frozen=True, slots=True)
class RiskReport:
    """위험지표 묶음. metrics의 이름은 config/rules의 metric과 일치해야 한다.

    수학적으로 정의되지 않는 지표(예: 하락 없는 시계열의 Sortino)는
    값을 지어내지 않고 생략된다 - 키가 없으면 '해당 데이터로는 정의 불가'라는 뜻.
    """

    as_of: date
    metrics: Mapping[str, Decimal]


def _put_if_defined(metrics: dict[str, Decimal], name: str, compute: Callable[[], Decimal]) -> None:
    """정의되지 않는 지표는 조용히 0을 넣는 대신 생략한다."""
    try:
        metrics[name] = compute()
    except RiskCalculationError:
        pass


class RiskEngine:
    def analyze(
        self,
        *,
        portfolio_values: ValueSeries,
        parameters: RiskParameters,
        benchmark_values: ValueSeries | None = None,
        position_weights: Mapping[str, Decimal] | None = None,
    ) -> RiskReport:
        returns = portfolio_values.returns()
        # 항상 계산 가능한 지표 (규칙이 참조하는 drawdown/mdd 포함)
        metrics: dict[str, Decimal] = {
            "mdd": measures.max_drawdown(portfolio_values),
            "drawdown": measures.current_drawdown(portfolio_values),
            "cagr": measures.cagr(portfolio_values),
            "volatility": measures.annualized_volatility(returns, parameters.periods_per_year),
            "var": measures.historical_var(returns, parameters.var_confidence),
            "cvar": measures.historical_cvar(returns, parameters.var_confidence),
        }
        # 데이터에 따라 정의되지 않을 수 있는 비율 지표
        _put_if_defined(
            metrics,
            "sharpe",
            lambda: measures.sharpe_ratio(
                returns, parameters.risk_free_rate, parameters.periods_per_year
            ),
        )
        _put_if_defined(
            metrics,
            "sortino",
            lambda: measures.sortino_ratio(
                returns, parameters.risk_free_rate, parameters.periods_per_year
            ),
        )
        _put_if_defined(metrics, "calmar", lambda: measures.calmar_ratio(portfolio_values))

        if benchmark_values is not None:
            benchmark_returns = benchmark_values.returns()
            _put_if_defined(metrics, "beta", lambda: measures.beta(returns, benchmark_returns))
            _put_if_defined(
                metrics,
                "alpha",
                lambda: measures.alpha(
                    returns,
                    benchmark_returns,
                    parameters.risk_free_rate,
                    parameters.periods_per_year,
                ),
            )
            _put_if_defined(
                metrics,
                "correlation",
                lambda: measures.correlation(returns, benchmark_returns),
            )
            _put_if_defined(
                metrics,
                "tracking_error",
                lambda: measures.tracking_error(
                    returns, benchmark_returns, parameters.periods_per_year
                ),
            )
        if position_weights is not None:
            metrics["concentration_hhi"] = measures.herfindahl_index(position_weights.values())
        return RiskReport(as_of=portfolio_values.end[0], metrics=metrics)
