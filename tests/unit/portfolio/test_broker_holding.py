"""BrokerHolding 값객체 검증 테스트."""

from decimal import Decimal

import pytest

from pams.portfolio.domain import BrokerHolding, HoldingsProvider
from pams.shared_kernel.domain import Currency, DomainValidationError


class TestBrokerHolding:
    def test_valid_holding(self) -> None:
        holding = BrokerHolding(
            symbol="AAPL",
            quantity=Decimal(10),
            avg_price=Decimal("155.3"),
            current_price=Decimal("178.5"),
            currency=Currency.USD,
        )
        assert holding.symbol == "AAPL"

    def test_negative_quantity_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            BrokerHolding(
                symbol="AAPL",
                quantity=Decimal(-1),
                avg_price=Decimal(1),
                current_price=Decimal(1),
                currency=Currency.USD,
            )

    def test_negative_price_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            BrokerHolding(
                symbol="AAPL",
                quantity=Decimal(1),
                avg_price=Decimal(-1),
                current_price=Decimal(1),
                currency=Currency.USD,
            )

    def test_satisfies_holdings_provider_port(self) -> None:
        class Fake:
            def holdings(self) -> list[BrokerHolding]:
                return []

        assert isinstance(Fake(), HoldingsProvider)
