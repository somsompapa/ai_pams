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

    def test_values_by_asset_class(self) -> None:
        snapshot = build_snapshot()
        values = snapshot.values_by_asset_class()
        assert values[AssetClass.DOMESTIC_STOCK] == Money.of("700000", Currency.KRW)
        assert values[AssetClass.US_STOCK] == Money.of("1430000", Currency.KRW)
        # 예수금은 DEPOSIT으로 분류된다
        assert values[AssetClass.DEPOSIT] == Money.of("1300000", Currency.KRW)
        # 금액 합계 = 총자산
        total = sum((m.amount for m in values.values()), Decimal(0))
        assert total == snapshot.total_value.amount

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

    def test_max_position_excludes_cash_like_and_pension(self) -> None:
        """단일종목 집중도(max_position_weight)는 개별 종목의 쏠림 위험을 재는 지표다.

        CMA·연금 계좌는 계좌 하나를 자산 1건으로 등록해도 그 안에 여러 상품이
        섞여 있거나(연금) 애초에 시장 위험이 없는 현금이라(CMA), '집중투자'와
        무관하다. 금액이 훨씬 커도 이 지표에서는 제외해야 한다.
        """
        cma = Asset(
            asset_id="CASH:CMA",
            name="CMA",
            asset_class=AssetClass.CASH,
            currency=Currency.KRW,
            country="KR",
        )
        pension = Asset(
            asset_id="PENSION:IRP",
            name="IRP",
            asset_class=AssetClass.PENSION,
            currency=Currency.KRW,
            country="KR",
        )
        positions = dict(POSITIONS)
        positions[cma.asset_id] = Position(
            asset_id=cma.asset_id,
            quantity=Quantity.of(1),
            cost_basis=Money.of("100000000", Currency.KRW),
            realized_pnl=Money.zero(Currency.KRW),
        )
        positions[pension.asset_id] = Position(
            asset_id=pension.asset_id,
            quantity=Quantity.of(1),
            cost_basis=Money.of("50000000", Currency.KRW),
            realized_pnl=Money.zero(Currency.KRW),
        )
        assets = dict(ASSETS)
        assets[cma.asset_id] = cma
        assets[pension.asset_id] = pension
        prices = dict(PRICES)
        prices[cma.asset_id] = Money.of("100000000", Currency.KRW)
        prices[pension.asset_id] = Money.of("50000000", Currency.KRW)

        snapshot = PortfolioValuator().valuate(
            as_of=AS_OF,
            base_currency=Currency.KRW,
            positions=positions,
            assets=assets,
            prices=prices,
            fx_rates=FX,
            cash_balances=CASH,
        )
        metrics = snapshot.metrics()
        # CMA(1억)·연금(5천만)이 애플(1,430,000)보다 훨씬 크지만 제외되어야 한다
        assert metrics["max_position_weight"] == Decimal("1430000") / snapshot.total_value.amount

    def test_exceptional_quality_position_uses_separate_metric(self) -> None:
        """portfolio_rules.md P-3: 초우량 예외(사유 명시) 종목은 일반 20% 한도가 아니라
        별도 30% 한도를 적용받아야 하므로, 자체 지표로 분리돼야 한다 — 일반
        max_position_weight에 섞여 20% 위반으로 오판되면 안 된다."""
        nvda = Asset(
            asset_id="NASDAQ:NVDA",
            name="엔비디아",
            asset_class=AssetClass.US_STOCK,
            currency=Currency.USD,
            country="US",
            exceptional_quality_reason="기업 점수 90+ 3분기 연속 유지, 시장 지배력 근거",
        )
        positions = dict(POSITIONS)
        positions[nvda.asset_id] = Position(
            asset_id=nvda.asset_id,
            quantity=Quantity.of(10),
            cost_basis=Money.of("1000", Currency.USD),
            realized_pnl=Money.zero(Currency.USD),
        )
        assets = dict(ASSETS)
        assets[nvda.asset_id] = nvda
        prices = dict(PRICES)
        prices[nvda.asset_id] = Money.of("300", Currency.USD)  # 10주×300×1300 = 3,900,000 KRW

        snapshot = PortfolioValuator().valuate(
            as_of=AS_OF,
            base_currency=Currency.KRW,
            positions=positions,
            assets=assets,
            prices=prices,
            fx_rates=FX,
            cash_balances=CASH,
        )
        metrics = snapshot.metrics()
        total = snapshot.total_value.amount
        # 엔비디아(3,900,000)가 애플(1,430,000)보다 크지만 초우량이라 일반 지표에서 빠진다
        assert metrics["max_position_weight"] == Decimal("1430000") / total
        assert metrics["max_exceptional_position_weight"] == Decimal("3900000") / total

    def test_no_exceptional_positions_yields_zero_metric(self) -> None:
        snapshot = build_snapshot()
        assert snapshot.metrics()["max_exceptional_position_weight"] == Decimal(0)


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
