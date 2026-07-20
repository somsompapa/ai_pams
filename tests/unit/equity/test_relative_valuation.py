"""relative_valuation_score() 테스트. valuation_rules.md V-2: PER 밴드(최대5) +
PBR 밴드(최대3) + PEG 보정(±2) = 최대 10점, 최저 0점."""

from decimal import Decimal

from pams.equity.domain.relative_valuation import relative_valuation_score


class TestRelativeValuationScore:
    def test_typical_case_sums_all_three_components(self, scoring_config) -> None:  # type: ignore[no-untyped-def]
        result = relative_valuation_score(
            per_band_percentile=Decimal("0.15"),  # 하위 20% 이내 → 5*1.00=5
            pbr_band_percentile=Decimal("0.50"),  # 40~60% → 3*0.50=1.5
            peg=Decimal("0.8"),  # <1.0 → +2
            config=scoring_config.relative_valuation,
        )
        assert result.per_score == Decimal("5.00")
        assert result.pbr_score == Decimal("1.50")
        assert result.peg_adjustment == Decimal(2)
        assert result.score == Decimal("8.50")
        assert result.missing == ()

    def test_missing_per_treated_as_zero_and_flagged(self, scoring_config) -> None:  # type: ignore[no-untyped-def]
        result = relative_valuation_score(
            per_band_percentile=None,
            pbr_band_percentile=Decimal("0.50"),
            peg=Decimal("1.5"),  # 1.0~2.0 → 0
            config=scoring_config.relative_valuation,
        )
        assert result.per_score is None
        assert result.missing == ("PER밴드",)
        assert result.score == Decimal("1.50")  # pbr만 반영, per는 0으로 처리
        assert "임의" not in result.note  # note 존재는 확인하되 문구는 별도 검증
        assert result.note != ""

    def test_all_missing_yields_zero_score(self, scoring_config) -> None:  # type: ignore[no-untyped-def]
        result = relative_valuation_score(
            per_band_percentile=None,
            pbr_band_percentile=None,
            peg=None,
            config=scoring_config.relative_valuation,
        )
        assert result.score == Decimal(0)
        assert result.missing == ("PER밴드", "PBR밴드")
        assert result.peg_adjustment == Decimal(0)

    def test_score_clamped_to_zero_when_peg_penalty_exceeds_band_scores(
        self, scoring_config
    ) -> None:  # type: ignore[no-untyped-def]
        """상단 구간(배점비율 0) + PEG 고평가(-2) 조합이면 합계가 음수가 될 수 있다 —
        0으로 클램프해야 한다(최저 0점)."""
        result = relative_valuation_score(
            per_band_percentile=Decimal("0.9"),  # 상단 → 0
            pbr_band_percentile=Decimal("0.9"),  # 상단 → 0
            peg=Decimal("3.0"),  # >2.0 → -2
            config=scoring_config.relative_valuation,
        )
        assert result.score == Decimal(0)

    def test_score_never_exceeds_ten(self, scoring_config) -> None:  # type: ignore[no-untyped-def]
        result = relative_valuation_score(
            per_band_percentile=Decimal("0.1"),  # 최하단 → 5
            pbr_band_percentile=Decimal("0.1"),  # 최하단 → 3
            peg=Decimal("0.5"),  # <1.0 → +2
            config=scoring_config.relative_valuation,
        )
        assert result.score == Decimal(10)
