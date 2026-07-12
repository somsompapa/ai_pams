"""PortfolioValuator/PortfolioSnapshot 테스트.

시나리오: 기준통화 KRW, 삼성전자 + 애플 + USD 예수금.
- 삼성전자 10주 @70,000 (원가 700,000)
- 애플 5주 @$200 (원가 $1,000)
- 예수금 $1,000 / 환율 1 USD = 1,300 KRW

총자산 = 700,000 + (5×220×1300=1,430,000) + 1,300,000 = 3,430,000 KRW (삼성 시세 70,000 유지 시)
"""

from datetime import date
from decimal import Decimal

import pytest

from pams.portfolio.domain import (
    MissingMarketDataError,
    PortfolioValuator,
    Position,
)
from pams.shared_kernel.domain import (
    Asset,
    AssetClass,
    Currency,
    Money,
    Percentage,
    Quantity,
)

AS_OF = date(2026, 7, 10)

SAMSUNG = Asset(
    asset_id="KRX:005930",
    name="삼성전자",
    asset_class=AssetClass.DOMESTIC_STOCK,
    currency=Currency.KRW,
    country="KR",
    sector="Information Technology",
)
APPLE = Asset(
    asset_id="NASDAQ:AAPL",
    name="Apple Inc.",
    asset_class=AssetClass.US_STOCK,
    currency=Currency.USD,
    country="US",
    sector="Information Technology",
)

POSITIONS = {
    SAMSUNG.asset_id: Position(
        asset_id=SAMSUNG.asset_id,
        quantity=Quantity.of(10),
        cost_basis=Money.of("700000", Currency.KRW),
        realized_pnl=Money.zero(Currency.KRW),
    ),
    APPLE.asset_id: Position(
        asset_id=APPLE.asset_id,
        quantity=Quantity.of(5),
        cost_basis=Money.of("1000", Currency.USD),
        realized_pnl=Money.zero(Currency.USD),
    ),
}
ASSETS = {SAMSUNG.asset_id: SAMSUNG, APPLE.asset_id: APPLE}
PRICES = {
    SAMSUNG.asset_id: Money.of("70000", Currency.KRW),
    APPLE.asset_id: Money.of("220", Currency.USD),
}
FX = {Currency.USD: Decimal("1300")}
CASH = {Currency.USD: Money.of("1000", Currency.USD)}


def build_snapshot() -> object:
    return PortfolioValuator().valuate(
        as_of=AS_OF,
        base_currency=Currency.KRW,
        positions=POSITIONS,
        assets=ASSETS,
        prices=PRICES,
        fx_rates=FX,
        cash_balances=CASH,
    )


class TestValuation:
    def test_total_value_in_base_currency(self) -> None:
        snapshot = build_snapshot()
        assert snapshot.total_value == Money.of("3430000", Currency.KRW)

    def test_unrealized_pnl(self) -> None:
        snapshot = build_snapshot()
        by_id = {v.asset.asset_id: v for v in snapshot.valuations}
        # 애플: 시가 $1,100 - 원가 $1,000 = +$100 → 130,000 KRW
        assert by_id[APPLE.asset_id].unrealized_pnl_local == Money.of("100", Currency.USD)
        assert by_id[APPLE.asset_id].unrealized_pnl_base == Money.of("130000", Currency.KRW)
        assert snapshot.total_unrealized_pnl == Money.of("130000", Currency.KRW)

    def test_weights_by_asset_class(self) -> None:
        snapshot = build_snapshot()
        weights = snapshot.weights_by_asset_class()
        assert weights[AssetClass.DOMESTIC_STOCK] == Percentage.from_ratio(
            Decimal("700000") / Decimal("3430000")
        )
        # 예수금은 DEPOSIT으로 분류된다
        assert weights[AssetClass.DEPOSIT] == Percentage.from_ratio(
            Decimal("1300000") / Decimal("3430000")
        )

    def test_weights_sum_to_one(self) -> None:
        snapshot = build_snapshot()
        for weights in (
            snapshot.weights_by_asset_class(),
            snapshot.weights_by_country(),
            snapshot.weights_by_currency(),
        ):
            total = sum((w.ratio for w in weights.values()), Decimal(0))
            assert total == Decimal(1)

    def test_weights_by_currency_includes_cash(self) -> None:
        snapshot = build_snapshot()
        weights = snapshot.weights_by_currency()
        # USD = 애플 1,430,000 + 예수금 1,300,000 = 2,730,000
        assert weights[Currency.USD] == Percentage.from_ratio(
            Decimal("2730000") / Decimal("3430000")
        )


class TestMetrics:
    def test_rule_engine_metrics(self) -> None:
        """Rule Engine(EvaluationContext)이 소비하는 표준 지표."""
        snapshot = build_snapshot()
        metrics = snapshot.metrics()
        # 주식성 = 삼성 700,000 + 애플 1,430,000 = 2,130,000
        assert metrics["equity_weight"] == Decimal("2130000") / Decimal("3430000")
        # 현금성 = USD 예수금 1,300,000
        assert metrics["cash_weight"] == Decimal("1300000") / Decimal("3430000")
        # 최대 단일 종목 = 애플 1,430,000
        assert metrics["max_position_weight"] == Decimal("1430000") / Decimal("3430000")
        for value in metrics.values():
            assert isinstance(value, Decimal)


class TestMissingData:
    def test_missing_price_raises(self) -> None:
        with pytest.raises(MissingMarketDataError, match="NASDAQ:AAPL"):
            PortfolioValuator().valuate(
                as_of=AS_OF,
                base_currency=Currency.KRW,
                positions=POSITIONS,
                assets=ASSETS,
                prices={SAMSUNG.asset_id: PRICES[SAMSUNG.asset_id]},
                fx_rates=FX,
                cash_balances=CASH,
            )

    def test_missing_fx_rate_raises(self) -> None:
        with pytest.raises(MissingMarketDataError, match="USD"):
            PortfolioValuator().valuate(
                as_of=AS_OF,
                base_currency=Currency.KRW,
                positions=POSITIONS,
                assets=ASSETS,
                prices=PRICES,
                fx_rates={},
                cash_balances=CASH,
            )

    def test_missing_asset_metadata_raises(self) -> None:
        with pytest.raises(MissingMarketDataError, match="NASDAQ:AAPL"):
            PortfolioValuator().valuate(
                as_of=AS_OF,
                base_currency=Currency.KRW,
                positions=POSITIONS,
                assets={SAMSUNG.asset_id: SAMSUNG},
                prices=PRICES,
                fx_rates=FX,
                cash_balances=CASH,
            )

    def test_fully_sold_position_needs_no_price(self) -> None:
        """수량 0인 포지션(전량 매도)은 평가에서 제외되므로 시세가 없어도 된다."""
        positions = {
            SAMSUNG.asset_id: Position(
                asset_id=SAMSUNG.asset_id,
                quantity=Quantity.of(0),
                cost_basis=Money.zero(Currency.KRW),
                realized_pnl=Money.of("50000", Currency.KRW),
            )
        }
        snapshot = PortfolioValuator().valuate(
            as_of=AS_OF,
            base_currency=Currency.KRW,
            positions=positions,
            assets=ASSETS,
            prices={},
            fx_rates={},
            cash_balances={Currency.KRW: Money.of("750000", Currency.KRW)},
        )
        assert snapshot.total_value == Money.of("750000", Currency.KRW)
        assert snapshot.total_realized_pnl == Money.of("50000", Currency.KRW)
