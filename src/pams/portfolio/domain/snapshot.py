"""포트폴리오 평가: PositionValuation, CashBalance, PortfolioSnapshot, PortfolioValuator.

스냅샷은 특정 시점의 평가 결과이며, Rule Engine이 소비하는 표준 지표(metrics)를 제공한다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pams.portfolio.domain.position import Position
from pams.shared_kernel.domain import (
    Asset,
    AssetClass,
    Currency,
    DomainError,
    DomainValidationError,
    Money,
    Percentage,
)


class MissingMarketDataError(DomainError):
    """평가에 필요한 자산 정보/시세/환율이 없다.

    누락을 0으로 간주하면 총자산·비중·규칙 판정이 전부 왜곡되므로 즉시 실패시킨다.
    """


@dataclass(frozen=True, slots=True)
class PositionValuation:
    """단일 포지션의 평가 결과. local은 자산 통화, base는 기준통화."""

    asset: Asset
    position: Position
    price: Money
    market_value_local: Money
    market_value_base: Money
    unrealized_pnl_local: Money
    unrealized_pnl_base: Money
    realized_pnl_base: Money


@dataclass(frozen=True, slots=True)
class CashBalance:
    """통화별 예수금. 자산군 비중에서는 DEPOSIT으로 분류된다."""

    currency: Currency
    amount: Money
    value_base: Money


_KeyFn = Callable[["PositionValuation"], str]
_CashKeyFn = Callable[["CashBalance"], str]


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    as_of: date
    base_currency: Currency
    valuations: tuple[PositionValuation, ...]
    cash_balances: tuple[CashBalance, ...]

    @property
    def total_value(self) -> Money:
        total = Money.zero(self.base_currency)
        for valuation in self.valuations:
            total = total + valuation.market_value_base
        for cash in self.cash_balances:
            total = total + cash.value_base
        return total

    @property
    def total_unrealized_pnl(self) -> Money:
        total = Money.zero(self.base_currency)
        for valuation in self.valuations:
            total = total + valuation.unrealized_pnl_base
        return total

    @property
    def total_realized_pnl(self) -> Money:
        total = Money.zero(self.base_currency)
        for valuation in self.valuations:
            total = total + valuation.realized_pnl_base
        return total

    def _weights(self, groups: Mapping[str, Decimal]) -> dict[str, Percentage]:
        total = self.total_value.amount
        if total <= 0:
            return {}
        return {key: Percentage.from_ratio(value / total) for key, value in groups.items()}

    def _grouped_values(self, key_of: _KeyFn, cash_key: _CashKeyFn) -> dict[str, Decimal]:
        groups: dict[str, Decimal] = {}
        for valuation in self.valuations:
            key = key_of(valuation)
            groups[key] = groups.get(key, Decimal(0)) + valuation.market_value_base.amount
        for cash in self.cash_balances:
            key = cash_key(cash)
            groups[key] = groups.get(key, Decimal(0)) + cash.value_base.amount
        return groups

    def weights_by_asset_class(self) -> dict[AssetClass, Percentage]:
        raw = self._grouped_values(
            lambda v: v.asset.asset_class.value, lambda _c: AssetClass.DEPOSIT.value
        )
        return {AssetClass(key): weight for key, weight in self._weights(raw).items()}

    def values_by_asset_class(self) -> dict[AssetClass, Money]:
        """자산군별 평가금액(기준통화). 예수금은 DEPOSIT으로 분류된다."""
        raw = self._grouped_values(
            lambda v: v.asset.asset_class.value, lambda _c: AssetClass.DEPOSIT.value
        )
        return {AssetClass(key): Money(amount, self.base_currency) for key, amount in raw.items()}

    def weights_by_country(self) -> dict[str, Percentage]:
        """예수금은 통화 발행국이 아닌 '무국적(CASH)'으로 분류한다."""
        return self._weights(self._grouped_values(lambda v: v.asset.country, lambda _c: "CASH"))

    def weights_by_currency(self) -> dict[Currency, Percentage]:
        raw = self._grouped_values(lambda v: v.asset.currency.value, lambda c: c.currency.value)
        return {Currency(key): weight for key, weight in self._weights(raw).items()}

    def weights_by_sector(self) -> dict[str, Percentage]:
        return self._weights(
            self._grouped_values(lambda v: v.asset.sector or "UNCLASSIFIED", lambda _c: "CASH")
        )

    def metrics(self) -> dict[str, Decimal]:
        """Rule Engine(EvaluationContext)이 소비하는 표준 지표.

        이름은 config/rules/*.yaml의 metric과 일치해야 한다.
        """
        total = self.total_value.amount
        if total <= 0:
            raise DomainValidationError("총자산이 0 이하인 포트폴리오는 지표를 만들 수 없다")

        equity = sum(
            (
                v.market_value_base.amount
                for v in self.valuations
                if v.asset.asset_class.is_equity_like
            ),
            Decimal(0),
        )
        cash_like = sum(
            (
                v.market_value_base.amount
                for v in self.valuations
                if v.asset.asset_class.is_cash_like
            ),
            Decimal(0),
        ) + sum((c.value_base.amount for c in self.cash_balances), Decimal(0))
        max_position = max(
            (
                v.market_value_base.amount
                for v in self.valuations
                if not v.asset.asset_class.is_diversification_exempt
            ),
            default=Decimal(0),
        )
        return {
            "equity_weight": equity / total,
            "cash_weight": cash_like / total,
            "max_position_weight": max_position / total,
        }


class PortfolioValuator:
    """포지션·예수금을 시세/환율로 평가해 PortfolioSnapshot을 만드는 도메인 서비스."""

    def valuate(
        self,
        *,
        as_of: date,
        base_currency: Currency,
        positions: Mapping[str, Position],
        assets: Mapping[str, Asset],
        prices: Mapping[str, Money],
        fx_rates: Mapping[Currency, Decimal],  # 1 통화 = rate × base_currency
        cash_balances: Mapping[Currency, Money],
    ) -> PortfolioSnapshot:
        valuations = tuple(
            self._valuate_position(position, assets, prices, fx_rates, base_currency)
            for position in positions.values()
            if not position.quantity.is_zero or not position.realized_pnl.is_zero
        )
        cash = tuple(
            CashBalance(
                currency=currency,
                amount=amount,
                value_base=self._to_base(amount, fx_rates, base_currency),
            )
            for currency, amount in cash_balances.items()
        )
        return PortfolioSnapshot(
            as_of=as_of,
            base_currency=base_currency,
            valuations=valuations,
            cash_balances=cash,
        )

    def _valuate_position(
        self,
        position: Position,
        assets: Mapping[str, Asset],
        prices: Mapping[str, Money],
        fx_rates: Mapping[Currency, Decimal],
        base_currency: Currency,
    ) -> PositionValuation:
        asset = assets.get(position.asset_id)
        if asset is None:
            raise MissingMarketDataError(f"자산 정보가 없다: {position.asset_id}")

        if position.quantity.is_zero:
            # 전량 매도 포지션: 실현손익 이력만 유지하며 시세가 필요 없다
            zero_local = Money.zero(asset.currency)
            return PositionValuation(
                asset=asset,
                position=position,
                price=zero_local,
                market_value_local=zero_local,
                market_value_base=Money.zero(base_currency),
                unrealized_pnl_local=zero_local,
                unrealized_pnl_base=Money.zero(base_currency),
                realized_pnl_base=self._to_base(position.realized_pnl, fx_rates, base_currency),
            )

        price = prices.get(position.asset_id)
        if price is None:
            raise MissingMarketDataError(f"시세가 없다: {position.asset_id}")
        if price.currency is not asset.currency:
            raise MissingMarketDataError(
                f"{position.asset_id}: 시세 통화({price.currency})가 "
                f"자산 통화({asset.currency})와 다르다"
            )

        market_value_local = price * position.quantity.value
        unrealized_local = market_value_local - position.cost_basis
        return PositionValuation(
            asset=asset,
            position=position,
            price=price,
            market_value_local=market_value_local,
            market_value_base=self._to_base(market_value_local, fx_rates, base_currency),
            unrealized_pnl_local=unrealized_local,
            unrealized_pnl_base=self._to_base(unrealized_local, fx_rates, base_currency),
            realized_pnl_base=self._to_base(position.realized_pnl, fx_rates, base_currency),
        )

    @staticmethod
    def _to_base(
        money: Money, fx_rates: Mapping[Currency, Decimal], base_currency: Currency
    ) -> Money:
        if money.currency is base_currency:
            return money
        rate = fx_rates.get(money.currency)
        if rate is None:
            raise MissingMarketDataError(f"환율이 없다: {money.currency}→{base_currency}")
        return Money(money.amount * rate, base_currency)
