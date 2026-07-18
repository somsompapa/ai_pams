"""매수 필수조건(buy_rules.md B-1) — AND 게이트: 4개 조건을 모두 충족해야 매수 후보.

하나라도 미충족이면 매수 금지다. 조건2(시장 상태)는 equity 도메인이 직접 계산하지
않는다(market_regime 컨텍스트의 책임) — 이미 판정된 불리언만 받는다. 도메인 계층끼리
서로의 내부 타입을 참조하지 않게 하기 위한 경계다(컨텍스트 간 결합 방지). 실제로 두
컨텍스트의 결과를 모으는 일은 application/API 계층이 한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BuyGateCondition:
    condition: str
    met: bool
    detail: str
    # v1.6.1: DCF는 조건3을 충족해도 상대지표(PER/PBR/PEG)가 정반대 신호(richly-valued)를
    # 주면, 조건 자체는 통과시키되(AND 게이트를 막지 않음) 그 불일치를 여기 남긴다 —
    # valuation_rules.md V-2 "DCF와 상대지표가 상반되면 불일치를 명시" 요건.
    caution: str | None = None


@dataclass(frozen=True, slots=True)
class BuyGateResult:
    """conditions는 항상 4개, buy_rules.md B-1의 순서(점수→시장→가격할인→투자논리)."""

    conditions: tuple[BuyGateCondition, ...]

    @property
    def all_conditions_met(self) -> bool:
        return all(c.met for c in self.conditions)

    def condition_for(self, name: str) -> BuyGateCondition | None:
        return next((c for c in self.conditions if c.condition == name), None)


def evaluate_buy_gate(
    *,
    score_condition_met: bool,
    score_detail: str,
    market_grade_condition_met: bool,
    market_grade_detail: str,
    price_discount_condition_met: bool,
    price_discount_detail: str,
    investment_thesis: str,
    price_discount_caution: str | None = None,
) -> BuyGateResult:
    """buy_rules.md B-1의 4개 AND 조건을 평가한다.

    investment_thesis는 "1문장 이상 명문화"(B-1 조건4) 요건의 최소 구조적 검증만
    한다 — 공백 제거 후 비어있지 않으면 충족으로 본다(문장 품질까지 AI가 판단하지
    않는다, CLAUDE.md 절대원칙 #1: AI는 계산·판단하지 않고 결과만 서술한다).
    """
    thesis_stripped = investment_thesis.strip()
    thesis_met = len(thesis_stripped) > 0

    return BuyGateResult(
        conditions=(
            BuyGateCondition(
                condition="기업 점수 ≥ 80점", met=score_condition_met, detail=score_detail
            ),
            BuyGateCondition(
                condition="시장 상태 C 이상",
                met=market_grade_condition_met,
                detail=market_grade_detail,
            ),
            BuyGateCondition(
                condition="DCF 적정가 대비 -10% 이상 할인",
                met=price_discount_condition_met,
                detail=price_discount_detail,
                caution=price_discount_caution,
            ),
            BuyGateCondition(
                condition="투자 논리 1문장 이상 명문화",
                met=thesis_met,
                detail=thesis_stripped if thesis_met else "미입력",
            ),
        )
    )
