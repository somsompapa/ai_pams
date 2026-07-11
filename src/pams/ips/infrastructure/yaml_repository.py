"""YAML 파일 기반 투자헌장 저장소.

config/ips/*.yaml (목표비중)과 config/rules/*.yaml (규칙)을 도메인 객체로 변환한다.
모든 파싱 실패는 파일/항목 위치가 담긴 ConfigParseError로 통일한다.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

import yaml

from pams.ips.domain import (
    AllocationTarget,
    ComparisonOperator,
    Condition,
    PolicyStatement,
    Rule,
    RuleAction,
    Severity,
)
from pams.shared_kernel.domain import AssetClass, Currency, DomainError, Percentage


class ConfigParseError(Exception):
    """설정 파일을 도메인 객체로 변환하는 데 실패했다."""


def _to_decimal(value: object, where: str) -> Decimal:
    """YAML 숫자를 Decimal로 변환한다.

    권장 표기는 문자열("0.70")이다. YAML이 float로 파싱한 값은 str을 거쳐
    변환해 작성자가 적은 표기 그대로 보존한다 (이진 오차 유입 방지).
    """
    if isinstance(value, bool) or value is None:
        raise ConfigParseError(f"{where}: 숫자가 필요하다: {value!r}")
    if isinstance(value, float):
        value = str(value)
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise ConfigParseError(f"{where}: 숫자로 해석할 수 없다: {value!r}") from error


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ConfigParseError(f"{where}: 필수 항목 '{key}'가 없다")
    return mapping[key]


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigParseError(f"설정 파일을 읽을 수 없다: {path}") from error
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigParseError(f"YAML 문법 오류: {path}: {error}") from error
    if not isinstance(document, dict):
        raise ConfigParseError(f"{path}: 최상위는 매핑(key: value)이어야 한다")
    return document


E = TypeVar("E", bound=Enum)


def _parse_enum(enum_type: type[E], value: object, where: str) -> E:
    try:
        return enum_type(value)
    except ValueError:
        raise ConfigParseError(f"{where}: 알 수 없는 값 {value!r}") from None


def _parse_target(entry: dict[str, Any], where: str) -> AllocationTarget:
    asset_class = _parse_enum(
        AssetClass, _require(entry, "asset_class", where), f"{where}.asset_class"
    )
    target = _to_decimal(_require(entry, "target_percent", where), f"{where}.target_percent")
    band = _to_decimal(_require(entry, "band_percent", where), f"{where}.band_percent")
    return AllocationTarget(
        asset_class=asset_class,
        target=Percentage.from_percent(target),
        band=Percentage.from_percent(band),
    )


def _parse_condition(entry: dict[str, Any], where: str) -> Condition:
    return Condition(
        metric=str(_require(entry, "metric", where)),
        operator=_parse_enum(
            ComparisonOperator, _require(entry, "operator", where), f"{where}.operator"
        ),
        value=_to_decimal(_require(entry, "value", where), f"{where}.value"),
    )


def _parse_rule(entry: dict[str, Any], where: str) -> Rule:
    conditions = _require(entry, "when", where)
    if not isinstance(conditions, list):
        raise ConfigParseError(f"{where}.when: 조건 목록이어야 한다")
    then = _require(entry, "then", where)
    if not isinstance(then, dict):
        raise ConfigParseError(f"{where}.then: 매핑이어야 한다")
    raw_params = then.get("params", {})
    if not isinstance(raw_params, dict):
        raise ConfigParseError(f"{where}.then.params: 매핑이어야 한다")
    return Rule(
        rule_id=str(_require(entry, "id", where)),
        description=str(_require(entry, "description", where)),
        severity=_parse_enum(Severity, _require(entry, "severity", where), f"{where}.severity"),
        conditions=tuple(
            _parse_condition(c, f"{where}.when[{i}]") for i, c in enumerate(conditions)
        ),
        action=RuleAction(
            action_type=str(_require(then, "action", f"{where}.then")),
            params={str(k): str(v) for k, v in raw_params.items()},
        ),
    )


class YamlPolicyRepository:
    def __init__(self, ips_path: Path, rules_path: Path) -> None:
        self._ips_path = ips_path
        self._rules_path = rules_path

    def load(self) -> PolicyStatement:
        ips_doc = _load_yaml(self._ips_path)
        rules_doc = _load_yaml(self._rules_path)

        raw_targets = _require(ips_doc, "allocation_targets", str(self._ips_path))
        if not isinstance(raw_targets, list):
            raise ConfigParseError(f"{self._ips_path}: allocation_targets는 목록이어야 한다")
        raw_rules = rules_doc.get("rules", [])
        if not isinstance(raw_rules, list):
            raise ConfigParseError(f"{self._rules_path}: rules는 목록이어야 한다")

        try:
            return PolicyStatement(
                name=str(_require(ips_doc, "name", str(self._ips_path))),
                base_currency=_parse_enum(
                    Currency,
                    _require(ips_doc, "base_currency", str(self._ips_path)),
                    f"{self._ips_path}.base_currency",
                ),
                targets=tuple(
                    _parse_target(t, f"{self._ips_path}.allocation_targets[{i}]")
                    for i, t in enumerate(raw_targets)
                ),
                rules=tuple(
                    _parse_rule(r, f"{self._rules_path}.rules[{i}]")
                    for i, r in enumerate(raw_rules)
                ),
            )
        except DomainError as error:
            raise ConfigParseError(
                f"설정이 도메인 규칙을 위반한다 ({self._ips_path}, {self._rules_path}): {error}"
            ) from error
