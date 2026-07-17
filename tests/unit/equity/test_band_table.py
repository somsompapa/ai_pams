"""BandTable/CategoricalTable 도메인 테스트."""

from decimal import Decimal

import pytest

from pams.equity.domain.band_table import (
    Band,
    BandDirection,
    BandTable,
    CategoricalOption,
    CategoricalTable,
)
from pams.shared_kernel.domain import DomainValidationError

_REVENUE_CAGR_BANDS = BandTable(
    metric="revenue_cagr_3y",
    max_score=Decimal(10),
    direction=BandDirection.HIGHER_IS_BETTER,
    bands=(
        Band(bound=Decimal("0.15"), score=Decimal(10), label="≥15%"),
        Band(bound=Decimal("0.10"), score=Decimal(7), label="10~15%"),
        Band(bound=Decimal("0.05"), score=Decimal(4), label="5~10%"),
        Band(bound=Decimal("-Infinity"), score=Decimal(0), label="<5%"),
    ),
)

_DEBT_RATIO_BANDS = BandTable(
    metric="debt_ratio",
    max_score=Decimal(3),
    direction=BandDirection.LOWER_IS_BETTER,
    bands=(
        Band(bound=Decimal("1.0"), score=Decimal(3), label="≤100%"),
        Band(bound=Decimal("2.0"), score=Decimal(1), label="100~200%"),
        Band(bound=Decimal("Infinity"), score=Decimal(0), label=">200%"),
    ),
)


class TestBandTable:
    def test_higher_is_better_picks_top_band(self) -> None:
        band = _REVENUE_CAGR_BANDS.score_for(Decimal("0.16"))
        assert band.score == Decimal(10)
        assert band.label == "≥15%"

    def test_higher_is_better_picks_middle_band(self) -> None:
        band = _REVENUE_CAGR_BANDS.score_for(Decimal("0.123"))
        assert band.score == Decimal(7)

    def test_higher_is_better_catch_all_for_negative(self) -> None:
        band = _REVENUE_CAGR_BANDS.score_for(Decimal("-0.5"))
        assert band.score == Decimal(0)

    def test_lower_is_better_picks_top_band(self) -> None:
        band = _DEBT_RATIO_BANDS.score_for(Decimal("0.4"))
        assert band.score == Decimal(3)

    def test_lower_is_better_catch_all_for_huge_value(self) -> None:
        band = _DEBT_RATIO_BANDS.score_for(Decimal("50"))
        assert band.score == Decimal(0)

    def test_missing_catch_all_bound_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            BandTable(
                metric="broken",
                max_score=Decimal(10),
                direction=BandDirection.HIGHER_IS_BETTER,
                bands=(Band(bound=Decimal("0.15"), score=Decimal(10), label="x"),),
            )

    def test_wrong_sort_order_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            BandTable(
                metric="broken",
                max_score=Decimal(10),
                direction=BandDirection.HIGHER_IS_BETTER,
                bands=(
                    Band(bound=Decimal("0.05"), score=Decimal(4), label="x"),
                    Band(bound=Decimal("0.15"), score=Decimal(10), label="y"),
                    Band(bound=Decimal("-Infinity"), score=Decimal(0), label="z"),
                ),
            )

    def test_empty_bands_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            BandTable(
                metric="broken",
                max_score=Decimal(10),
                direction=BandDirection.HIGHER_IS_BETTER,
                bands=(),
            )


class TestCategoricalTable:
    def test_known_value_returns_option(self) -> None:
        table = CategoricalTable(
            metric="market_share_trend",
            max_score=Decimal(8),
            options={
                "up": CategoricalOption(score=Decimal(8), label="상승"),
                "flat": CategoricalOption(score=Decimal(4), label="횡보"),
                "down": CategoricalOption(score=Decimal(0), label="하락"),
            },
        )
        assert table.score_for("up").score == Decimal(8)

    def test_unknown_value_returns_none_not_zero_score(self) -> None:
        """정의되지 않은 값은 조용히 0점으로 만들지 않고 None을 반환 —
        호출자가 '데이터 누락'으로 명시 처리하게 한다(임의 추정 금지)."""
        table = CategoricalTable(
            metric="market_share_trend",
            max_score=Decimal(8),
            options={"up": CategoricalOption(score=Decimal(8), label="상승")},
        )
        assert table.score_for("모름") is None
