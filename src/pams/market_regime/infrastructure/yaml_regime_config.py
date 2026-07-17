"""config/market_regime/*.yaml → MarketRegimeConfig 로더."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from pams.market_regime.domain.regime import MarketRegimeConfig
from pams.shared_kernel.domain import (
    Band,
    BandDirection,
    BandTable,
    CategoricalOption,
    CategoricalTable,
    DomainError,
)


class RegimeConfigError(Exception):
    """시장 국면 설정 파일을 MarketRegimeConfig로 변환하는 데 실패했다."""


class YamlMarketRegimeConfigLoader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> MarketRegimeConfig:
        document = self._read()
        try:
            indicators = self._require(document, "indicators")
            return MarketRegimeConfig(
                vix=self._band_table("indicators.vix", indicators["vix"]),
                circuit_breaker=self._band_table(
                    "indicators.circuit_breaker", indicators["circuit_breaker"]
                ),
                treasury_10y=self._categorical_table(
                    "indicators.treasury_10y", indicators["treasury_10y"]
                ),
                sp500_per=self._categorical_table("indicators.sp500_per", indicators["sp500_per"]),
                kospi_foreign_flow=self._categorical_table(
                    "indicators.kospi_foreign_flow", indicators["kospi_foreign_flow"]
                ),
                sources={
                    "vix": str(indicators["vix"]["source"]),
                    "circuit_breaker": str(indicators["circuit_breaker"]["source"]),
                    "treasury_10y": str(indicators["treasury_10y"]["source"]),
                    "sp500_per": str(indicators["sp500_per"]["source"]),
                    "kospi_foreign_flow": str(indicators["kospi_foreign_flow"]["source"]),
                },
                min_indicators_required=int(document.get("min_indicators_required", 3)),
            )
        except (DomainError, KeyError, ValueError) as error:
            raise RegimeConfigError(f"{self._path}: 잘못된 시장국면 설정: {error}") from error

    def _read(self) -> dict[str, Any]:
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise RegimeConfigError(f"설정 파일을 읽을 수 없다: {self._path}") from error
        except yaml.YAMLError as error:
            raise RegimeConfigError(f"YAML 문법 오류: {self._path}: {error}") from error
        if not isinstance(document, dict):
            raise RegimeConfigError(f"{self._path}: 최상위는 매핑이어야 한다")
        return document

    def _require(self, document: dict[str, Any], key: str) -> Any:
        if key not in document:
            raise RegimeConfigError(f"{self._path}: 필수 항목 '{key}'가 없다")
        return document[key]

    def _decimal(self, label: str, value: object) -> Decimal:
        try:
            return Decimal(str(value))
        except InvalidOperation as error:
            raise RegimeConfigError(
                f"{self._path}.{label}: 숫자로 해석할 수 없다: {value!r}"
            ) from error

    def _band_table(self, label: str, node: dict[str, Any]) -> BandTable:
        direction = BandDirection(node["direction"])
        bands = tuple(
            Band(
                bound=self._decimal(f"{label}.bands[{i}].bound", b["bound"]),
                score=self._decimal(f"{label}.bands[{i}].rank", b["rank"]),
                label=f"{b['grade']}:{b['basis']}",
            )
            for i, b in enumerate(node["bands"])
        )
        return BandTable(metric=label, max_score=Decimal(4), direction=direction, bands=bands)

    def _categorical_table(self, label: str, node: dict[str, Any]) -> CategoricalTable:
        options = {
            str(key): CategoricalOption(
                score=self._decimal(f"{label}.options.{key}.rank", opt["rank"]),
                label=f"{opt['grade']}:{opt['basis']}",
            )
            for key, opt in node["options"].items()
        }
        return CategoricalTable(metric=label, max_score=Decimal(4), options=options)
