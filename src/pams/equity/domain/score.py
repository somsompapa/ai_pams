"""기업 점수 결과 값객체. company_analysis_rules.md 3장(100점 모델) 3-7 근거표 형식을 그대로 반영.

"근거 없는 점수는 무효"(3-7) — ScoreItem은 항상 값·구간·점수·근거를 함께 들고 다닌다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum, unique


@dataclass(frozen=True, slots=True)
class ScoreItem:
    metric: str
    value: str  # 사람이 읽는 표현(숫자·범주·"데이터 누락" 등을 문자열로 통일)
    bucket: str
    score: Decimal
    max_score: Decimal
    note: str = ""


@dataclass(frozen=True, slots=True)
class CategoryScore:
    """score는 명시적 필드다 — sum(items)로 자동 계산하지 않는다. 리스크 카테고리처럼
    "기본점수 - 차감(카테고리별 상한 적용)"이 sum(item.score)와 다른 경우가 있기 때문이다
    (각 item.score는 "이 항목이 몇 점 깎았는지" 표시용, 카테고리 합계와 별개)."""

    category: str
    max_score: Decimal
    score: Decimal
    items: tuple[ScoreItem, ...]


@unique
class Verdict(StrEnum):
    STRONG_CANDIDATE = "strong_candidate"  # 90점 이상
    BUY_REVIEW = "buy_review"  # 80~89
    WATCHLIST = "watchlist"  # 70~79
    EXCLUDE = "exclude"  # 70점 미만


def verdict_for(total_score: Decimal) -> Verdict:
    if total_score >= 90:
        return Verdict.STRONG_CANDIDATE
    if total_score >= 80:
        return Verdict.BUY_REVIEW
    if total_score >= 70:
        return Verdict.WATCHLIST
    return Verdict.EXCLUDE


@dataclass(frozen=True, slots=True)
class CompanyScoreReport:
    symbol: str
    as_of: date
    data_source: str
    categories: tuple[CategoryScore, ...]
    data_quality_flags: tuple[str, ...] = ()

    @property
    def total_score(self) -> Decimal:
        return sum((category.score for category in self.categories), Decimal(0))

    @property
    def verdict(self) -> Verdict:
        return verdict_for(self.total_score)

    @property
    def buy_score_condition_met(self) -> bool:
        """buy_rules.md B-1 조건1: 기업 점수 ≥ 80점."""
        return self.total_score >= 80

    def category(self, name: str) -> CategoryScore | None:
        return next((c for c in self.categories if c.category == name), None)
