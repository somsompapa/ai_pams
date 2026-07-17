"""유스케이스: DCF 가정으로 적정가·민감도·괴리율·매수/매도 트리거 구간을 산출한다."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pams.equity.domain.dcf import (
    DcfAssumptions,
    DcfResult,
    TriggerZones,
    ValuationGap,
    calculate_dcf,
    dcf_sensitivity,
    trigger_zones,
    valuation_gap,
)


@dataclass(frozen=True, slots=True)
class DcfReport:
    result: DcfResult
    sensitivity: dict[str, Decimal | None]
    zones: TriggerZones
    gap: ValuationGap | None  # current_price 미제공 시 None


@dataclass(frozen=True, slots=True)
class CalculateDcf:
    def execute(
        self, assumptions: DcfAssumptions, *, current_price: Decimal | None = None
    ) -> DcfReport:
        result = calculate_dcf(assumptions)
        sensitivity = dcf_sensitivity(assumptions)
        zones = trigger_zones(sensitivity)
        gap = None
        if current_price is not None and result.fair_value_per_share is not None:
            gap = valuation_gap(current_price, result.fair_value_per_share)
        return DcfReport(result=result, sensitivity=sensitivity, zones=zones, gap=gap)
