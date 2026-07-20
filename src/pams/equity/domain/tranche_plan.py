"""분할매수 추적 + 데이터누락/논리훼손 구분 (buy_rules.md B-2, v1.6.1 확장).

한 번에 전량 매수하지 않고 하락을 활용해 분할한다 — 1차 30%, 2차(1차 대비 -10%
하락 시) 30% 추가, 3차(1차 대비 -20% 하락 시) 40% 추가. 하락 중 기업 점수가
최초 대비 10점 이상 하락(투자 논리 훼손)했다면 추가매수를 즉시 중단한다.

v1.6.1 신규: 하락분이 전적으로 "데이터 누락" 항목에서 발생했고 실제 펀더멘털
변화 근거가 없다면, 즉시 중단하지 말고 먼저 데이터를 보완해 재채점한 뒤
판단한다 — company_analysis_rules.md 3-7의 "데이터 누락 항목은 0점 처리" 원칙을
채점 시엔 정직한 처리이지만, 여기서는 점수의 하락폭을 트리거로 쓰므로 그대로
적용하면 데이터 공급자 일시 오류만으로 추가매수가 잘못 중단되는 함정이 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pams.shared_kernel.domain import DomainValidationError

_SCORE_DROP_THRESHOLD = Decimal(10)
_SECOND_TRANCHE_DROP_PCT = Decimal("-0.10")
_THIRD_TRANCHE_DROP_PCT = Decimal("-0.20")
_TRANCHE_FRACTIONS: dict[int, Decimal] = {2: Decimal("0.30"), 3: Decimal("0.40")}


@dataclass(frozen=True, slots=True)
class ScoreItemSnapshot:
    metric: str
    score: Decimal
    missing: bool


@dataclass(frozen=True, slots=True)
class ScoreSnapshot:
    total_score: Decimal
    items: tuple[ScoreItemSnapshot, ...]


@dataclass(frozen=True, slots=True)
class TranchePlan:
    asset_id: str
    first_tranche_price: Decimal
    target_quantity: Decimal
    baseline: ScoreSnapshot
    tranches_bought: int  # 1~3, 최초 등록 시 1
    created_at: date

    def __post_init__(self) -> None:
        if not (1 <= self.tranches_bought <= 3):
            raise DomainValidationError(f"tranches_bought는 1~3이어야 한다: {self.tranches_bought}")
        if self.first_tranche_price <= 0:
            raise DomainValidationError(f"1차 매수가는 양수여야 한다: {self.first_tranche_price}")
        if self.target_quantity <= 0:
            raise DomainValidationError(f"목표 수량은 양수여야 한다: {self.target_quantity}")


@dataclass(frozen=True, slots=True)
class TrancheEvaluation:
    next_tranche: int | None  # 2 또는 3. 이미 3차까지 완료했으면 None.
    price_drop_pct: Decimal
    price_trigger_met: bool
    total_score_drop: Decimal
    real_score_drop: Decimal  # 데이터 누락으로 새로 빠진 항목의 하락분 제외
    logic_broken: bool
    data_gap_only: bool
    recommended_amount_fraction: Decimal | None
    note: str


def _newly_missing(baseline: ScoreItemSnapshot, current: ScoreItemSnapshot) -> bool:
    """baseline엔 실값이 있었는데 현재는 결측이 됐다면(데이터 공급자 일시 오류 등),
    그 하락분은 실제 펀더멘털 변화 근거로 보지 않는다."""
    return current.missing and not baseline.missing


def evaluate_tranche(
    *, plan: TranchePlan, current_price: Decimal, current: ScoreSnapshot
) -> TrancheEvaluation:
    next_tranche = plan.tranches_bought + 1 if plan.tranches_bought < 3 else None
    price_drop_pct = (current_price - plan.first_tranche_price) / plan.first_tranche_price
    total_drop = plan.baseline.total_score - current.total_score

    if next_tranche is None:
        return TrancheEvaluation(
            next_tranche=None,
            price_drop_pct=price_drop_pct,
            price_trigger_met=False,
            total_score_drop=total_drop,
            real_score_drop=Decimal(0),
            logic_broken=False,
            data_gap_only=False,
            recommended_amount_fraction=None,
            note="이미 3차까지 완료됨 — 더 이상 분할매수 계획이 없다",
        )

    threshold = _SECOND_TRANCHE_DROP_PCT if next_tranche == 2 else _THIRD_TRANCHE_DROP_PCT
    price_trigger_met = price_drop_pct <= threshold

    baseline_by_metric = {item.metric: item for item in plan.baseline.items}
    real_drop = Decimal(0)
    for current_item in current.items:
        baseline_item = baseline_by_metric.get(current_item.metric)
        if baseline_item is None or _newly_missing(baseline_item, current_item):
            continue
        real_drop += baseline_item.score - current_item.score

    logic_broken = real_drop >= _SCORE_DROP_THRESHOLD
    data_gap_only = total_drop >= _SCORE_DROP_THRESHOLD and not logic_broken

    fraction: Decimal | None
    if not price_trigger_met:
        note = f"{next_tranche}차 매수 가격 트리거 미도달(1차 대비 {price_drop_pct:.2%})"
        fraction = None
    elif logic_broken:
        note = (
            f"투자 논리 훼손 — 데이터 누락을 제외한 실질 점수가 {real_drop}점 하락. "
            "추가매수 중단 권고(buy_rules.md B-2)."
        )
        fraction = None
    elif data_gap_only:
        note = (
            f"점수가 {total_drop}점 하락했으나 데이터 누락에서만 발생 — 즉시 중단 대상이 "
            "아니다. 데이터를 보완해 재채점한 뒤 판단하라."
        )
        fraction = None
    else:
        pct = _TRANCHE_FRACTIONS[next_tranche] * 100
        note = f"{next_tranche}차 매수 조건 충족 (목표수량의 {pct:.0f}%)"
        fraction = _TRANCHE_FRACTIONS[next_tranche]

    return TrancheEvaluation(
        next_tranche=next_tranche,
        price_drop_pct=price_drop_pct,
        price_trigger_met=price_trigger_met,
        total_score_drop=total_drop,
        real_score_drop=real_drop,
        logic_broken=logic_broken,
        data_gap_only=data_gap_only,
        recommended_amount_fraction=fraction,
        note=note,
    )
