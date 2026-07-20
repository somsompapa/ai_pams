"""evaluate_sell_review() 테스트. sell_rules.md S-1(논리훼손, OR) + S-2(과대평가, 부분매도)."""

from decimal import Decimal

from pams.equity.domain.sell_review import evaluate_sell_review

_NO_SIGNALS = dict(
    revenue_yoy_growth_deceleration_pp=None,
    market_share_declining_two_quarters=False,
    structural_disruption=False,
    dcf_gap_ratio=None,
)


class TestNoSignals:
    def test_nothing_triggered_when_all_clean(self) -> None:
        result = evaluate_sell_review(**_NO_SIGNALS)
        assert result.review_recommended is False
        assert result.thesis_break_triggered is False
        assert result.suggested_sell_fraction is None


class TestThesisBreakIsOrLogic:
    def test_growth_deceleration_alone_triggers_review(self) -> None:
        result = evaluate_sell_review(
            **{**_NO_SIGNALS, "revenue_yoy_growth_deceleration_pp": Decimal("0.06")}
        )
        assert result.thesis_break_triggered is True
        assert result.review_recommended is True

    def test_deceleration_below_threshold_does_not_trigger(self) -> None:
        result = evaluate_sell_review(
            **{**_NO_SIGNALS, "revenue_yoy_growth_deceleration_pp": Decimal("0.04")}
        )
        assert result.thesis_break_triggered is False

    def test_market_share_decline_alone_triggers_review(self) -> None:
        result = evaluate_sell_review(
            **{**_NO_SIGNALS, "market_share_declining_two_quarters": True}
        )
        assert result.thesis_break_triggered is True

    def test_structural_disruption_alone_triggers_review(self) -> None:
        result = evaluate_sell_review(
            **{
                **_NO_SIGNALS,
                "structural_disruption": True,
                "structural_disruption_note": "대체재 등장",
            }
        )
        assert result.thesis_break_triggered is True
        signal = next(s for s in result.thesis_break_signals if s.reason == "산업 구조 변화")
        assert signal.detail == "대체재 등장"


class TestOvervaluation:
    def test_below_50pct_gap_no_signal(self) -> None:
        result = evaluate_sell_review(**{**_NO_SIGNALS, "dcf_gap_ratio": Decimal("0.3")})
        assert result.overvaluation_signal.triggered is False
        assert result.suggested_sell_fraction is None

    def test_50pct_gap_suggests_25pct_sell(self) -> None:
        result = evaluate_sell_review(**{**_NO_SIGNALS, "dcf_gap_ratio": Decimal("0.5")})
        assert result.overvaluation_signal.triggered is True
        assert result.suggested_sell_fraction == Decimal("0.25")

    def test_100pct_gap_suggests_50pct_sell(self) -> None:
        result = evaluate_sell_review(**{**_NO_SIGNALS, "dcf_gap_ratio": Decimal("1.0")})
        assert result.overvaluation_signal.triggered is True
        assert result.suggested_sell_fraction == Decimal("0.50")

    def test_overvaluation_alone_triggers_review_recommended(self) -> None:
        result = evaluate_sell_review(**{**_NO_SIGNALS, "dcf_gap_ratio": Decimal("0.6")})
        assert result.thesis_break_triggered is False
        assert result.review_recommended is True
