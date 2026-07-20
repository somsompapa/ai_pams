"""YAML 자산 카탈로그 통합 테스트."""

from pathlib import Path

import pytest

from pams.asset.infrastructure import (
    AssetConfigError,
    YamlAssetCatalog,
    append_asset,
    delete_asset,
    update_asset,
)
from pams.portfolio.domain import AssetCatalog
from pams.shared_kernel.domain import Asset, AssetClass, Currency

VALID = """
assets:
  - asset_id: KRX:005930
    name: 삼성전자
    asset_class: domestic_stock
    currency: KRW
    country: KR
    sector: Information Technology
  - asset_id: NASDAQ:AAPL
    name: Apple Inc.
    asset_class: us_stock
    currency: USD
    country: US
"""


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "assets.yaml"
    path.write_text(content, encoding="utf-8")
    return path


class TestYamlAssetCatalog:
    def test_satisfies_portfolio_port(self, tmp_path: Path) -> None:
        assert isinstance(YamlAssetCatalog(write(tmp_path, VALID)), AssetCatalog)

    def test_get(self, tmp_path: Path) -> None:
        catalog = YamlAssetCatalog(write(tmp_path, VALID))
        samsung = catalog.get("KRX:005930")
        assert samsung is not None
        assert samsung.asset_class is AssetClass.DOMESTIC_STOCK
        assert samsung.currency is Currency.KRW
        apple = catalog.get("NASDAQ:AAPL")
        assert apple is not None and apple.sector is None
        assert catalog.get("UNKNOWN") is None

    def test_unknown_asset_class_rejected(self, tmp_path: Path) -> None:
        bad = VALID.replace("us_stock", "meme_stock")
        with pytest.raises(AssetConfigError, match="meme_stock"):
            YamlAssetCatalog(write(tmp_path, bad)).get("NASDAQ:AAPL")

    def test_duplicate_asset_id_rejected(self, tmp_path: Path) -> None:
        bad = VALID.replace("NASDAQ:AAPL", "KRX:005930")
        with pytest.raises(AssetConfigError, match="005930"):
            YamlAssetCatalog(write(tmp_path, bad)).get("KRX:005930")

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(AssetConfigError):
            YamlAssetCatalog(tmp_path / "nope.yaml").get("KRX:005930")


class TestUpdateAsset:
    def test_replaces_matching_entry(self, tmp_path: Path) -> None:
        path = write(tmp_path, VALID)
        update_asset(
            path,
            "KRX:005930",
            Asset(
                asset_id="KRX:005930",
                name="삼성전자우",
                asset_class=AssetClass.DOMESTIC_STOCK,
                currency=Currency.KRW,
                country="KR",
            ),
        )
        catalog = YamlAssetCatalog(path)
        samsung = catalog.get("KRX:005930")
        assert samsung is not None and samsung.name == "삼성전자우"
        assert catalog.get("NASDAQ:AAPL") is not None  # 다른 항목은 그대로

    def test_unknown_asset_id_rejected(self, tmp_path: Path) -> None:
        path = write(tmp_path, VALID)
        with pytest.raises(AssetConfigError, match="찾을 수 없다"):
            update_asset(
                path,
                "NOPE",
                Asset(
                    asset_id="NOPE",
                    name="X",
                    asset_class=AssetClass.DOMESTIC_STOCK,
                    currency=Currency.KRW,
                    country="KR",
                ),
            )


class TestDeleteAsset:
    def test_removes_matching_entry(self, tmp_path: Path) -> None:
        path = write(tmp_path, VALID)
        delete_asset(path, "KRX:005930")
        catalog = YamlAssetCatalog(path)
        assert catalog.get("KRX:005930") is None
        assert catalog.get("NASDAQ:AAPL") is not None

    def test_unknown_asset_id_rejected(self, tmp_path: Path) -> None:
        path = write(tmp_path, VALID)
        with pytest.raises(AssetConfigError, match="찾을 수 없다"):
            delete_asset(path, "NOPE")


class TestExceptionalQualityReason:
    def test_round_trips_through_yaml(self, tmp_path: Path) -> None:
        path = write(tmp_path, VALID)
        append_asset(
            path,
            Asset(
                asset_id="NASDAQ:NVDA",
                name="엔비디아",
                asset_class=AssetClass.US_STOCK,
                currency=Currency.USD,
                country="US",
                exceptional_quality_reason="기업 점수 90+ 3분기 연속 유지",
            ),
        )
        catalog = YamlAssetCatalog(path)
        nvda = catalog.get("NASDAQ:NVDA")
        assert nvda is not None
        assert nvda.exceptional_quality_reason == "기업 점수 90+ 3분기 연속 유지"
        assert nvda.is_exceptional_quality is True

    def test_absent_when_not_set(self, tmp_path: Path) -> None:
        catalog = YamlAssetCatalog(write(tmp_path, VALID))
        samsung = catalog.get("KRX:005930")
        assert samsung is not None
        assert samsung.exceptional_quality_reason is None


class TestAppendAsset:
    def test_appends_new_entry(self, tmp_path: Path) -> None:
        path = write(tmp_path, VALID)
        append_asset(
            path,
            Asset(
                asset_id="NASDAQ:NVDA",
                name="엔비디아",
                asset_class=AssetClass.US_STOCK,
                currency=Currency.USD,
                country="US",
            ),
        )
        catalog = YamlAssetCatalog(path)
        assert catalog.get("NASDAQ:NVDA") is not None

    def test_rejects_duplicate(self, tmp_path: Path) -> None:
        path = write(tmp_path, VALID)
        with pytest.raises(AssetConfigError, match="이미 등록"):
            append_asset(
                path,
                Asset(
                    asset_id="KRX:005930",
                    name="삼성전자",
                    asset_class=AssetClass.DOMESTIC_STOCK,
                    currency=Currency.KRW,
                    country="KR",
                ),
            )
