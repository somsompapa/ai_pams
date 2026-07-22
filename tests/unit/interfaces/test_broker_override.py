"""_broker_override (증권사 실계좌 잔고로 주식 종목 표시값 보강) 단위 테스트.

거래이력 기반 계산과는 독립적인 순수 함수라, DashboardService 전체를 조립하지
않고 이 함수만 직접 검증한다.
"""

from decimal import Decimal

from pams.interfaces.api.service import _broker_override
from pams.portfolio.domain import BrokerHolding
from pams.shared_kernel.domain import Currency, Money


class TestBrokerOverride:
    def test_same_currency_uses_fx_rate_of_one(self) -> None:
        holding = BrokerHolding(
            symbol="005930",
            quantity=Decimal(100),
            avg_price=Decimal(65000),
            current_price=Decimal(72000),
            currency=Currency.KRW,
        )
        result = _broker_override(
            holding,
            local_price=Money(Decimal(72000), Currency.KRW),
            local_quantity=Decimal(100),
            market_value_base=Money(Decimal(7200000), Currency.KRW),
        )
        assert result["quantity"] == "100.0000"
        assert result["avg_price"] == "65,000 KRW"
        assert result["current_price"] == "72,000 KRW"
        assert result["market_value"] == "7,200,000 KRW"
        assert result["unrealized_pnl"] == "700,000 KRW"
        assert result["unrealized_percent"] == "10.77%"
        assert result["unrealized_positive"] is True

    def test_foreign_currency_derives_fx_rate_from_existing_valuation(self) -> None:
        """local_price × local_quantity 대비 market_value_base 비율로 환율을 역산한다.

        PAMS 원장은 8주만 알고 있었지만(거래 누락) 증권사는 실제 10주를 보고하는
        상황을 가정 - local_quantity(8)로 기존 환율(1400)을 역산한 뒤, holding의
        실제 수량(10)에 그 환율을 적용해야 한다.
        """
        holding = BrokerHolding(
            symbol="AAPL",
            quantity=Decimal(10),
            avg_price=Decimal("155.3"),
            current_price=Decimal("178.5"),
            currency=Currency.USD,
        )
        result = _broker_override(
            holding,
            local_price=Money(Decimal("178.5"), Currency.USD),
            local_quantity=Decimal(8),
            market_value_base=Money(Decimal("1999200"), Currency.KRW),  # 8*178.5*1400
        )
        assert result["market_value"] == "2,499,000 KRW"  # 178.5*10*1400
        assert result["unrealized_pnl"] == "324,800 KRW"  # (1785-1553)*1400

    def test_zero_avg_price_avoids_division_by_zero(self) -> None:
        holding = BrokerHolding(
            symbol="X",
            quantity=Decimal(10),
            avg_price=Decimal(0),
            current_price=Decimal(100),
            currency=Currency.USD,
        )
        result = _broker_override(
            holding,
            local_price=Money(Decimal(100), Currency.USD),
            local_quantity=Decimal(10),
            market_value_base=Money(Decimal(100000), Currency.KRW),
        )
        assert result["unrealized_percent"] == "0.00%"

    def test_zero_local_quantity_falls_back_to_fx_rate_one(self) -> None:
        holding = BrokerHolding(
            symbol="X",
            quantity=Decimal(10),
            avg_price=Decimal(50),
            current_price=Decimal(60),
            currency=Currency.USD,
        )
        result = _broker_override(
            holding,
            local_price=Money(Decimal(100), Currency.USD),
            local_quantity=Decimal(0),  # 원장이 이 종목을 전혀 모르던 극단 케이스
            market_value_base=Money(Decimal(0), Currency.KRW),
        )
        assert result["market_value"] == "600 KRW"  # fx_rate=1 -> 60*10
