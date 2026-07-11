"""유스케이스: 거래 기록과 시장 데이터로 포트폴리오 스냅샷을 만든다.

흐름: 거래 조회 → 포지션/예수금 파생(원장) → 시세/환율 수집 → 평가(Valuator).
필요한 시장 데이터가 없으면 MissingMarketDataError가 그대로 전파된다(엄격 실행).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pams.portfolio.domain import (
    AssetCatalog,
    CashLedger,
    FxLookup,
    PortfolioSnapshot,
    PortfolioValuator,
    PositionLedger,
    PriceLookup,
    TransactionRepository,
)
from pams.shared_kernel.domain import Asset, Currency, Money


@dataclass(frozen=True, slots=True)
class BuildPortfolioSnapshot:
    transactions: TransactionRepository
    assets: AssetCatalog
    prices: PriceLookup
    fx: FxLookup
    position_ledger: PositionLedger = field(default_factory=PositionLedger)
    cash_ledger: CashLedger = field(default_factory=CashLedger)
    valuator: PortfolioValuator = field(default_factory=PortfolioValuator)

    def execute(self, *, as_of: date, base_currency: Currency) -> PortfolioSnapshot:
        history = self.transactions.transactions_until(as_of)
        positions = self.position_ledger.build(history)
        cash_balances = self.cash_ledger.build(history)

        asset_map: dict[str, Asset] = {}
        price_map: dict[str, Money] = {}
        fx_map: dict[Currency, Decimal] = {}

        for asset_id, position in positions.items():
            asset = self.assets.get(asset_id)
            if asset is not None:
                asset_map[asset_id] = asset
                self._collect_fx(asset.currency, base_currency, as_of, fx_map)
            if not position.quantity.is_zero:
                price = self.prices.price_of(asset_id, as_of)
                if price is not None:
                    price_map[asset_id] = price
        for currency in cash_balances:
            self._collect_fx(currency, base_currency, as_of, fx_map)

        # 수집 단계는 조회만 하고, 누락 판정은 Valuator(도메인)가 일관되게 수행한다
        return self.valuator.valuate(
            as_of=as_of,
            base_currency=base_currency,
            positions=positions,
            assets=asset_map,
            prices=price_map,
            fx_rates=fx_map,
            cash_balances=cash_balances,
        )

    def _collect_fx(
        self,
        currency: Currency,
        base_currency: Currency,
        as_of: date,
        fx_map: dict[Currency, Decimal],
    ) -> None:
        if currency is base_currency or currency in fx_map:
            return
        rate = self.fx.rate_to(currency, base_currency, as_of)
        if rate is not None:
            fx_map[currency] = rate
