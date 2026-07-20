"""매도 판단 보조(sell_rules.md 5장). 매도는 논리 훼손이 최우선 — 가격이 아니라
투자 논리가 깨졌을 때 판다. 이 모듈은 기계적 자동집행을 하지 않는다(원칙 6: AI는
제안만 한다) — 신호를 구조적으로 드러낼 뿐, 실행 여부는 항상 사용자 확인 사항이다.

S-1(논리훼손, OR — 하나라도 발생하면 검토): 성장 둔화(YoY 5%p 이상 둔화)·점유율
2분기 연속 하락·산업구조 변화.
S-2(과대평가, 부분매도 검토): DCF 괴리율 +50%↑ → 25%, +100%↑ → 50%.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# S-1 성장 둔화 임계값(전년 대비 YoY 성장률 둔화폭, %p). 3장 매출 3Y CAGR과는 다른
# 지표다(연도별 YoY 변화폭 vs 3개년 연평균 복리성장률) — 혼동 금지, rulebook 명시.
_GROWTH_DECELERATION_THRESHOLD = Decimal("0.05")

# S-2 과대평가 임계값(DCF 괴리율 = (현재가-적정가)/적정가).
_OVERVALUATION_50PCT_SELL = Decimal("1.0")  # +100% 이상 → 50% 매도 검토
_OVERVALUATION_25PCT_SELL = Decimal("0.5")  # +50% 이상 → 25% 매도 검토


@dataclass(frozen=True, slots=True)
class SellSignal:
    reason: str
    triggered: bool
    detail: str


@dataclass(frozen=True, slots=True)
class SellReviewResult:
    thesis_break_signals: tuple[SellSignal, ...]  # 3개, OR — 하나라도 triggered면 검토
    overvaluation_signal: SellSignal
    suggested_sell_fraction: Decimal | None  # 0.25 / 0.50 / None(과대평가 아님)

    @property
    def thesis_break_triggered(self) -> bool:
        return any(signal.triggered for signal in self.thesis_break_signals)

    @property
    def review_recommended(self) -> bool:
        """S-1 또는 S-2 중 하나라도 해당하면 매도 검토를 권고한다.
        자동집행 아님 — 사용자 최종 확인 필수(S-4 체크리스트)."""
        return self.thesis_break_triggered or self.overvaluation_signal.triggered


def evaluate_sell_review(
    *,
    revenue_yoy_growth_deceleration_pp: Decimal | None,
    market_share_declining_two_quarters: bool,
    structural_disruption: bool,
    structural_disruption_note: str = "",
    dcf_gap_ratio: Decimal | None,
) -> SellReviewResult:
    """매수 시 명문화한 투자 논리(buy_gate의 investment_thesis)와 대조해 판단할 신호를
    조립한다. 값이 없으면(임의 추정 금지) 해당 신호는 미충족으로 처리하고 사유를
    "미입력"으로 남긴다."""
    thesis_signals = (
        SellSignal(
            reason="성장 둔화(YoY)",
            triggered=(
                revenue_yoy_growth_deceleration_pp is not None
                and revenue_yoy_growth_deceleration_pp >= _GROWTH_DECELERATION_THRESHOLD
            ),
            detail=(
                f"YoY 성장률 둔화폭 {revenue_yoy_growth_deceleration_pp}(≥5%p 기준)"
                if revenue_yoy_growth_deceleration_pp is not None
                else "미입력"
            ),
        ),
        SellSignal(
            reason="점유율 하락(2분기 연속)",
            triggered=market_share_declining_two_quarters,
            detail="2분기 연속 하락" if market_share_declining_two_quarters else "해당 없음",
        ),
        SellSignal(
            reason="산업 구조 변화",
            triggered=structural_disruption,
            detail=structural_disruption_note if structural_disruption else "해당 없음",
        ),
    )

    overvaluation_signal: SellSignal
    suggested_sell_fraction: Decimal | None
    if dcf_gap_ratio is None:
        overvaluation_signal = SellSignal(
            reason="과대평가(DCF 괴리율)", triggered=False, detail="DCF 괴리율 미확보"
        )
        suggested_sell_fraction = None
    elif dcf_gap_ratio >= _OVERVALUATION_50PCT_SELL:
        overvaluation_signal = SellSignal(
            reason="과대평가(DCF 괴리율)",
            triggered=True,
            detail=f"괴리율 {dcf_gap_ratio} — +100% 이상, 보유분 50% 매도 검토",
        )
        suggested_sell_fraction = Decimal("0.50")
    elif dcf_gap_ratio >= _OVERVALUATION_25PCT_SELL:
        overvaluation_signal = SellSignal(
            reason="과대평가(DCF 괴리율)",
            triggered=True,
            detail=f"괴리율 {dcf_gap_ratio} — +50% 이상, 보유분 25% 매도 검토",
        )
        suggested_sell_fraction = Decimal("0.25")
    else:
        overvaluation_signal = SellSignal(
            reason="과대평가(DCF 괴리율)", triggered=False, detail=f"괴리율 {dcf_gap_ratio}"
        )
        suggested_sell_fraction = None

    return SellReviewResult(
        thesis_break_signals=thesis_signals,
        overvaluation_signal=overvaluation_signal,
        suggested_sell_fraction=suggested_sell_fraction,
    )
