"""시장 국면 판정(4장): 지표별 A~E 등급 → 다수결(동률 시 보수적 채택) → 최종 등급.

market_analysis_rules.md 4장을 그대로 구현한다:
  - 가중합이 아니라 각 지표를 동등한 1표로 보고 다수결한다(4장 서두: 가중치 근거 없음).
  - 동률이면 더 위험한(E에 가까운) 등급을 채택한다(4-2).
  - 자동조회 실패·미입력 지표는 판정에서 제외하되, 남은 지표가 min_indicators_required
    미만이면 "판단 보류"로 처리한다(4-4: 임의 등급 부여 금지).

BandTable/CategoricalTable(shared_kernel)을 그대로 재사용한다 — 다만 여기서는 "점수"가
아니라 "등급"을 표현하는 데 쓴다: Band.label / CategoricalOption.label에
"<A~E 등급>:<사람이 읽는 근거>" 형식 문자열을 담고(예: "C:20~25 구간"), Band.score /
CategoricalOption.score는 등급 서수(0=A~4=E, 참고용, 판정 로직에는 쓰지 않음)로 채운다.
새 구간표 자료구조를 중복 정의하지 않기 위한 재사용이다(CLAUDE.md 원칙 #7).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pams.market_regime.domain.grade import Grade
from pams.shared_kernel.domain import BandTable, CategoricalTable

# 표에 있는 지표 키(관측값 딕셔너리의 키와 정확히 일치해야 한다).
VIX = "vix"
CIRCUIT_BREAKER = "circuit_breaker"  # KOSPI 전일 대비 등락률(%), 예: -5.3
TREASURY_10Y = "treasury_10y"  # 범주: stable_or_down / mild_up / flat / spike / spike_continued
SP500_PER = "sp500_per"  # 범주: lower_mid / mid / upper_mid / near_upper / above_upper
KOSPI_FOREIGN_FLOW = "kospi_foreign_flow"  # net_buy/turning_buy/mixed/turning_sell/heavy_sell

ALL_INDICATORS: tuple[str, ...] = (
    VIX,
    CIRCUIT_BREAKER,
    TREASURY_10Y,
    SP500_PER,
    KOSPI_FOREIGN_FLOW,
)

_ACTION_GUIDANCE: dict[Grade, str] = {
    Grade.A: "공격적 투자",
    Grade.B: "분할매수",
    Grade.C: "보유",
    Grade.D: "신규투자 축소",
    Grade.E: "현금 확보",
}


def _split_grade_label(label: str) -> tuple[Grade, str]:
    """ "C:20~25 구간" → (Grade.C, "20~25 구간"). 콜론이 없으면 라벨 전체를 등급으로 본다."""
    grade_part, _, basis_part = label.partition(":")
    return Grade(grade_part), basis_part or label


@dataclass(frozen=True, slots=True)
class IndicatorGrade:
    indicator: str
    observed: str  # 사람이 읽는 관측값 표현("22.4", "데이터 누락" 등)
    grade: Grade | None  # None이면 판정 제외(데이터 누락)
    basis: str  # 어느 구간/범주에 해당해 이 등급이 나왔는지
    source: str
    as_of: date | None
    note: str = ""


@dataclass(frozen=True, slots=True)
class MarketRegimeConfig:
    vix: BandTable
    circuit_breaker: BandTable
    treasury_10y: CategoricalTable
    sp500_per: CategoricalTable
    kospi_foreign_flow: CategoricalTable
    sources: Mapping[str, str]
    min_indicators_required: int = 3


@dataclass(frozen=True, slots=True)
class MarketRegimeResult:
    indicator_grades: tuple[IndicatorGrade, ...]
    grade_tally: Mapping[Grade, int]
    final_grade: Grade | None  # None이면 "판단 보류"(min_indicators_required 미달)
    tie_broken: bool
    action_guidance: str | None

    @property
    def buy_allowed(self) -> bool:
        """buy_rules.md B-1 조건2: 시장 상태 C 이상(A/B/C)이어야 매수 후보.
        판단 보류(final_grade=None)도 매수 불허로 취급한다(임의 낙관 금지)."""
        return self.final_grade is not None and self.final_grade.at_least_as_safe_as(Grade.C)


def _band_indicator(
    name: str, table: BandTable, value: Decimal | None, source: str, as_of: date | None
) -> IndicatorGrade:
    if value is None:
        return IndicatorGrade(
            indicator=name,
            observed="데이터 누락",
            grade=None,
            basis="",
            source=source,
            as_of=as_of,
            note="미입력 — 판정에서 제외(임의 추정 금지)",
        )
    grade, basis = _split_grade_label(table.score_for(value).label)
    return IndicatorGrade(
        indicator=name, observed=str(value), grade=grade, basis=basis, source=source, as_of=as_of
    )


def _categorical_indicator(
    name: str, table: CategoricalTable, value: str | None, source: str, as_of: date | None
) -> IndicatorGrade:
    if value is None:
        return IndicatorGrade(
            indicator=name,
            observed="데이터 누락",
            grade=None,
            basis="",
            source=source,
            as_of=as_of,
            note="미입력 — 판정에서 제외(임의 추정 금지)",
        )
    option = table.score_for(value)
    if option is None:
        return IndicatorGrade(
            indicator=name,
            observed=value,
            grade=None,
            basis="",
            source=source,
            as_of=as_of,
            note=f"정의되지 않은 범주값({value!r}) — 판정에서 제외",
        )
    grade, basis = _split_grade_label(option.label)
    return IndicatorGrade(
        indicator=name, observed=value, grade=grade, basis=basis, source=source, as_of=as_of
    )


def grade_market_regime(
    observations: Mapping[str, Decimal | str | None],
    config: MarketRegimeConfig,
    *,
    as_of: date | None = None,
) -> MarketRegimeResult:
    """5개 지표 관측값으로부터 시장 국면(4장)을 판정한다.

    observations는 ALL_INDICATORS의 일부/전부를 키로 가질 수 있다(누락된 키는
    미입력으로 취급). vix/circuit_breaker는 Decimal, 나머지 세 지표는 범주 문자열이다.
    """
    indicator_grades = (
        _band_indicator(
            VIX, config.vix, _as_decimal(observations.get(VIX)), config.sources[VIX], as_of
        ),
        _band_indicator(
            CIRCUIT_BREAKER,
            config.circuit_breaker,
            _as_decimal(observations.get(CIRCUIT_BREAKER)),
            config.sources[CIRCUIT_BREAKER],
            as_of,
        ),
        _categorical_indicator(
            TREASURY_10Y,
            config.treasury_10y,
            _as_str(observations.get(TREASURY_10Y)),
            config.sources[TREASURY_10Y],
            as_of,
        ),
        _categorical_indicator(
            SP500_PER,
            config.sp500_per,
            _as_str(observations.get(SP500_PER)),
            config.sources[SP500_PER],
            as_of,
        ),
        _categorical_indicator(
            KOSPI_FOREIGN_FLOW,
            config.kospi_foreign_flow,
            _as_str(observations.get(KOSPI_FOREIGN_FLOW)),
            config.sources[KOSPI_FOREIGN_FLOW],
            as_of,
        ),
    )

    graded = [ig.grade for ig in indicator_grades if ig.grade is not None]
    tally: dict[Grade, int] = dict(Counter(graded))

    if len(graded) < config.min_indicators_required:
        return MarketRegimeResult(
            indicator_grades=indicator_grades,
            grade_tally=tally,
            final_grade=None,
            tie_broken=False,
            action_guidance=None,
        )

    max_count = max(tally.values())
    top_grades = [g for g, count in tally.items() if count == max_count]
    tie_broken = len(top_grades) > 1
    final_grade = max(top_grades, key=lambda g: g.rank)  # 동률이면 더 위험한 쪽(4-2)

    return MarketRegimeResult(
        indicator_grades=indicator_grades,
        grade_tally=tally,
        final_grade=final_grade,
        tie_broken=tie_broken,
        action_guidance=_ACTION_GUIDANCE[final_grade],
    )


def _as_decimal(value: Decimal | str | None) -> Decimal | None:
    if value is None or isinstance(value, Decimal):
        return value
    raise TypeError(f"vix/circuit_breaker는 Decimal이어야 한다: {value!r}")


def _as_str(value: Decimal | str | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise TypeError(f"범주 지표는 문자열이어야 한다: {value!r}")
