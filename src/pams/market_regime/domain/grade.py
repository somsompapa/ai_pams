"""시장 국면 등급(A~E). market_analysis_rules.md 4장.

A(강세)~E(위기) 5단계. rank가 클수록 위험하다(E에 가깝다) — 동률 처리(4-2 보수적 채택)와
"C 이상"(buy_rules.md B-1 조건2) 판정에 이 순서를 그대로 쓴다.
"""

from __future__ import annotations

from enum import StrEnum, unique

_ORDER: tuple[str, ...] = ("A", "B", "C", "D", "E")


@unique
class Grade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"

    @property
    def rank(self) -> int:
        """0(A, 최선) ~ 4(E, 최악)."""
        return _ORDER.index(self.value)

    def at_least_as_safe_as(self, other: Grade) -> bool:
        """self가 other보다 같거나 더 안전한(위험이 낮거나 같은) 등급인가."""
        return self.rank <= other.rank
