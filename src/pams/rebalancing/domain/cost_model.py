"""거래비용 모델: 자산군별 수수료율/매도세율.

요율은 config/costs/*.yaml에서 로드한다 (하드코딩 금지).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pams.shared_kernel.domain import AssetClass, DomainValidationError, Percentage


@dataclass(frozen=True, slots=True)
class TradingCostRates:
    fee_rate: Percentage  # 매매수수료율 (매수/매도 공통)
    sell_tax_rate: Percentage  # 매도 시에만 부과되는 세율 (예: 증권거래세)

    def __post_init__(self) -> None:
        if self.fee_rate < Percentage.zero():
            raise DomainValidationError(f"수수료율은 음수가 될 수 없다: {self.fee_rate.ratio}")
        if self.sell_tax_rate < Percentage.zero():
            raise DomainValidationError(f"매도세율은 음수가 될 수 없다: {self.sell_tax_rate.ratio}")


@dataclass(frozen=True, slots=True)
class CostModel:
    rates: Mapping[AssetClass, TradingCostRates]
    default: TradingCostRates  # 정의되지 않은 자산군의 폴백

    def rates_for(self, asset_class: AssetClass) -> TradingCostRates:
        return self.rates.get(asset_class, self.default)
