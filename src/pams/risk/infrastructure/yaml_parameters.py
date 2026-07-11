"""config/risk/*.yaml → RiskParameters 로더."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from pams.risk.domain import RiskParameters
from pams.shared_kernel.domain import DomainError


class RiskConfigError(Exception):
    """리스크 설정 파일을 RiskParameters로 변환하는 데 실패했다."""


class YamlRiskParametersLoader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> RiskParameters:
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise RiskConfigError(f"설정 파일을 읽을 수 없다: {self._path}") from error
        except yaml.YAMLError as error:
            raise RiskConfigError(f"YAML 문법 오류: {self._path}: {error}") from error
        if not isinstance(document, dict):
            raise RiskConfigError(f"{self._path}: 최상위는 매핑이어야 한다")

        try:
            return RiskParameters(
                periods_per_year=int(str(self._require(document, "periods_per_year"))),
                risk_free_rate=self._decimal(document, "risk_free_rate"),
                var_confidence=self._decimal(document, "var_confidence"),
            )
        except (DomainError, ValueError) as error:
            raise RiskConfigError(f"{self._path}: 잘못된 리스크 파라미터: {error}") from error

    def _require(self, document: dict[str, object], key: str) -> object:
        if key not in document:
            raise RiskConfigError(f"{self._path}: 필수 항목 '{key}'가 없다")
        return document[key]

    def _decimal(self, document: dict[str, object], key: str) -> Decimal:
        value = self._require(document, key)
        try:
            return Decimal(str(value))
        except InvalidOperation as error:
            raise RiskConfigError(
                f"{self._path}.{key}: 숫자로 해석할 수 없다: {value!r}"
            ) from error
