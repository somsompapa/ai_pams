"""Asset 엔티티 및 AssetClass 분류 체계 테스트."""

import pytest

from pams.asset.domain import Asset, AssetClass
from pams.shared_kernel.domain import Currency, DomainValidationError


class TestAssetClass:
    def test_all_required_asset_classes_supported(self) -> None:
        """요구사항: 국내주식/미국주식/ETF/채권/현금/예수금/외화/금/연금/가상자산."""
        required = {
            "DOMESTIC_STOCK",
            "US_STOCK",
            "ETF",
            "BOND",
            "CASH",
            "DEPOSIT",
            "FOREIGN_CURRENCY",
            "GOLD",
            "PENSION",
            "CRYPTO",
        }
        assert required <= {member.name for member in AssetClass}

    def test_cash_like_classification(self) -> None:
        """IPS의 '현금 최소 비중' 규칙은 현금성 자산 전체를 대상으로 한다."""
        assert AssetClass.CASH.is_cash_like
        assert AssetClass.DEPOSIT.is_cash_like
        assert AssetClass.FOREIGN_CURRENCY.is_cash_like
        assert not AssetClass.US_STOCK.is_cash_like
        assert not AssetClass.GOLD.is_cash_like


class TestAsset:
    def make_asset(self, **overrides: object) -> Asset:
        defaults: dict[str, object] = {
            "asset_id": "KRX:005930",
            "name": "삼성전자",
            "asset_class": AssetClass.DOMESTIC_STOCK,
            "currency": Currency.KRW,
            "country": "KR",
            "sector": "Information Technology",
        }
        defaults.update(overrides)
        return Asset(**defaults)  # type: ignore[arg-type]

    def test_valid_asset(self) -> None:
        asset = self.make_asset()
        assert asset.asset_id == "KRX:005930"
        assert asset.country == "KR"

    def test_us_stock(self) -> None:
        asset = self.make_asset(
            asset_id="NASDAQ:AAPL",
            name="Apple Inc.",
            asset_class=AssetClass.US_STOCK,
            currency=Currency.USD,
            country="US",
        )
        assert asset.currency is Currency.USD

    def test_sector_is_optional(self) -> None:
        """현금/금 등은 섹터가 없다."""
        asset = self.make_asset(
            asset_id="CASH:KRW",
            name="원화 현금",
            asset_class=AssetClass.CASH,
            sector=None,
        )
        assert asset.sector is None

    def test_empty_asset_id_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            self.make_asset(asset_id="  ")

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(DomainValidationError):
            self.make_asset(name="")

    def test_invalid_country_code_rejected(self) -> None:
        """국가는 ISO 3166-1 alpha-2 형식(예: KR, US)만 허용한다."""
        with pytest.raises(DomainValidationError):
            self.make_asset(country="KOR")
        with pytest.raises(DomainValidationError):
            self.make_asset(country="kr")

    def test_immutable(self) -> None:
        asset = self.make_asset()
        with pytest.raises(AttributeError):
            asset.name = "변경"  # type: ignore[misc]
