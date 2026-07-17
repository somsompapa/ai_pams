"""연간 재무제표 도메인: AnnualFinancials 값객체, FinancialStatementProvider 포트.

외부 재무제표 공급자(SEC EDGAR XBRL, DART Open API)는 이 포트로 추상화되며
infrastructure에서 구현한다(DIP) — 언제든 다른 소스로 교체 가능하다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pams.shared_kernel.domain import DomainError, DomainValidationError


class FinancialStatementProviderError(DomainError):
    """외부 재무제표 공급자 호출/응답 처리에 실패했다."""


def _validate_decimal(name: str, value: Decimal | None) -> None:
    if value is not None and not isinstance(value, Decimal):
        raise DomainValidationError(f"{name}는 Decimal이어야 한다 (float 금지): {value!r}")


@dataclass(frozen=True, slots=True)
class AnnualFinancials:
    """특정 회계연도의 연간 재무제표. 값이 없는 필드는 None(임의 추정 금지, 0으로 채우지 않음)."""

    fiscal_year: int
    revenue: Decimal | None = None
    operating_income: Decimal | None = None
    net_income: Decimal | None = None
    eps: Decimal | None = None
    gross_profit: Decimal | None = None
    total_assets: Decimal | None = None
    total_equity: Decimal | None = None
    total_equity_derived: bool = False  # True면 자산-부채 역산으로 채운 값(원본 계정 매칭 실패)
    # v1.4 정의 고정(company_analysis_rules.md 3-3): 총부채(유동+비유동 전체,
    # 총자산-자기자본). 이자부채만이 아니다 — debt_ratio 채점에 사용.
    total_debt: Decimal | None = None
    interest_bearing_debt: Decimal | None = None  # 감점 시 보조지표용, total_debt와 다름
    cash: Decimal | None = None
    operating_cash_flow: Decimal | None = None
    capex: Decimal | None = None
    shares_outstanding: Decimal | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("revenue", self.revenue),
            ("operating_income", self.operating_income),
            ("net_income", self.net_income),
            ("eps", self.eps),
            ("gross_profit", self.gross_profit),
            ("total_assets", self.total_assets),
            ("total_equity", self.total_equity),
            ("total_debt", self.total_debt),
            ("interest_bearing_debt", self.interest_bearing_debt),
            ("cash", self.cash),
            ("operating_cash_flow", self.operating_cash_flow),
            ("capex", self.capex),
            ("shares_outstanding", self.shares_outstanding),
        ):
            _validate_decimal(name, value)

    @property
    def fcf(self) -> Decimal | None:
        """잉여현금흐름 = 영업활동현금흐름 - Capex. 둘 중 하나라도 없으면 None(추정 금지)."""
        if self.operating_cash_flow is None or self.capex is None:
            return None
        return self.operating_cash_flow - self.capex


@dataclass(frozen=True, slots=True)
class AnnualFinancialsResult:
    """조회 결과 + 연도별 부분 실패 사유. 일부 연도가 실패해도 나머지는 반환한다
    (전체 실패로 만들지 않음) — 단, "결측이 있다"는 사실은 숨기지 않는다."""

    asset_id: str
    data_source: str
    annual: tuple[AnnualFinancials, ...]  # fiscal_year 오름차순(과거→최신)
    fetch_errors: tuple[str, ...] = ()


@runtime_checkable
class FinancialStatementProvider(Protocol):
    def annual_financials(self, asset_id: str, *, years: int = 4) -> AnnualFinancialsResult:
        """최근 years개년 연간 재무제표. 공급자 자체를 호출할 수 없으면(키 누락 등) 예외,
        일부 연도만 실패하면 fetch_errors에 사유를 담아 나머지 연도로 반환한다."""
        ...
