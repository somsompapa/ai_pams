"""거래비용 모델: 자산군별 수수료율/매도세율/양도소득세.

요율은 config/costs/*.yaml에서 로드한다 (하드코딩 금지).

세금은 두 종류를 구분한다.
- 매도세(sell_tax_rate): 매도금액 기준 (예: 국내주식 증권거래세).
- 양도소득세(capital_gains): 양도차익 기준, 연 공제 후 과세 (예: 해외주식).
자산군에 따라 둘 중 하나 또는 둘 다 적용될 수 있다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pams.shared_kernel.domain import AssetClass, DomainValidationError, Money, Percentage


@dataclass(frozen=True, slots=True)
class CapitalGainsTax:
    """양도소득세: (양도차익 − 연 공제)의 양수분에 세율을 적용한다.

    한국 해외주식 예: 세율 22%(지방세 포함), 연 기본공제 250만원.
    연 공제는 '해당 자산군의 이 매도 건'에 대해 적용하는 근사다 - 정확한 연간
    합산 공제는 실현 이력을 별도로 추적해야 하며, 리밸런싱 제안의 '예상 세금'은
    의사결정 참고용 추정치다.
    """

    rate: Percentage
    annual_exemption: Money

    def __post_init__(self) -> None:
        if self.rate < Percentage.zero():
            raise DomainValidationError(f"양도세율은 음수가 될 수 없다: {self.rate.ratio}")
        if self.annual_exemption.is_negative:
            raise DomainValidationError(
                f"연 공제는 음수가 될 수 없다: {self.annual_exemption.amount}"
            )

    def on_gain(self, gain: Money) -> Money:
        """양도차익에 대한 세액. 차익이 공제 이하면 0."""
        taxable = gain - self.annual_exemption
        if not taxable.is_positive:
            return Money.zero(gain.currency)
        return self.rate.of(taxable)


@dataclass(frozen=True, slots=True)
class TradingCostRates:
    fee_rate: Percentage  # 매매수수료율 (매수/매도 공통)
    sell_tax_rate: Percentage  # 매도금액 기준 세율 (예: 증권거래세)
    capital_gains: CapitalGainsTax | None = None  # 양도차익 기준 세금 (예: 해외주식)

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
