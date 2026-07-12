"""PolicyStatement(투자헌장) 테스트."""

import pytest

from pams.ips.domain import AllocationTarget, PolicyStatement
from pams.shared_kernel.domain import (
    AssetClass,
    Currency,
    DomainValidationError,
    Percentage,
)


def target(asset_class: AssetClass, percent: str, band: str = "5") -> AllocationTarget:
    return AllocationTarget(
        asset_class=asset_class,
        target=Percentage.from_percent(percent),
        band=Percentage.from_percent(band),
    )


def policy(**overrides: object) -> PolicyStatement:
    defaults: dict[str, object] = {
        "name": "기본 투자헌장",
        "base_currency": Currency.KRW,
        "targets": (
            target(AssetClass.DOMESTIC_STOCK, "20"),
            target(AssetClass.US_STOCK, "30"),
            target(AssetClass.BOND, "25"),
            target(AssetClass.GOLD, "5"),
            target(AssetClass.CASH, "20"),
        ),
        "rules": (),
    }
    defaults.update(overrides)
    return PolicyStatement(**defaults)  # type: ignore[arg-type]


class TestAllocationTarget:
    def test_weight_band(self) -> None:
        t = target(AssetClass.US_STOCK, "30", band="5")
        assert t.min_weight == Percentage.from_percent(25)
        assert t.max_weight == Percentage.from_percent(35)

    def test_target_out_of_range_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            target(AssetClass.US_STOCK, "101")
        with pytest.raises(DomainValidationError):
            target(AssetClass.US_STOCK, "-1")

    def test_negative_band_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            target(AssetClass.US_STOCK, "30", band="-1")

    def test_band_is_clamped_to_valid_weights(self) -> None:
        """목표 3% ± 밴드 5%여도 하한은 0% 아래로 내려가지 않는다."""
        t = target(AssetClass.GOLD, "3", band="5")
        assert t.min_weight == Percentage.zero()


class TestPolicyStatement:
    def test_valid_policy(self) -> None:
        p = policy()
        assert p.base_currency is Currency.KRW
        found = p.target_for(AssetClass.US_STOCK)
        assert found is not None and found.target == Percentage.from_percent(30)
        assert p.target_for(AssetClass.CRYPTO) is None

    def test_targets_must_sum_to_100_percent(self) -> None:
        with pytest.raises(DomainValidationError):
            policy(
                targets=(
                    target(AssetClass.US_STOCK, "50"),
                    target(AssetClass.CASH, "40"),
                )
            )

    def test_duplicate_asset_class_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            policy(
                targets=(
                    target(AssetClass.US_STOCK, "50"),
                    target(AssetClass.US_STOCK, "30"),
                    target(AssetClass.CASH, "20"),
                )
            )

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            policy(name=" ")

    def test_empty_targets_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            policy(targets=())
