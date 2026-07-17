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
