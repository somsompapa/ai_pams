"""YAML 자산 카탈로그: 자산 마스터 데이터를 config에서 관리한다.

portfolio의 AssetCatalog 포트는 Protocol(구조적 타이핑)이므로
이 구현은 portfolio를 import하지 않고도 포트를 만족한다.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from pams.shared_kernel.domain import Asset, AssetClass, Currency, DomainError


class AssetConfigError(Exception):
    """자산 카탈로그 파일을 읽는 데 실패했다."""


class YamlAssetCatalog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._assets: dict[str, Asset] | None = None

    def get(self, asset_id: str) -> Asset | None:
        return self._load().get(asset_id)

    def all(self) -> list[Asset]:
        return list(self._load().values())

    def _load(self) -> dict[str, Asset]:
        if self._assets is not None:
            return self._assets
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise AssetConfigError(f"자산 파일을 읽을 수 없다: {self._path}") from error
        except yaml.YAMLError as error:
            raise AssetConfigError(f"YAML 문법 오류: {self._path}: {error}") from error
        if not isinstance(document, dict) or not isinstance(document.get("assets"), list):
            raise AssetConfigError(f"{self._path}: 최상위 'assets' 목록이 필요하다")

        assets: dict[str, Asset] = {}
        for index, entry in enumerate(document["assets"]):
            where = f"{self._path}.assets[{index}]"
            if not isinstance(entry, dict):
                raise AssetConfigError(f"{where}: 매핑이어야 한다")
            try:
                asset = Asset(
                    asset_id=str(entry.get("asset_id", "")),
                    name=str(entry.get("name", "")),
                    asset_class=AssetClass(str(entry.get("asset_class"))),
                    currency=Currency(str(entry.get("currency"))),
                    country=str(entry.get("country", "")),
                    sector=(str(entry["sector"]) if entry.get("sector") is not None else None),
                )
            except ValueError:
                raise AssetConfigError(
                    f"{where}: 알 수 없는 자산군/통화 "
                    f"{entry.get('asset_class')!r}/{entry.get('currency')!r}"
                ) from None
            except DomainError as error:
                raise AssetConfigError(f"{where}: {error}") from error
            if asset.asset_id in assets:
                raise AssetConfigError(f"{where}: 중복된 asset_id '{asset.asset_id}'")
            assets[asset.asset_id] = asset
        self._assets = assets
        return assets
