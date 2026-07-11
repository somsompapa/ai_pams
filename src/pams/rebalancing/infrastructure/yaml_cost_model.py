"""config/costs/*.yaml → CostModel 로더."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from pams.rebalancing.domain import CostModel, TradingCostRates
from pams.shared_kernel.domain import AssetClass, DomainError, Percentage


class CostConfigError(Exception):
    """거래비용 설정 파일을 CostModel로 변환하는 데 실패했다."""


class YamlCostModelLoader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> CostModel:
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise CostConfigError(f"설정 파일을 읽을 수 없다: {self._path}") from error
        except yaml.YAMLError as error:
            raise CostConfigError(f"YAML 문법 오류: {self._path}: {error}") from error
        if not isinstance(document, dict):
            raise CostConfigError(f"{self._path}: 최상위는 매핑이어야 한다")

        raw_default = document.get("default")
        if not isinstance(raw_default, dict):
            raise CostConfigError(f"{self._path}: 'default' 요율 정의가 필요하다")
        raw_costs = document.get("costs", [])
        if not isinstance(raw_costs, list):
            raise CostConfigError(f"{self._path}: costs는 목록이어야 한다")

        try:
            rates = {}
            for index, entry in enumerate(raw_costs):
                where = f"{self._path}.costs[{index}]"
                if not isinstance(entry, dict):
                    raise CostConfigError(f"{where}: 매핑이어야 한다")
                asset_class = self._asset_class(entry, where)
                rates[asset_class] = self._rates(entry, where)
            return CostModel(rates=rates, default=self._rates(raw_default, f"{self._path}.default"))
        except DomainError as error:
            raise CostConfigError(f"{self._path}: 잘못된 요율: {error}") from error

    @staticmethod
    def _asset_class(entry: dict[str, Any], where: str) -> AssetClass:
        value = entry.get("asset_class")
        try:
            return AssetClass(str(value))
        except ValueError:
            raise CostConfigError(f"{where}: 알 수 없는 자산군 {value!r}") from None

    @staticmethod
    def _rates(entry: dict[str, Any], where: str) -> TradingCostRates:
        def ratio(key: str) -> Percentage:
            if key not in entry:
                raise CostConfigError(f"{where}: 필수 항목 '{key}'가 없다")
            try:
                return Percentage.from_ratio(Decimal(str(entry[key])))
            except InvalidOperation:
                raise CostConfigError(
                    f"{where}.{key}: 숫자로 해석할 수 없다: {entry[key]!r}"
                ) from None

        return TradingCostRates(fee_rate=ratio("fee_rate"), sell_tax_rate=ratio("sell_tax_rate"))
