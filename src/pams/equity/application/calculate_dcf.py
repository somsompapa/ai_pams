"""유스케이스: DCF 가정으로 적정가·민감도·괴리율·매수/매도 트리거 구간을 산출한다."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pams.equity.domain.dcf import (
    DcfAssumptions,
    DcfResult,
    TriggerZones,
    ValuationError,
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
    # 발행주식수 미확보 등으로 민감도 그리드 전체가 무효면 트리거 구간을 못 만든다.
    # 그렇다고 이미 유효하게 계산된 enterprise_value/equity_value(result)까지 버릴
    # 이유는 없다 — zones만 None으로 남기고 사유를 함께 전달한다.
    zones: TriggerZones | None
    zones_unavailable_reason: str | None
    gap: ValuationGap | None  # current_price 미제공 시 None


@dataclass(frozen=True, slots=True)
class CalculateDcf:
    def execute(
        self, assumptions: DcfAssumptions, *, current_price: Decimal | None = None
    ) -> DcfReport:
        result = calculate_dcf(assumptions)
        sensitivity = dcf_sensitivity(assumptions)
        zones: TriggerZones | None
        zones_unavailable_reason: str | None
        try:
            zones = trigger_zones(sensitivity)
            zones_unavailable_reason = None
        except ValuationError as error:
            zones = None
            zones_unavailable_reason = str(error)
        gap = None
        if current_price is not None and result.fair_value_per_share is not None:
            gap = valuation_gap(current_price, result.fair_value_per_share)
        return DcfReport(
            result=result,
            sensitivity=sensitivity,
            zones=zones,
            zones_unavailable_reason=zones_unavailable_reason,
            gap=gap,
        )
