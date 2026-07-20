"""evaluate_buy_gate() 테스트. buy_rules.md B-1: 4개 조건 AND — 하나라도 미충족 시 매수 금지."""

from pams.equity.domain.buy_gate import evaluate_buy_gate

_ALL_MET = dict(
    score_condition_met=True,
    score_detail="85점",
    market_grade_condition_met=True,
    market_grade_detail="B",
    price_discount_condition_met=True,
    price_discount_detail="-15%",
    investment_thesis="3년 내 매출 CAGR 15% 지속 가능, 근거: OO",
)


class TestAllConditionsMet:
    def test_all_four_met_passes_gate(self) -> None:
        result = evaluate_buy_gate(**_ALL_MET)
        assert result.all_conditions_met is True
        assert len(result.conditions) == 4


class TestEachConditionCanBlockAlone:
    def test_score_below_80_blocks(self) -> None:
        result = evaluate_buy_gate(**{**_ALL_MET, "score_condition_met": False})
        assert result.all_conditions_met is False
        assert result.condition_for("기업 점수 ≥ 80점").met is False

    def test_market_grade_below_c_blocks(self) -> None:
        result = evaluate_buy_gate(**{**_ALL_MET, "market_grade_condition_met": False})
        assert result.all_conditions_met is False
        assert result.condition_for("시장 상태 C 이상").met is False

    def test_price_not_discounted_blocks(self) -> None:
        result = evaluate_buy_gate(**{**_ALL_MET, "price_discount_condition_met": False})
        assert result.all_conditions_met is False
        assert result.condition_for("DCF 적정가 대비 -10% 이상 할인").met is False

    def test_empty_thesis_blocks(self) -> None:
        result = evaluate_buy_gate(**{**_ALL_MET, "investment_thesis": ""})
        assert result.all_conditions_met is False
        assert result.condition_for("투자 논리 1문장 이상 명문화").met is False

    def test_whitespace_only_thesis_blocks(self) -> None:
        """공백만 있는 논지는 명문화된 것으로 보지 않는다."""
        result = evaluate_buy_gate(**{**_ALL_MET, "investment_thesis": "   \n  "})
        assert result.all_conditions_met is False


class TestPriceDiscountCaution:
    """v1.6.1: DCF·상대지표가 상반될 때 조건3은 통과시키되 불일치를 고지한다
    (valuation_rules.md V-2)."""

    def test_caution_attached_but_gate_still_passes(self) -> None:
        result = evaluate_buy_gate(
            **{**_ALL_MET, "price_discount_caution": "DCF와 상대지표가 상반된다"}
        )
        assert result.all_conditions_met is True
        condition = result.condition_for("DCF 적정가 대비 -10% 이상 할인")
        assert condition is not None
        assert condition.met is True
        assert condition.caution == "DCF와 상대지표가 상반된다"

    def test_no_caution_by_default(self) -> None:
        result = evaluate_buy_gate(**_ALL_MET)
        condition = result.condition_for("DCF 적정가 대비 -10% 이상 할인")
        assert condition is not None
        assert condition.caution is None
