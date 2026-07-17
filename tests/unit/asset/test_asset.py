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

    def test_equity_like_classification(self) -> None:
        """IPS의 '최대 주식비중'(equity_weight) 규칙 대상: 국내주식+미국주식+ETF."""
        assert AssetClass.DOMESTIC_STOCK.is_equity_like
        assert AssetClass.US_STOCK.is_equity_like
        assert AssetClass.ETF.is_equity_like
        assert not AssetClass.BOND.is_equity_like
        assert not AssetClass.GOLD.is_equity_like
        assert not AssetClass.CASH.is_equity_like

    def test_savings_asset_class_supported(self) -> None:
        """청약·적립식 저축은 중도해지 페널티로 사실상 묶인 저축 자산이다."""
        assert AssetClass.SAVINGS.value == "savings"

    def test_diversification_exempt_classification(self) -> None:
        """단일종목 집중도 지표 제외 대상: 현금성 + 연금 + 저축(청약).

        모두 '한 종목 쏠림' 위험과 무관하다(현금은 시장위험 없음,
        연금·청약은 계좌 단위 등록).
        """
        assert AssetClass.CASH.is_diversification_exempt
        assert AssetClass.DEPOSIT.is_diversification_exempt
        assert AssetClass.FOREIGN_CURRENCY.is_diversification_exempt
        assert AssetClass.PENSION.is_diversification_exempt
        assert AssetClass.SAVINGS.is_diversification_exempt
        assert not AssetClass.US_STOCK.is_diversification_exempt
        assert not AssetClass.GOLD.is_diversification_exempt


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

    def test_no_exceptional_reason_by_default(self) -> None:
        asset = self.make_asset()
        assert asset.exceptional_quality_reason is None
        assert asset.is_exceptional_quality is False

    def test_exceptional_quality_reason_sets_flag(self) -> None:
        asset = self.make_asset(
            exceptional_quality_reason="기업 점수 90+ 3분기 연속 유지, 시장 지배력 근거"
        )
        assert asset.is_exceptional_quality is True

    def test_empty_exceptional_reason_rejected(self) -> None:
        """사유 문장 없는 빈 값으로 예외를 켤 수 없다(임의 적용 금지)."""
        with pytest.raises(DomainValidationError):
            self.make_asset(exceptional_quality_reason="   ")
