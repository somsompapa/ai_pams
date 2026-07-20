"""DCF(현금흐름할인법) 밸류에이션 도메인.

ai_stock 프로젝트(rulebook/valuation_rules.md V-1)의 검증된 로직을 PAMS 컨벤션(Decimal,
값객체, DomainValidationError)으로 이식한다.

설계 원칙:
  - DCF 가정(WACC, 영구성장률, 예측기간, FCF 성장경로)은 호출자가 매번 넘기는 값이다.
    도메인은 이 가정을 코드에 하드코딩하지 않는다.
  - 전부 Decimal — float은 쓰지 않는다.
  - fair_value가 0 이하로 나오면(가정 붕괴) 조용히 계산을 진행하지 않고 예외를 던진다
    (ai_stock v1.1에서 실제로 겪은 버그: 음수 적정가가 그대로 "크게 저평가"로 오판된 사례).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from pams.shared_kernel.domain import DomainValidationError

_DEFAULT_WACC_DELTA = Decimal("0.01")
_DEFAULT_G_DELTA = Decimal("0.005")


class ValuationError(DomainValidationError):
    """DCF 가정 또는 산출값이 수학적으로 성립하지 않는다."""


def project_fcf(base_fcf: Decimal, growth_path: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """기준 FCF에 연도별 성장률을 순차 적용한 예측 FCF. growth_path 길이 = 예측기간 n."""
    if not growth_path:
        raise ValuationError("growth_path(예측기간별 성장률)가 비어 있다")
    fcfs: list[Decimal] = []
    current = base_fcf
    for growth in growth_path:
        current = current * (1 + growth)
        fcfs.append(current)
    return tuple(fcfs)


@dataclass(frozen=True, slots=True)
class DcfAssumptions:
    """DCF 계산에 필요한 전체 가정. 값이 바뀌면 재계산해야 한다(근거 추적을 위해 불변)."""

    base_fcf: Decimal
    wacc: Decimal
    terminal_growth: Decimal
    growth_path: tuple[Decimal, ...]
    net_debt: Decimal = Decimal(0)
    shares_outstanding: Decimal | None = None
    wacc_basis: str = ""

    def __post_init__(self) -> None:
        if self.wacc <= self.terminal_growth:
            raise ValuationError(
                f"WACC({self.wacc})가 영구성장률({self.terminal_growth}) 이하다 — "
                "잔존가치가 발산한다. g < WACC가 필수다."
            )
        if not self.growth_path:
            raise ValuationError("growth_path(예측기간별 성장률)가 비어 있다")
        if self.shares_outstanding is not None and self.shares_outstanding <= 0:
            raise ValuationError(f"발행주식수는 양수여야 한다: {self.shares_outstanding}")


@dataclass(frozen=True, slots=True)
class DcfResult:
    enterprise_value: Decimal
    equity_value: Decimal
    fair_value_per_share: Decimal | None
    pv_explicit: Decimal
    pv_terminal: Decimal
    terminal_value: Decimal
    projected_fcf: tuple[Decimal, ...]
    assumptions: DcfAssumptions


def calculate_dcf(assumptions: DcfAssumptions) -> DcfResult:
    """DCF 적정가치 계산. 계산 구조는 valuation_rules.md V-1과 동일:
    기업가치 = Σ FCFₜ/(1+WACC)ᵗ + 잔존가치/(1+WACC)ⁿ, 잔존가치(Gordon Growth) = FCFₙ×(1+g)/(WACC-g).
    """
    fcfs = project_fcf(assumptions.base_fcf, assumptions.growth_path)
    n = len(fcfs)

    pv_explicit = sum(
        (fcf / (1 + assumptions.wacc) ** (t + 1) for t, fcf in enumerate(fcfs)),
        Decimal(0),
    )
    fcf_n = fcfs[-1]
    terminal_value = (
        fcf_n * (1 + assumptions.terminal_growth) / (assumptions.wacc - assumptions.terminal_growth)
    )
    pv_terminal = terminal_value / (1 + assumptions.wacc) ** n

    enterprise_value = pv_explicit + pv_terminal
    equity_value = enterprise_value - assumptions.net_debt
    fair_value_per_share = (
        equity_value / assumptions.shares_outstanding
        if assumptions.shares_outstanding is not None
        else None
    )

    return DcfResult(
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        fair_value_per_share=fair_value_per_share,
        pv_explicit=pv_explicit,
        pv_terminal=pv_terminal,
        terminal_value=terminal_value,
        projected_fcf=fcfs,
        assumptions=assumptions,
    )


def dcf_sensitivity(
    base: DcfAssumptions,
    *,
    wacc_delta: Decimal = _DEFAULT_WACC_DELTA,
    g_delta: Decimal = _DEFAULT_G_DELTA,
) -> dict[str, Decimal | None]:
    """WACC±wacc_delta × g±g_delta 9칸 그리드의 주당 적정가(단일 숫자 맹신 방지).

    특정 칸의 가정이 성립하지 않으면(WACC<=g 등) 그 칸만 None으로 남긴다.
    """
    grid: dict[str, Decimal | None] = {}
    for w_label, wacc in (
        ("wacc-", base.wacc - wacc_delta),
        ("wacc0", base.wacc),
        ("wacc+", base.wacc + wacc_delta),
    ):
        for g_label, growth in (
            ("g-", base.terminal_growth - g_delta),
            ("g0", base.terminal_growth),
            ("g+", base.terminal_growth + g_delta),
        ):
            try:
                scenario = DcfAssumptions(
                    base_fcf=base.base_fcf,
                    wacc=wacc,
                    terminal_growth=growth,
                    growth_path=base.growth_path,
                    net_debt=base.net_debt,
                    shares_outstanding=base.shares_outstanding,
                )
                grid[f"{w_label}/{g_label}"] = calculate_dcf(scenario).fair_value_per_share
            except ValuationError:
                grid[f"{w_label}/{g_label}"] = None
    return grid


@dataclass(frozen=True, slots=True)
class ValuationGap:
    """밸류에이션(1) DCF 괴리율 판정. company_analysis_rules.md 3-4 (1) 참조."""

    gap_ratio: Decimal  # (현재가 - 적정가) / 적정가
    score: Decimal  # 최대 10
    label: str
    buy_price_condition_met: bool  # buy_rules.md B-1 조건3: -10% 이상 할인


def valuation_gap(current_price: Decimal, fair_value: Decimal) -> ValuationGap:
    """DCF 괴리율 = (현재가-적정가)/적정가.

    ⩽-30%:10점(크게저평가) / -30~-10%:6점(저평가) / -10~+10%:3점(적정) / ⩾+10%:0점(고평가).
    """
    if fair_value <= 0:
        raise ValuationError(
            f"fair_value가 0 이하다({fair_value}) — DCF 가정(WACC/g/기준FCF)이 붕괴했다는 "
            "신호다. 괴리율을 계산하지 않는다(음수 적정가를 그대로 계산하면 "
            "'크게 저평가·10점'처럼 잘못된 매수신호를 낸다). DCF 가정을 재점검할 것."
        )
    gap = (current_price - fair_value) / fair_value
    if gap <= Decimal("-0.30"):
        score, label = Decimal(10), "크게 저평가"
    elif gap <= Decimal("-0.10"):
        score, label = Decimal(6), "저평가"
    elif gap < Decimal("0.10"):
        score, label = Decimal(3), "적정"
    else:
        score, label = Decimal(0), "고평가"
    return ValuationGap(
        gap_ratio=gap, score=score, label=label, buy_price_condition_met=gap <= Decimal("-0.10")
    )


@dataclass(frozen=True, slots=True)
class TriggerZones:
    """매수 적정가 범위 / 매도 검토가 범위 (valuation_rules.md V-1-1).

    민감도 그리드(9칸)의 최솟값~최댓값으로 "가정이 흔들려도 견디는 범위"를 표현한다.
    """

    conservative_fair_value: Decimal
    central_fair_value: Decimal
    optimistic_fair_value: Decimal
    buy_high_confidence_upper: Decimal  # 보수적 적정가 x0.9 이하면 강한 매수 후보
    buy_base_case_upper: Decimal  # 중심 적정가 x0.9 이하면 기준가정에서만 충족
    watch_lower: Decimal
    watch_upper: Decimal
    sell_25pct_lower: Decimal  # 중심 적정가 x1.5 이상 — 25% 매도 검토
    sell_50pct_lower: Decimal  # 중심 적정가 x2.0 이상 — 50% 매도 검토


def trigger_zones(sensitivity_grid: dict[str, Decimal | None]) -> TriggerZones:
    values = [v for v in sensitivity_grid.values() if v is not None]
    if not values:
        raise ValuationError("민감도 그리드에 유효한 적정가가 하나도 없다 — 트리거 구간 산출 불가")
    central = sensitivity_grid.get("wacc0/g0")
    if central is None:
        raise ValuationError("중심 시나리오(wacc0/g0)가 정의되지 않았다 — 트리거 구간 산출 불가")
    conservative = min(values)
    optimistic = max(values)
    return TriggerZones(
        conservative_fair_value=conservative,
        central_fair_value=central,
        optimistic_fair_value=optimistic,
        buy_high_confidence_upper=conservative * Decimal("0.9"),
        buy_base_case_upper=central * Decimal("0.9"),
        watch_lower=central * Decimal("0.9"),
        watch_upper=central * Decimal("1.1"),
        sell_25pct_lower=central * Decimal("1.5"),
        sell_50pct_lower=central * Decimal("2.0"),
    )
