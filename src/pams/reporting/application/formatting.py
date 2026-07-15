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

METRIC_DESCRIPTIONS: dict[str, str] = {
    "mdd": "역사적 고점 대비 가장 크게 떨어졌던 비율 - 최악의 경우 얼마나 잃었는지",
    "drawdown": "지금 시점 고점 대비 얼마나 내려와 있는지",
    "cagr": "연평균 복리 성장률",
    "volatility": "수익률이 얼마나 들쭉날쭉한지(연환산 표준편차) - 높을수록 변동이 크다",
    "sharpe": "위험(변동성) 대비 초과수익 - 높을수록 위험 대비 수익이 좋다",
    "sortino": "하락 변동성만 위험으로 보는 위험조정 수익률 - 상승 변동은 위험으로 치지 않는다",
    "calmar": "연수익률 ÷ 최대낙폭 - 낙폭 대비 수익성",
    "var": "정해진 신뢰수준에서 예상되는 최대 손실률(Value at Risk)",
    "cvar": "VaR를 넘는 손실이 났을 때의 평균 손실률(Conditional VaR)",
    "beta": "벤치마크 대비 민감도 - 1보다 크면 벤치마크보다 더 크게 움직인다",
    "alpha": "벤치마크 대비 초과수익률",
    "correlation": "벤치마크와 얼마나 같이 움직이는지(-1~1)",
    "tracking_error": "벤치마크 대비 수익률이 얼마나 벌어지는지 - 낮을수록 벤치마크를 잘 따라간다",
    "concentration_hhi": "허핀달-허쉬만 지수 - 특정 종목·자산에 쏠려 있을수록 높다",
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


def metric_description(name: str) -> str:
    return METRIC_DESCRIPTIONS.get(name, "")
