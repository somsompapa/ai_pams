"""상대지표(PER/PBR/PEG) 밸류에이션 도메인. company_analysis_rules.md 3-4 (2)/
valuation_rules.md V-2 — DCF를 교차검증하는 보조지표(절대 기준 아님).

PER 밴드(최대5) + PBR 밴드(최대3) + PEG 보정(±2) = 최대 10점, 최저 0점.

v1.1 정정 이식: v1.0 rulebook은 "밴드 하단 근접 → 가점"처럼 숫자 임계값 없이
서술되어 있어 "임계값 없는 느낌 기반 등급 부여 금지" 원칙을 시스템 스스로 위반하고
있었다. 이 파일은 rulebook이 명시한 정량 표를 그대로 구현한다(ai_stock
valuation.relative_valuation_score() 이식).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pams.shared_kernel.domain import BandTable


@dataclass(frozen=True, slots=True)
class RelativeValuationConfig:
    per_max_score: Decimal  # 5
    pbr_max_score: Decimal  # 3
    # 5년 밴드 내 백분위(0=최하단/가장 저평가 ~ 1=최상단) → 배점비율(0~1).
    # PER/PBR 공통 표(valuation_rules.md V-2 (1)) — LOWER_IS_BETTER: 백분위가
    # 낮을수록(저평가에 가까울수록) 배점비율이 높다.
    percentile_ratio: BandTable
    # PEG(=PER÷EPS성장률%) → 보정(-2~+2). LOWER_IS_BETTER: PEG가 낮을수록 보정이 크다.
    peg_adjustment: BandTable


@dataclass(frozen=True, slots=True)
class RelativeValuationResult:
    score: Decimal  # 0~10으로 클램프된 합산 점수
    per_score: Decimal | None  # None이면 데이터 누락(0으로 처리했다는 뜻이지 무점수가 아님)
    pbr_score: Decimal | None
    peg_adjustment: Decimal
    missing: tuple[str, ...]
    note: str


def relative_valuation_score(
    per_band_percentile: Decimal | None,
    pbr_band_percentile: Decimal | None,
    peg: Decimal | None,
    config: RelativeValuationConfig,
) -> RelativeValuationResult:
    """PER/PBR 5년 밴드 백분위 + PEG로 상대지표 점수(0~10)를 계산한다.

    percentile은 해당 종목 **자신의** 과거 5년 PER/PBR 밴드 내 현재 위치다(업종
    평균이 아니다 — V-2 (1) 참고). 데이터 누락 시 해당 구성요소는 0점 처리하고
    missing에 표시한다(임의 추정 금지).
    """
    per_score = (
        None
        if per_band_percentile is None
        else config.percentile_ratio.score_for(per_band_percentile).score * config.per_max_score
    )
    pbr_score = (
        None
        if pbr_band_percentile is None
        else config.percentile_ratio.score_for(pbr_band_percentile).score * config.pbr_max_score
    )
    peg_adjustment = Decimal(0) if peg is None else config.peg_adjustment.score_for(peg).score

    missing = tuple(
        name
        for name, value in (("PER밴드", per_band_percentile), ("PBR밴드", pbr_band_percentile))
        if value is None
    )
    total = (per_score or Decimal(0)) + (pbr_score or Decimal(0)) + peg_adjustment
    total = max(Decimal(0), min(Decimal(10), total))

    return RelativeValuationResult(
        score=total,
        per_score=per_score,
        pbr_score=pbr_score,
        peg_adjustment=peg_adjustment,
        missing=missing,
        note=(
            "missing 항목은 0으로 처리됨 — 근거 없는 가점 금지(원 데이터 확보 시 재계산 권장)"
            if missing
            else ""
        ),
    )
