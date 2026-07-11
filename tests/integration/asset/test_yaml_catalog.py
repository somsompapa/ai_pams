"""YAML 자산 카탈로그 통합 테스트."""

from pathlib import Path

import pytest

from pams.asset.infrastructure import AssetConfigError, YamlAssetCatalog
from pams.portfolio.domain import AssetCatalog
from pams.shared_kernel.domain import AssetClass, Currency

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
