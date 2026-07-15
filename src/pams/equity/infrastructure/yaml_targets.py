"""config/stock_targets/*.yaml → StockTargetPlan 로더."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pams.equity.domain import StockTarget, StockTargetPlan
from pams.shared_kernel.domain import DomainError, Percentage

_TARGET_HEADER = (
    "# 종목별 목표비중 · 매수/매도 트리거 (Tier 2 — 대시보드에서 관리됨)\n"
    "# 주식 슬리브(국내주식+미국주식) 안에서 종목별 목표비중과 밴드를 정한다.\n"
)


class StockTargetConfigError(Exception):
    """종목 목표 설정 파일을 StockTargetPlan으로 변환하는 데 실패했다."""


def save_stock_target(path: Path, target: StockTarget) -> None:
    """종목 목표 한 건을 upsert 한다(같은 asset_id는 교체). 파일이 없으면 만든다.

    도메인 StockTarget으로 이미 검증된 값만 받으므로 여기서는 직렬화만 한다.
    """
    entries: list[dict[str, str]] = []
    if path.exists():
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = document.get("targets", []) if isinstance(document, dict) else []
        entries = [e for e in raw if isinstance(e, dict) and e.get("asset_id") != target.asset_id]

    entries.append(
        {
            "asset_id": target.asset_id,
            "target_percent": str(target.target.as_percent),
            "buy_band": str(target.buy_band.as_percent),
            "sell_band": str(target.sell_band.as_percent),
        }
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        {"targets": entries}, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    path.write_text(_TARGET_HEADER + body, encoding="utf-8")


def delete_stock_target(path: Path, asset_id: str) -> None:
    """asset_id의 종목 목표를 제거한다. 없으면 실패."""
    entries: list[dict[str, str]] = []
    if path.exists():
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = document.get("targets", []) if isinstance(document, dict) else []
        entries = [e for e in raw if isinstance(e, dict)]

    remaining = [e for e in entries if e.get("asset_id") != asset_id]
    if len(remaining) == len(entries):
        raise StockTargetConfigError(f"asset_id '{asset_id}'의 종목 목표를 찾을 수 없다")

    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        {"targets": remaining}, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    path.write_text(_TARGET_HEADER + body, encoding="utf-8")


class YamlStockTargetLoader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> StockTargetPlan:
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise StockTargetConfigError(f"설정 파일을 읽을 수 없다: {self._path}") from error
        except yaml.YAMLError as error:
            raise StockTargetConfigError(f"YAML 문법 오류: {self._path}: {error}") from error
        if not isinstance(document, dict):
            raise StockTargetConfigError(f"{self._path}: 최상위는 매핑이어야 한다")

        raw_targets = document.get("targets", [])
        if not isinstance(raw_targets, list) or not raw_targets:
            raise StockTargetConfigError(f"{self._path}: targets 목록이 비어 있다")

        try:
            targets = tuple(
                self._target(raw, f"{self._path}.targets[{index}]")
                for index, raw in enumerate(raw_targets)
            )
            return StockTargetPlan(targets=targets)
        except DomainError as error:
            raise StockTargetConfigError(f"{self._path}: 잘못된 종목 목표: {error}") from error

    def _target(self, raw: Any, where: str) -> StockTarget:
        if not isinstance(raw, dict):
            raise StockTargetConfigError(f"{where}: 매핑이어야 한다")
        asset_id = str(raw.get("asset_id") or "").strip()
        if not asset_id:
            raise StockTargetConfigError(f"{where}: asset_id가 필요하다")
        if "target_percent" not in raw:
            raise StockTargetConfigError(f"{where}: target_percent(목표비중)가 필요하다")

        target = Percentage.from_percent(str(raw["target_percent"]))
        # band 하나만 주면 매수/매도 대칭, buy_band/sell_band를 주면 개별 적용
        default_band = str(raw.get("band", "0"))
        buy_band = Percentage.from_percent(str(raw.get("buy_band", default_band)))
        sell_band = Percentage.from_percent(str(raw.get("sell_band", default_band)))
        return StockTarget(asset_id=asset_id, target=target, buy_band=buy_band, sell_band=sell_band)
