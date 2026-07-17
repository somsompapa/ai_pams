"""AnnualFinancials 값객체 테스트."""

from decimal import Decimal

import pytest

from pams.equity.domain.financial_statement import AnnualFinancials
from pams.shared_kernel.domain import DomainValidationError


class TestAnnualFinancials:
    def test_fcf_computed_from_operating_cash_flow_minus_capex(self) -> None:
        row = AnnualFinancials(
            fiscal_year=2025,
            operating_cash_flow=Decimal("9730881000000"),
            capex=Decimal("258659000000"),
        )
        assert row.fcf == Decimal("9472222000000")

    def test_fcf_none_when_either_input_missing(self) -> None:
        assert AnnualFinancials(fiscal_year=2025, operating_cash_flow=Decimal(100)).fcf is None
        assert AnnualFinancials(fiscal_year=2025, capex=Decimal(100)).fcf is None

    def test_float_field_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            AnnualFinancials(fiscal_year=2025, revenue=100.0)  # type: ignore[arg-type]

    def test_minimal_construction_all_none(self) -> None:
        row = AnnualFinancials(fiscal_year=2025)
        assert row.revenue is None
        assert row.fcf is None
        assert row.total_equity_derived is False
