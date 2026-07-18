"""evaluate_tranche() 테스트 — buy_rules.md B-2 분할매수(30/30/40%) + v1.6.1
데이터누락/논리훼손 구분 회귀 테스트."""

from datetime import date
from decimal import Decimal

from pams.equity.domain.tranche_plan import (
    ScoreItemSnapshot,
    ScoreSnapshot,
    TranchePlan,
    evaluate_tranche,
)


def _snapshot(total: str, items: dict[str, tuple[str, bool]]) -> ScoreSnapshot:
    return ScoreSnapshot(
        total_score=Decimal(total),
        items=tuple(
            ScoreItemSnapshot(metric=metric, score=Decimal(score), missing=missing)
            for metric, (score, missing) in items.items()
        ),
    )


def _plan(tranches_bought: int = 1, baseline: ScoreSnapshot | None = None) -> TranchePlan:
    return TranchePlan(
        asset_id="TEST",
        first_tranche_price=Decimal(100),
        target_quantity=Decimal(100),
        baseline=baseline or _snapshot("85", {"ROE": ("10", False), "EPS 3Y CAGR": ("8", False)}),
        tranches_bought=tranches_bought,
        created_at=date(2026, 1, 1),
    )


class TestPriceTrigger:
    def test_second_tranche_not_triggered_above_minus_10_pct(self) -> None:
        result = evaluate_tranche(
            plan=_plan(tranches_bought=1),
            current_price=Decimal(95),  # -5%
            current=_snapshot("85", {"ROE": ("10", False), "EPS 3Y CAGR": ("8", False)}),
        )
        assert result.next_tranche == 2
        assert result.price_trigger_met is False
        assert result.recommended_amount_fraction is None

    def test_second_tranche_triggered_at_exactly_minus_10_pct(self) -> None:
        result = evaluate_tranche(
            plan=_plan(tranches_bought=1),
            current_price=Decimal(90),  # -10%
            current=_snapshot("85", {"ROE": ("10", False), "EPS 3Y CAGR": ("8", False)}),
        )
        assert result.price_trigger_met is True
        assert result.recommended_amount_fraction == Decimal("0.30")

    def test_third_tranche_requires_minus_20_pct_not_minus_10(self) -> None:
        result = evaluate_tranche(
            plan=_plan(tranches_bought=2),
            current_price=Decimal(85),  # -15%, 3차 기준(-20%) 미도달
            current=_snapshot("85", {"ROE": ("10", False), "EPS 3Y CAGR": ("8", False)}),
        )
        assert result.next_tranche == 3
        assert result.price_trigger_met is False

    def test_third_tranche_triggered_at_minus_20_pct(self) -> None:
        result = evaluate_tranche(
            plan=_plan(tranches_bought=2),
            current_price=Decimal(80),  # -20%
            current=_snapshot("85", {"ROE": ("10", False), "EPS 3Y CAGR": ("8", False)}),
        )
        assert result.price_trigger_met is True
        assert result.recommended_amount_fraction == Decimal("0.40")

    def test_no_more_tranches_after_third_bought(self) -> None:
        result = evaluate_tranche(
            plan=_plan(tranches_bought=3),
            current_price=Decimal(50),
            current=_snapshot("85", {}),
        )
        assert result.next_tranche is None
        assert result.recommended_amount_fraction is None


class TestLogicBreakVsDataGap:
    """v1.6.1 핵심 회귀 테스트: 데이터 누락으로 인한 하락과 실제 논리훼손을
    구분해야 한다."""

    def test_real_fundamental_drop_halts_further_buying(self) -> None:
        baseline = _snapshot("85", {"ROE": ("10", False), "EPS 3Y CAGR": ("8", False)})
        current = _snapshot(
            "75",
            {"ROE": ("0", False), "EPS 3Y CAGR": ("8", False)},  # ROE 실값이 10→0으로 하락
        )
        result = evaluate_tranche(
            plan=_plan(tranches_bought=1, baseline=baseline),
            current_price=Decimal(90),  # 2차 트리거 충족
            current=current,
        )
        assert result.logic_broken is True
        assert result.data_gap_only is False
        assert result.recommended_amount_fraction is None

    def test_drop_caused_only_by_newly_missing_data_does_not_halt(self) -> None:
        """baseline엔 ROE가 실값(10점)이었는데 현재는 데이터 누락(0점)이 됐다 —
        총점은 10점 이상 빠졌지만 실질 하락은 아니므로 즉시 중단하지 않는다."""
        baseline = _snapshot("85", {"ROE": ("10", False), "EPS 3Y CAGR": ("8", False)})
        current = _snapshot("75", {"ROE": ("0", True), "EPS 3Y CAGR": ("8", False)})
        result = evaluate_tranche(
            plan=_plan(tranches_bought=1, baseline=baseline),
            current_price=Decimal(90),
            current=current,
        )
        assert result.total_score_drop == Decimal(10)
        assert result.real_score_drop == Decimal(0)
        assert result.logic_broken is False
        assert result.data_gap_only is True
        assert result.recommended_amount_fraction is None

    def test_already_missing_at_baseline_does_not_inflate_real_drop(self) -> None:
        """baseline에서도 이미 데이터 누락이었던 항목은(신규 결측이 아니므로)
        real_score_drop 계산에서 제외 대상이 아니다 — 애초에 델타가 0이라 영향 없음."""
        baseline = _snapshot("80", {"ROE": ("0", True), "EPS 3Y CAGR": ("8", False)})
        current = _snapshot("80", {"ROE": ("0", True), "EPS 3Y CAGR": ("8", False)})
        result = evaluate_tranche(
            plan=_plan(tranches_bought=1, baseline=baseline),
            current_price=Decimal(90),
            current=current,
        )
        assert result.real_score_drop == Decimal(0)
        assert result.logic_broken is False

    def test_score_drop_below_threshold_proceeds_normally(self) -> None:
        baseline = _snapshot("85", {"ROE": ("10", False)})
        current = _snapshot("80", {"ROE": ("5", False)})  # 5점 하락, 10점 미만
        result = evaluate_tranche(
            plan=_plan(tranches_bought=1, baseline=baseline),
            current_price=Decimal(90),
            current=current,
        )
        assert result.logic_broken is False
        assert result.data_gap_only is False
        assert result.recommended_amount_fraction == Decimal("0.30")

    def test_new_metric_not_present_in_baseline_is_ignored(self) -> None:
        """baseline에 없던(항목 자체가 새로 추가된) metric은 비교 대상이 아니므로
        real_score_drop 계산에서 조용히 건너뛴다."""
        baseline = _snapshot("85", {"ROE": ("10", False)})
        current = _snapshot("85", {"ROE": ("10", False), "새항목": ("5", False)})
        result = evaluate_tranche(
            plan=_plan(tranches_bought=1, baseline=baseline),
            current_price=Decimal(90),
            current=current,
        )
        assert result.real_score_drop == Decimal(0)
