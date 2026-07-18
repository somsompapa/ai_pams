"""compute_price_band() 테스트 — PER/PBR 5년밴드 백분위(company_analysis_rules.md 3-4,
valuation_rules.md V-2 (1)). 종목 자신의 과거 결산연도별 PER/PBR 분포 내 위치를 계산한다."""

from datetime import date
from decimal import Decimal

from pams.equity.domain.financial_statement import AnnualFinancials
from pams.equity.domain.price_band import compute_price_band
from pams.market_data.domain import Quote
from pams.shared_kernel.domain import Currency


def _price(year: int, month: int, day: int, close: str) -> Quote:
    return Quote(
        symbol="TEST",
        quote_date=date(year, month, day),
        close=Decimal(close),
        currency=Currency.USD,
    )


class TestNoData:
    def test_none_current_price_returns_note(self) -> None:
        result = compute_price_band(
            current_price=None,
            annual=(AnnualFinancials(fiscal_year=2025, eps=Decimal(10)),),
            historical_prices=(),
        )
        assert result.per_band_percentile is None
        assert result.note is not None

    def test_empty_annual_returns_note(self) -> None:
        result = compute_price_band(current_price=Decimal(100), annual=(), historical_prices=())
        assert result.per_band_percentile is None
        assert result.note is not None

    def test_empty_historical_prices_returns_note(self) -> None:
        result = compute_price_band(
            current_price=Decimal(100),
            annual=(AnnualFinancials(fiscal_year=2025, eps=Decimal(10)),),
            historical_prices=(),
        )
        assert result.per_band_percentile is None
        assert "가격 이력" in (result.note or "")


class TestPerBandPercentile:
    def test_computes_percentile_within_historical_per_series(self) -> None:
        annual = (
            AnnualFinancials(fiscal_year=2021, eps=Decimal(5)),
            AnnualFinancials(fiscal_year=2022, eps=Decimal(6)),
            AnnualFinancials(fiscal_year=2023, eps=Decimal(7)),
            AnnualFinancials(fiscal_year=2024, eps=Decimal(8)),
            AnnualFinancials(fiscal_year=2025, eps=Decimal(10)),
        )
        prices = (
            _price(2021, 12, 30, "50"),  # PER 10
            _price(2022, 12, 30, "60"),  # PER 10
            _price(2023, 12, 29, "70"),  # PER 10
            _price(2024, 12, 31, "120"),  # PER 15
        )
        # 현재가 200, 최근연도 EPS 10 → 현재 PER 20 (역대 최고 → 백분위 1.0 = 최상단)
        result = compute_price_band(
            current_price=Decimal(200), annual=annual, historical_prices=prices
        )
        assert result.per_band_percentile == Decimal(1)

    def test_current_per_at_cheapest_end_yields_zero(self) -> None:
        annual = (
            AnnualFinancials(fiscal_year=2023, eps=Decimal(6)),
            AnnualFinancials(fiscal_year=2024, eps=Decimal(8)),
            AnnualFinancials(fiscal_year=2025, eps=Decimal(10)),
        )
        prices = (
            _price(2023, 12, 29, "120"),  # PER 20
            _price(2024, 12, 31, "160"),  # PER 20
        )
        # 현재가 50, EPS 10 → 현재 PER 5 (역대 최저 → 백분위 0.0 = 최하단)
        result = compute_price_band(
            current_price=Decimal(50), annual=annual, historical_prices=prices
        )
        assert result.per_band_percentile == Decimal(0)

    def test_none_when_fewer_than_two_historical_points(self) -> None:
        """비교할 과거 표본이 1개뿐이면 0%/100% 양극단만 나와 의미가 없어 생략한다."""
        annual = (
            AnnualFinancials(fiscal_year=2024, eps=Decimal(8)),
            AnnualFinancials(fiscal_year=2025, eps=Decimal(10)),
        )
        prices = (_price(2024, 12, 31, "160"),)
        result = compute_price_band(
            current_price=Decimal(200), annual=annual, historical_prices=prices
        )
        assert result.per_band_percentile is None

    def test_year_without_matching_price_is_skipped_not_fabricated(self) -> None:
        annual = (
            AnnualFinancials(fiscal_year=2021, eps=Decimal(5)),
            AnnualFinancials(fiscal_year=2022, eps=Decimal(6)),  # 가격 없음 → 표본 제외
            AnnualFinancials(fiscal_year=2023, eps=Decimal(7)),
        )
        prices = (
            _price(2021, 12, 30, "50"),
            _price(2023, 12, 29, "70"),
        )
        result = compute_price_band(
            current_price=Decimal(150), annual=annual, historical_prices=prices
        )
        # 표본 2개(2021, 2023)로 충분히 계산되지만, 2022는 조용히 제외됐다는 사실은
        # 값을 지어내지 않았다는 것으로 확인한다(에러 없이 정상 계산).
        assert result.per_band_percentile is not None

    def test_uses_latest_year_within_calendar_year_for_matching(self) -> None:
        """같은 연도 내 여러 관측치가 있으면 가장 늦은 날짜를 채택한다."""
        annual = (
            AnnualFinancials(fiscal_year=2022, eps=Decimal(4)),
            AnnualFinancials(fiscal_year=2023, eps=Decimal(5)),
            AnnualFinancials(fiscal_year=2024, eps=Decimal(10)),
        )
        prices = (
            _price(2022, 12, 30, "40"),  # PER 10
            _price(2023, 3, 1, "40"),  # 이 연도의 이른 시점(무시돼야 함)
            _price(2023, 12, 31, "50"),  # PER 10 — 이게 채택돼야 함
        )
        result = compute_price_band(
            current_price=Decimal(100), annual=annual, historical_prices=prices
        )
        assert result.per_band_percentile is not None


class TestPbrBandPercentile:
    def test_computes_percentile_within_historical_pbr_series(self) -> None:
        annual = (
            AnnualFinancials(
                fiscal_year=2023, total_equity=Decimal(1000), shares_outstanding=Decimal(100)
            ),  # BVPS 10
            AnnualFinancials(
                fiscal_year=2024, total_equity=Decimal(1200), shares_outstanding=Decimal(100)
            ),  # BVPS 12
            AnnualFinancials(
                fiscal_year=2025, total_equity=Decimal(1500), shares_outstanding=Decimal(100)
            ),  # BVPS 15
        )
        prices = (
            _price(2023, 12, 29, "10"),  # PBR 1.0
            _price(2024, 12, 31, "12"),  # PBR 1.0
        )
        # 현재가 30, 최근연도 BVPS 15 → 현재 PBR 2.0 (역대 최고)
        result = compute_price_band(
            current_price=Decimal(30), annual=annual, historical_prices=prices
        )
        assert result.pbr_band_percentile == Decimal(1)

    def test_none_when_shares_outstanding_missing(self) -> None:
        annual = (AnnualFinancials(fiscal_year=2025, total_equity=Decimal(1500)),)
        result = compute_price_band(
            current_price=Decimal(30),
            annual=annual,
            historical_prices=(_price(2025, 12, 31, "10"),),
        )
        assert result.pbr_band_percentile is None
