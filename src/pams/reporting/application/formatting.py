"""표시용 포맷팅 규칙 - 보고서와 대시보드가 공유한다.

표시 계층 전용이며, 계산에는 절대 사용하지 않는다.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pams.shared_kernel.domain import Money, Percentage

ASSET_CLASS_LABELS: dict[str, str] = {
    "domestic_stock": "국내주식",
    "us_stock": "미국주식",
    "etf": "ETF",
    "bond": "채권",
    "cash": "현금",
    "deposit": "예수금",
    "foreign_currency": "외화",
    "gold": "금",
    "pension": "연금",
    "savings": "청약·저축",
    "crypto": "가상자산",
}

METRIC_LABELS: dict[str, str] = {
    "mdd": "최대낙폭(MDD)",
    "drawdown": "현재 낙폭",
    "cagr": "CAGR",
    "volatility": "변동성(연환산)",
    "sharpe": "Sharpe Ratio",
    "sortino": "Sortino Ratio",
    "calmar": "Calmar Ratio",
    "var": "VaR",
    "cvar": "CVaR",
    "beta": "Beta",
    "alpha": "Alpha",
    "correlation": "상관계수",
    "tracking_error": "추적오차",
    "concentration_hhi": "집중도(HHI)",
}

# 백분율로 표시하는 리스크 지표 (나머지는 소수 그대로)
RATIO_METRICS: frozenset[str] = frozenset(
    {"mdd", "drawdown", "cagr", "volatility", "var", "cvar", "alpha", "tracking_error"}
)


def asset_class_label(value: str) -> str:
    return ASSET_CLASS_LABELS.get(value, value)


def format_money(money: Money) -> str:
    return f"{money.round_to(0).amount:,.0f} {money.currency}"


def percent_value(value: Percentage | Decimal) -> str:
    """부호/단위 없는 백분율 숫자 문자열 (예: "26.85")."""
    ratio = value.ratio if isinstance(value, Percentage) else value
    return str((ratio * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def format_percent(value: Percentage | Decimal) -> str:
    return f"{percent_value(value)}%"


def format_number(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def format_metric(name: str, value: Decimal) -> str:
    return format_percent(value) if name in RATIO_METRICS else format_number(value)


def metric_label(name: str) -> str:
    return METRIC_LABELS.get(name, name)
