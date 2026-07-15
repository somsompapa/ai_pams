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


def _read_entries(path: Path) -> list[dict[str, str]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    return list(document["assets"]) if isinstance(document, dict) and document.get("assets") else []


def _write_entries(path: Path, entries: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# 자산 마스터 데이터 (대시보드에서 관리됨)\n"
    body = yaml.safe_dump(
        {"assets": entries}, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    path.write_text(header + body, encoding="utf-8")


def _to_entry(asset: Asset) -> dict[str, str]:
    entry: dict[str, str] = {
        "asset_id": asset.asset_id,
        "name": asset.name,
        "asset_class": asset.asset_class.value,
        "currency": asset.currency.value,
        "country": asset.country,
    }
    if asset.sector is not None:
        entry["sector"] = asset.sector
    return entry


def append_asset(path: Path, asset: Asset) -> None:
    """자산 마스터에 새 종목 한 건을 추가한다(같은 asset_id가 있으면 거부).

    도메인 Asset으로 이미 검증된 값만 받는다. 기존 목록은 유지하고 추가만 한다.
    """
    entries = _read_entries(path)
    if any(isinstance(e, dict) and e.get("asset_id") == asset.asset_id for e in entries):
        raise AssetConfigError(f"이미 등록된 asset_id '{asset.asset_id}'")
    entries.append(_to_entry(asset))
    _write_entries(path, entries)


def update_asset(path: Path, asset_id: str, asset: Asset) -> None:
    """asset_id에 해당하는 자산을 새 내용으로 교체한다. 없으면 실패."""
    entries = _read_entries(path)
    if not any(isinstance(e, dict) and e.get("asset_id") == asset_id for e in entries):
        raise AssetConfigError(f"asset_id '{asset_id}'를 찾을 수 없다")
    if asset.asset_id != asset_id and any(
        isinstance(e, dict) and e.get("asset_id") == asset.asset_id for e in entries
    ):
        raise AssetConfigError(f"이미 등록된 asset_id '{asset.asset_id}'")
    updated = [_to_entry(asset) if e.get("asset_id") == asset_id else e for e in entries]
    _write_entries(path, updated)


def delete_asset(path: Path, asset_id: str) -> None:
    """asset_id에 해당하는 자산을 제거한다. 없으면 실패."""
    entries = _read_entries(path)
    remaining = [e for e in entries if not (isinstance(e, dict) and e.get("asset_id") == asset_id)]
    if len(remaining) == len(entries):
        raise AssetConfigError(f"asset_id '{asset_id}'를 찾을 수 없다")
    _write_entries(path, remaining)


class YamlAssetCatalog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._assets: dict[str, Asset] | None = None
        self._loaded_mtime: float | None = None

    def get(self, asset_id: str) -> Asset | None:
        return self._load().get(asset_id)

    def all(self) -> list[Asset]:
        return list(self._load().values())

    def _load(self) -> dict[str, Asset]:
        # 파일이 바뀌면(웹에서 종목 추가 등) 자동으로 다시 읽는다.
        try:
            mtime: float | None = self._path.stat().st_mtime
        except OSError:
            mtime = None
        if self._assets is not None and mtime == self._loaded_mtime:
            return self._assets
        self._loaded_mtime = mtime
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
