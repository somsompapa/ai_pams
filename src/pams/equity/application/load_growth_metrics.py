"""유스케이스: 재무제표 공급자(SEC/DART 등)로 종목의 성장성/수익성 지표를 계산한다.

다른 컨텍스트나 interfaces 계층은 FinancialStatementProvider 구현체를 직접 알
필요 없이 이 유스케이스만 호출한다 — 공급자 교체는 wiring에서만 바뀐다(DIP).
"""

from __future__ import annotations

from dataclasses import dataclass

from pams.equity.domain.financial_statement import (
    AnnualFinancialsResult,
    FinancialStatementProvider,
)
from pams.equity.domain.growth_metrics import GrowthMetrics, compute_growth_metrics


@dataclass(frozen=True, slots=True)
class GrowthMetricsReport:
    financials: AnnualFinancialsResult
    metrics: GrowthMetrics


@dataclass(frozen=True, slots=True)
class LoadGrowthMetrics:
    provider: FinancialStatementProvider

    def execute(self, asset_id: str, *, years: int = 4) -> GrowthMetricsReport:
        financials = self.provider.annual_financials(asset_id, years=years)
        metrics = compute_growth_metrics(financials.annual)
        return GrowthMetricsReport(financials=financials, metrics=metrics)
