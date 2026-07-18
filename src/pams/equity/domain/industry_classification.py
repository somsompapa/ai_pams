"""업종분류 코드(DART 업종코드/SEC SIC) 기반 동일업종 피어 비교.

company_analysis_rules.md 3-2의 "업종평균 대비" 지표(매출총이익률·ROA·영업이익률)는
업종 벤치마크 데이터 소스가 없어 수동 입력만 받아왔다. 이 모듈은 임의로 피어
종목코드를 지어내는 대신, DART/SEC가 각자 발표하는 표준 업종분류 코드
(각각 induty_code/SIC)를 그대로 써서 "같은 코드를 가진, 실제로 조회 가능한
다른 종목"만 피어로 인정한다 — 두 분류 체계는 서로 다른 코드 공간이므로
시장이 다르면 코드가 같아도 비교하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pams.equity.domain.financial_statement import FinancialStatementProvider
from pams.equity.domain.growth_metrics import GrowthMetrics


@dataclass(frozen=True, slots=True)
class IndustryClassification:
    """code만이 매칭 키다. name은 있으면 표시용일 뿐 비교에 쓰지 않는다."""

    code: str
    name: str | None = None


@runtime_checkable
class IndustryClassificationProvider(Protocol):
    def industry_classification(self, asset_id: str) -> IndustryClassification | None:
        """조회 실패·계정 없음이면 조용히 None(다른 재무 항목까지 실패시키지 않는다)."""
        ...


class EquityMarketDataProvider(
    FinancialStatementProvider, IndustryClassificationProvider, Protocol
):
    """DART/SEC 어댑터가 실제로 구현하는 두 능력(재무제표+업종분류)을 함께 요구하는
    합성 포트. sync-industry처럼 둘 다 필요한 호출부 전용 — equity-score 같은 단일
    능력만 쓰는 호출부는 여전히 FinancialStatementProvider만 받는다."""


class IndustryClassificationRepository(Protocol):
    def load(self) -> dict[str, IndustryClassification]:
        """키는 'MARKET:SYMBOL'(예: KR:005930) — sync-industry가 미리 적재해둔 맵."""
        ...

    def save(self, entries: dict[str, IndustryClassification]) -> None: ...


_MIN_PEERS_FOR_RANK = 2  # 자신 포함 3개 미만이면 top30/mid/bottom 구간이 무의미해 생략


@dataclass(frozen=True, slots=True)
class IndustryPeerComparison:
    peer_count: int
    gross_margin_vs_industry_pp: Decimal | None
    roa_vs_industry_pp: Decimal | None
    op_margin_industry_rank: str | None  # "top30" | "mid" | "bottom"
    note: str | None


def compare_industry_peers(
    *,
    target: GrowthMetrics,
    is_financial: bool,
    peer_metrics: tuple[GrowthMetrics, ...],
) -> IndustryPeerComparison:
    """피어들의 최신연도 지표 평균과 target을 비교한다. 값이 없는 피어는 그 지표
    계산에서만 제외한다(전부 실패시키지 않음) — 임의추정 금지, 있는 데이터만 쓴다."""
    if not peer_metrics:
        return IndustryPeerComparison(
            peer_count=0,
            gross_margin_vs_industry_pp=None,
            roa_vs_industry_pp=None,
            op_margin_industry_rank=None,
            note="동일 업종코드 피어를 찾지 못함(sync-industry 미실행 또는 대상 미등록)",
        )

    gross_margin_pp = None
    if not is_financial and target.gross_margin_latest is not None:
        peer_values = [
            m.gross_margin_latest for m in peer_metrics if m.gross_margin_latest is not None
        ]
        if peer_values:
            gross_margin_pp = target.gross_margin_latest - (
                sum(peer_values, Decimal(0)) / len(peer_values)
            )

    roa_pp = None
    if is_financial and target.roa_latest is not None:
        peer_values = [m.roa_latest for m in peer_metrics if m.roa_latest is not None]
        if peer_values:
            roa_pp = target.roa_latest - (sum(peer_values, Decimal(0)) / len(peer_values))

    op_margin_rank = None
    if target.operating_margin_latest is not None:
        peer_op_margins = [
            m.operating_margin_latest for m in peer_metrics if m.operating_margin_latest is not None
        ]
        if len(peer_op_margins) >= _MIN_PEERS_FOR_RANK:
            group = sorted([*peer_op_margins, target.operating_margin_latest], reverse=True)
            position = group.index(target.operating_margin_latest)
            percentile_from_top = Decimal(position) / Decimal(len(group) - 1)
            if percentile_from_top <= Decimal("0.3"):
                op_margin_rank = "top30"
            elif percentile_from_top >= Decimal("0.7"):
                op_margin_rank = "bottom"
            else:
                op_margin_rank = "mid"

    return IndustryPeerComparison(
        peer_count=len(peer_metrics),
        gross_margin_vs_industry_pp=gross_margin_pp,
        roa_vs_industry_pp=roa_pp,
        op_margin_industry_rank=op_margin_rank,
        note=None,
    )
