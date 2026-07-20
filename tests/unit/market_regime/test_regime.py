"""grade_market_regime() 테스트. market_analysis_rules.md 4-2의 두 예시를 정확히 재현한다."""

from datetime import date
from decimal import Decimal

from pams.market_regime.domain.grade import Grade
from pams.market_regime.domain.regime import (
    CIRCUIT_BREAKER,
    KOSPI_FOREIGN_FLOW,
    SP500_PER,
    TREASURY_10Y,
    VIX,
    grade_market_regime,
)


class TestMajorityVoteRulebookExamples:
    def test_example_1_clear_majority_a(self, regime_config) -> None:  # type: ignore[no-untyped-def]
        """4-2 예시1: VIX 13(A)·10년물 안정(A)·PER 중단(B)·외국인 순매수지속(A)·
        서킷브레이커 없음(C) → A 3표, B 1표, C 1표 → 최종 A."""
        observations = {
            VIX: Decimal("13"),
            TREASURY_10Y: "stable_or_down",
            SP500_PER: "mid",
            KOSPI_FOREIGN_FLOW: "net_buy",
            CIRCUIT_BREAKER: Decimal("0"),
        }
        result = grade_market_regime(observations, regime_config, as_of=date(2026, 7, 17))
        assert result.final_grade == Grade.A
        assert result.tie_broken is False
        assert result.buy_allowed is True

    def test_example_2_tie_adopts_conservative_grade(self, regime_config) -> None:  # type: ignore[no-untyped-def]
        """4-2 예시2: VIX 22(C)·10년물 급등+35bp(D)·PER 상단근접(D)·외국인 순매수전환(B)·
        서킷브레이커 없음(C) → C 2표, D 2표, B 1표 → 동률(C·D) → 보수적 채택으로 최종 D."""
        observations = {
            VIX: Decimal("22"),
            TREASURY_10Y: "spike",
            SP500_PER: "near_upper",
            KOSPI_FOREIGN_FLOW: "turning_buy",
            CIRCUIT_BREAKER: Decimal("0"),
        }
        result = grade_market_regime(observations, regime_config, as_of=date(2026, 7, 17))
        assert result.final_grade == Grade.D
        assert result.tie_broken is True
        assert result.buy_allowed is False


class TestCircuitBreakerNoSignalIsNeutralNotBullish:
    def test_no_drop_grades_c_not_a(self, regime_config) -> None:  # type: ignore[no-untyped-def]
        """v1.1 버그 회귀: 급락이 없어도 A가 아니라 C(중립)여야 한다 — "없음"이 상시
        강세표로 다수결에 편향 주입되는 문제 재발 방지."""
        observations = {CIRCUIT_BREAKER: Decimal("0.5")}
        result = grade_market_regime(observations, regime_config)
        cb_grade = next(ig for ig in result.indicator_grades if ig.indicator == CIRCUIT_BREAKER)
        assert cb_grade.grade == Grade.C

    def test_minus_five_to_eight_grades_d(self, regime_config) -> None:  # type: ignore[no-untyped-def]
        observations = {CIRCUIT_BREAKER: Decimal("-6.0")}
        result = grade_market_regime(observations, regime_config)
        cb_grade = next(ig for ig in result.indicator_grades if ig.indicator == CIRCUIT_BREAKER)
        assert cb_grade.grade == Grade.D

    def test_over_eight_pct_drop_grades_e(self, regime_config) -> None:  # type: ignore[no-untyped-def]
        observations = {CIRCUIT_BREAKER: Decimal("-8.5")}
        result = grade_market_regime(observations, regime_config)
        cb_grade = next(ig for ig in result.indicator_grades if ig.indicator == CIRCUIT_BREAKER)
        assert cb_grade.grade == Grade.E


class TestInsufficientData:
    def test_fewer_than_three_graded_indicators_is_judgment_withheld(self, regime_config) -> None:  # type: ignore[no-untyped-def]
        """4-4: 남은 지표가 3개 미만이면 임의 등급 부여 없이 '판단 보류'(final_grade=None)."""
        observations = {VIX: Decimal("13"), TREASURY_10Y: "stable_or_down"}
        result = grade_market_regime(observations, regime_config)
        assert result.final_grade is None
        assert result.buy_allowed is False

    def test_missing_indicator_excluded_not_defaulted(self, regime_config) -> None:  # type: ignore[no-untyped-def]
        observations = {
            VIX: Decimal("13"),
            TREASURY_10Y: "stable_or_down",
            SP500_PER: "mid",
            # kospi_foreign_flow, circuit_breaker 미입력
        }
        result = grade_market_regime(observations, regime_config)
        missing = [ig for ig in result.indicator_grades if ig.grade is None]
        assert len(missing) == 2
        assert all(ig.observed == "데이터 누락" for ig in missing)
        assert result.final_grade is not None  # 3개는 확보됨


class TestBuyAllowed:
    def test_grade_d_blocks_buy(self, regime_config) -> None:  # type: ignore[no-untyped-def]
        observations = {
            VIX: Decimal("30"),
            TREASURY_10Y: "spike",
            SP500_PER: "near_upper",
            KOSPI_FOREIGN_FLOW: "turning_sell",
            CIRCUIT_BREAKER: Decimal("-6"),
        }
        result = grade_market_regime(observations, regime_config)
        assert result.final_grade == Grade.D
        assert result.buy_allowed is False

    def test_grade_c_allows_buy(self, regime_config) -> None:  # type: ignore[no-untyped-def]
        observations = {
            VIX: Decimal("22"),
            TREASURY_10Y: "flat",
            SP500_PER: "upper_mid",
            KOSPI_FOREIGN_FLOW: "mixed",
            CIRCUIT_BREAKER: Decimal("0"),
        }
        result = grade_market_regime(observations, regime_config)
        assert result.final_grade == Grade.C
        assert result.buy_allowed is True
