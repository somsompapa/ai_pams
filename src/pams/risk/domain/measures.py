"""위험지표 계산 함수 모음.

모든 입력/출력은 Decimal이다. 비율 지표(수익률, 낙폭)는 0~1 스케일을 쓴다.
연환산 규약:
- 변동성/추적오차: 표본표준편차 × sqrt(periods_per_year)
- Sharpe/Sortino: 기간 무위험수익률 = 연 무위험수익률 / periods_per_year
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from pams.risk.domain.series import InsufficientDataError, ReturnSeries, ValueSeries
from pams.shared_kernel.domain import DomainError

_DAYS_PER_YEAR = Decimal(365)


class RiskCalculationError(DomainError):
    """지표가 수학적으로 정의되지 않는 상황 (예: 변동성 0에서의 Sharpe)."""


def max_drawdown(series: ValueSeries) -> Decimal:
    """전 기간 최대 낙폭 (고점 대비 하락 비율의 최댓값, 0~1)."""
    peak = series.values[0]
    worst = Decimal(0)
    for value in series.values:
        peak = max(peak, value)
        worst = max(worst, (peak - value) / peak)
    return worst


def current_drawdown(series: ValueSeries) -> Decimal:
    """현재(마지막 시점) 낙폭. config/rules의 'drawdown' 지표."""
    peak = max(series.values)
    return (peak - series.values[-1]) / peak


def cagr(series: ValueSeries) -> Decimal:
    """연복리수익률: (end/start)^(1/years) - 1."""
    if len(series) < 2:
        raise InsufficientDataError("CAGR 계산에는 가치가 2개 이상 필요하다")
    (start_date, start_value), (end_date, end_value) = series.start, series.end
    days = (end_date - start_date).days
    if days <= 0:
        raise InsufficientDataError("CAGR 계산 구간이 0일이다")
    years = Decimal(days) / _DAYS_PER_YEAR
    growth = end_value / start_value
    return (growth.ln() / years).exp() - 1


def annualized_volatility(returns: ReturnSeries, periods_per_year: int) -> Decimal:
    return returns.sample_std * Decimal(periods_per_year).sqrt()


def sharpe_ratio(returns: ReturnSeries, risk_free_rate: Decimal, periods_per_year: int) -> Decimal:
    std = returns.sample_std
    if std == 0:
        raise RiskCalculationError("변동성이 0이면 Sharpe Ratio가 정의되지 않는다")
    excess = returns.mean - risk_free_rate / periods_per_year
    return excess / std * Decimal(periods_per_year).sqrt()


def sortino_ratio(returns: ReturnSeries, risk_free_rate: Decimal, periods_per_year: int) -> Decimal:
    target = risk_free_rate / periods_per_year
    downside = returns.downside_deviation(target)
    if downside == 0:
        raise RiskCalculationError("하방편차가 0이면 Sortino Ratio가 정의되지 않는다")
    return (returns.mean - target) / downside * Decimal(periods_per_year).sqrt()


def calmar_ratio(series: ValueSeries) -> Decimal:
    mdd = max_drawdown(series)
    if mdd == 0:
        raise RiskCalculationError("낙폭이 0이면 Calmar Ratio가 정의되지 않는다")
    return cagr(series) / mdd


def _tail_size(count: int, confidence: Decimal) -> int:
    tail = count * (1 - confidence)
    size = int(tail) if tail == int(tail) else int(tail) + 1  # ceil
    return max(size, 1)


def historical_var(returns: ReturnSeries, confidence: Decimal) -> Decimal:
    """역사적 VaR: 신뢰수준을 벗어나는 꼬리의 경계 손실 (양수 = 손실)."""
    ordered = sorted(returns.values)
    tail = _tail_size(len(ordered), confidence)
    return -ordered[tail - 1]


def historical_cvar(returns: ReturnSeries, confidence: Decimal) -> Decimal:
    """역사적 CVaR(Expected Shortfall): 꼬리 손실의 평균 (양수 = 손실)."""
    ordered = sorted(returns.values)
    tail = _tail_size(len(ordered), confidence)
    return -(sum(ordered[:tail], Decimal(0)) / tail)


def _covariance(a: ReturnSeries, b: ReturnSeries) -> Decimal:
    """정렬된 두 시계열의 표본 공분산 (n-1 분모)."""
    if len(a) < 2:
        raise InsufficientDataError("공분산 계산에는 공통 수익률이 2개 이상 필요하다")
    mean_a, mean_b = a.mean, b.mean
    paired = zip(a.values, b.values, strict=True)
    total = sum(((x - mean_a) * (y - mean_b) for x, y in paired), Decimal(0))
    return total / (len(a) - 1)


def beta(portfolio: ReturnSeries, benchmark: ReturnSeries) -> Decimal:
    p, b = portfolio.align(benchmark)
    benchmark_variance = _covariance(b, b)
    if benchmark_variance == 0:
        raise RiskCalculationError("벤치마크 분산이 0이면 Beta가 정의되지 않는다")
    return _covariance(p, b) / benchmark_variance


def alpha(
    portfolio: ReturnSeries,
    benchmark: ReturnSeries,
    risk_free_rate: Decimal,
    periods_per_year: int,
) -> Decimal:
    """젠센 알파 (연환산)."""
    p, b = portfolio.align(benchmark)
    rf_period = risk_free_rate / periods_per_year
    portfolio_beta = beta(p, b)
    alpha_period = (p.mean - rf_period) - portfolio_beta * (b.mean - rf_period)
    return alpha_period * periods_per_year


def correlation(portfolio: ReturnSeries, benchmark: ReturnSeries) -> Decimal:
    p, b = portfolio.align(benchmark)
    std_product = p.sample_std * b.sample_std
    if std_product == 0:
        raise RiskCalculationError("표준편차가 0이면 상관계수가 정의되지 않는다")
    return _covariance(p, b) / std_product


def tracking_error(
    portfolio: ReturnSeries, benchmark: ReturnSeries, periods_per_year: int
) -> Decimal:
    """초과수익률(p-b)의 연환산 표준편차."""
    p, b = portfolio.align(benchmark)
    diffs = ReturnSeries.from_pairs(
        [(d, pv - bv) for (d, pv), (_bd, bv) in zip(p.entries, b.entries, strict=True)]
    )
    return annualized_volatility(diffs, periods_per_year)


def herfindahl_index(weights: Iterable[Decimal]) -> Decimal:
    """집중도(HHI): 비중 제곱합. 1에 가까울수록 집중, 1/N이면 완전 분산."""
    return sum((w**2 for w in weights), Decimal(0))
