"""유스케이스: 업종분류 맵(sync-industry가 미리 적재)에서 같은 시장·같은 업종코드를
가진 다른 종목을 찾아 그 재무제표로 업종평균 대비 지표를 계산한다.

피어 종목코드를 이 코드가 직접 지어내지 않는다 — 전부 IndustryClassificationRepository
(sync-industry CLI가 DART induty_code/SEC SIC로 미리 채워둔 data/industry_map.json)에서만
찾는다. 맵이 비어있거나 대상이 없으면 조용히 "데이터 없음"으로 물러난다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pams.equity.application.load_growth_metrics import LoadGrowthMetrics
from pams.equity.domain.financial_statement import (
    FinancialStatementProvider,
    FinancialStatementProviderError,
)
from pams.equity.domain.growth_metrics import GrowthMetrics
from pams.equity.domain.industry_classification import (
    IndustryClassificationRepository,
    IndustryPeerComparison,
    compare_industry_peers,
)

# 요청 1건당 추가 재무제표 조회 상한 — 지연시간과 DART/SEC 요율제한을 보호한다.
_MAX_PEERS = 8


@dataclass(frozen=True, slots=True)
class CompareIndustryPeers:
    classification_repository: IndustryClassificationRepository
    provider_for_market: Callable[[str], FinancialStatementProvider]

    def execute(
        self,
        *,
        asset_id: str,
        market: str,
        is_financial: bool,
        target_metrics: GrowthMetrics,
    ) -> IndustryPeerComparison:
        classifications = self.classification_repository.load()
        target_key = f"{market}:{asset_id}"
        target_classification = classifications.get(target_key)
        if target_classification is None:
            return IndustryPeerComparison(
                peer_count=0,
                gross_margin_vs_industry_pp=None,
                roa_vs_industry_pp=None,
                op_margin_industry_rank=None,
                note="업종분류 미확보(sync-industry 미실행 또는 대상 미등록) — 자동 비교 불가",
            )
        # 분류 체계가 시장마다 다르므로(DART induty_code vs SEC SIC) 같은 시장끼리만 비교한다.
        peer_keys = [
            key
            for key, classification in classifications.items()
            if key != target_key
            and key.split(":", 1)[0] == market
            and classification.code == target_classification.code
        ][:_MAX_PEERS]
        if not peer_keys:
            return IndustryPeerComparison(
                peer_count=0,
                gross_margin_vs_industry_pp=None,
                roa_vs_industry_pp=None,
                op_margin_industry_rank=None,
                note=f"업종코드 {target_classification.code}의 다른 피어를 찾지 못함",
            )

        provider = self.provider_for_market(market)
        peer_metrics: list[GrowthMetrics] = []
        for key in peer_keys:
            peer_symbol = key.split(":", 1)[1]
            try:
                # 최신연도 비율 지표만 필요하므로 1개년만 조회한다(피어당 API 호출 최소화).
                report = LoadGrowthMetrics(provider=provider).execute(peer_symbol, years=1)
            except FinancialStatementProviderError:
                continue
            peer_metrics.append(report.metrics)

        return compare_industry_peers(
            target=target_metrics, is_financial=is_financial, peer_metrics=tuple(peer_metrics)
        )
