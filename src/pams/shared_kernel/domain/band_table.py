"""구간표(band table) — 수치 지표를 구간별 점수로 매핑하는 공용 도메인 프리미티브.

CLAUDE.md 절대원칙 #2("투자 규칙은 코드에 하드코딩하지 않고 config/의 YAML로 관리한다")를
따르기 위한 것 — company_analysis_rules.md/valuation_rules.md의 모든 구간표(매출 성장률,
ROE, DCF 괴리율 등)를 이 하나의 자료구조로 표현하고, 실제 경계값·점수는 YAML에서 읽는다.
domain 계층은 이 표를 "적용"만 하고, 표 자체를 만들지 않는다(만드는 건 infrastructure).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum, unique

from pams.shared_kernel.domain.errors import DomainValidationError


@unique
class BandDirection(StrEnum):
    """HIGHER_IS_BETTER: 값이 클수록 좋음(성장률, ROE 등) — bound는 하한(이상).
    LOWER_IS_BETTER: 값이 작을수록 좋음(부채비율, DCF 괴리율 등) — bound는 상한(이하)."""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


@dataclass(frozen=True, slots=True)
class Band:
    bound: Decimal
    score: Decimal
    label: str


@dataclass(frozen=True, slots=True)
class BandTable:
    """구간이 정렬된 구간표. HIGHER_IS_BETTER는 bound 내림차순, LOWER_IS_BETTER는 오름차순.

    마지막 구간은 반드시 -Infinity(HIGHER_IS_BETTER) 또는 +Infinity(LOWER_IS_BETTER)를
    bound로 가져야 한다 — 그래야 모든 값이 어떤 구간이든 반드시 매칭되어, "이 값은 어느
    구간에도 안 걸림"이라는 조용한 판단 보류 상태(임의 추정 금지 원칙 위반의 씨앗)가
    생기지 않는다.
    """

    metric: str
    max_score: Decimal
    direction: BandDirection
    bands: tuple[Band, ...]

    def __post_init__(self) -> None:
        if not self.bands:
            raise DomainValidationError(f"{self.metric}: 구간표가 비어 있다")
        bounds = [band.bound for band in self.bands]
        expected = sorted(bounds, reverse=(self.direction is BandDirection.HIGHER_IS_BETTER))
        if bounds != expected:
            raise DomainValidationError(
                f"{self.metric}: 구간 정렬이 direction({self.direction})과 맞지 않는다"
            )
        last_bound = bounds[-1]
        catch_all = (
            last_bound == Decimal("-Infinity")
            if self.direction is BandDirection.HIGHER_IS_BETTER
            else last_bound == Decimal("Infinity")
        )
        if not catch_all:
            raise DomainValidationError(
                f"{self.metric}: 마지막 구간의 bound는 무한대여야 모든 값을 포괄한다 "
                f"(현재: {last_bound})"
            )

    def score_for(self, value: Decimal) -> Band:
        if self.direction is BandDirection.HIGHER_IS_BETTER:
            for band in self.bands:
                if value >= band.bound:
                    return band
        else:
            for band in self.bands:
                if value <= band.bound:
                    return band
        raise AssertionError(  # __post_init__의 catch-all 검증으로 도달 불가
            f"{self.metric}: {value}에 해당하는 구간을 찾지 못함 — 구간표 구성 오류"
        )


@dataclass(frozen=True, slots=True)
class CategoricalOption:
    score: Decimal
    label: str


@dataclass(frozen=True, slots=True)
class CategoricalTable:
    """수치가 아니라 범주(예: market_share_trend: up/flat/down)로 매핑되는 지표."""

    metric: str
    max_score: Decimal
    options: dict[str, CategoricalOption]

    def score_for(self, value: str) -> CategoricalOption | None:
        """정의되지 않은 값(데이터 누락 포함)은 None — 호출자가 0점+사유로 처리한다."""
        return self.options.get(value)
