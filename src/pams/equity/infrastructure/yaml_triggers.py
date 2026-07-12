"""config/triggers/*.yaml → PriceTriggerPlan 로더."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pams.equity.domain import PriceTrigger, PriceTriggerPlan
from pams.shared_kernel.domain import Currency, DomainError, Money


class PriceTriggerConfigError(Exception):
    """가격 트리거 설정 파일을 PriceTriggerPlan으로 변환하는 데 실패했다."""


class YamlPriceTriggerLoader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> PriceTriggerPlan:
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise PriceTriggerConfigError(f"설정 파일을 읽을 수 없다: {self._path}") from error
        except yaml.YAMLError as error:
            raise PriceTriggerConfigError(f"YAML 문법 오류: {self._path}: {error}") from error
        if not isinstance(document, dict):
            raise PriceTriggerConfigError(f"{self._path}: 최상위는 매핑이어야 한다")

        raw = document.get("triggers", [])
        if not isinstance(raw, list) or not raw:
            raise PriceTriggerConfigError(f"{self._path}: triggers 목록이 비어 있다")

        try:
            triggers = tuple(
                self._trigger(entry, f"{self._path}.triggers[{index}]")
                for index, entry in enumerate(raw)
            )
            return PriceTriggerPlan(triggers=triggers)
        except DomainError as error:
            raise PriceTriggerConfigError(f"{self._path}: 잘못된 트리거: {error}") from error

    def _trigger(self, entry: Any, where: str) -> PriceTrigger:
        if not isinstance(entry, dict):
            raise PriceTriggerConfigError(f"{where}: 매핑이어야 한다")
        asset_id = str(entry.get("asset_id") or "").strip()
        if not asset_id:
            raise PriceTriggerConfigError(f"{where}: asset_id가 필요하다")
        currency_raw = entry.get("currency")
        if currency_raw is None:
            raise PriceTriggerConfigError(f"{where}: currency가 필요하다")
        try:
            currency = Currency(str(currency_raw))
        except ValueError:
            raise PriceTriggerConfigError(f"{where}: 알 수 없는 통화 {currency_raw!r}") from None

        buy_at = (
            Money.of(str(entry["buy_at"]), currency) if entry.get("buy_at") is not None else None
        )
        sell_at = (
            Money.of(str(entry["sell_at"]), currency) if entry.get("sell_at") is not None else None
        )
        return PriceTrigger(asset_id=asset_id, buy_at=buy_at, sell_at=sell_at)
