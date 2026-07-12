"""config/stock_targets/*.yaml → StockTargetPlan 로더."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pams.equity.domain import StockTarget, StockTargetPlan
from pams.shared_kernel.domain import DomainError, Percentage


class StockTargetConfigError(Exception):
    """종목 목표 설정 파일을 StockTargetPlan으로 변환하는 데 실패했다."""


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
