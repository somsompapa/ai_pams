"""config/dca/*.yaml → DcaPlan 로더."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pams.dca.domain import DcaEntry, DcaFrequency, DcaPlan
from pams.shared_kernel.domain import Currency, DomainError, Money, Quantity

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class DcaConfigError(Exception):
    """DCA 설정 파일을 DcaPlan으로 변환하는 데 실패했다."""


class YamlDcaPlanLoader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> DcaPlan:
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise DcaConfigError(f"설정 파일을 읽을 수 없다: {self._path}") from error
        except yaml.YAMLError as error:
            raise DcaConfigError(f"YAML 문법 오류: {self._path}: {error}") from error
        if not isinstance(document, dict):
            raise DcaConfigError(f"{self._path}: 최상위는 매핑이어야 한다")

        raw_entries = document.get("entries", [])
        if not isinstance(raw_entries, list) or not raw_entries:
            raise DcaConfigError(f"{self._path}: entries 목록이 비어 있다")

        try:
            entries = tuple(
                self._entry(raw, f"{self._path}.entries[{index}]")
                for index, raw in enumerate(raw_entries)
            )
            return DcaPlan(entries=entries)
        except DomainError as error:
            raise DcaConfigError(f"{self._path}: 잘못된 DCA 규칙: {error}") from error

    def _entry(self, raw: Any, where: str) -> DcaEntry:
        if not isinstance(raw, dict):
            raise DcaConfigError(f"{where}: 매핑이어야 한다")
        asset_id = str(raw.get("asset_id") or "").strip()
        if not asset_id:
            raise DcaConfigError(f"{where}: asset_id가 필요하다")

        frequency = self._frequency(raw.get("frequency"), where)
        weekday = self._weekday(raw.get("weekday"), where) if "weekday" in raw else None
        amount = self._amount(raw, where)
        quantity = self._quantity(raw.get("quantity"), where)

        return DcaEntry(
            asset_id=asset_id,
            frequency=frequency,
            amount=amount,
            quantity=quantity,
            weekday=weekday,
            note=str(raw.get("note") or ""),
        )

    @staticmethod
    def _frequency(value: Any, where: str) -> DcaFrequency:
        try:
            return DcaFrequency(str(value))
        except ValueError:
            raise DcaConfigError(
                f"{where}: 알 수 없는 frequency {value!r} (daily/weekly)"
            ) from None

    @staticmethod
    def _weekday(value: Any, where: str) -> int:
        key = str(value).strip().lower()
        if key not in _WEEKDAYS:
            raise DcaConfigError(f"{where}: 알 수 없는 weekday {value!r} (monday~sunday)")
        return _WEEKDAYS[key]

    @staticmethod
    def _amount(raw: dict[str, Any], where: str) -> Money | None:
        if "amount" not in raw:
            return None
        currency_raw = raw.get("currency")
        if currency_raw is None:
            raise DcaConfigError(f"{where}: amount에는 currency가 필요하다")
        try:
            currency = Currency(str(currency_raw))
        except ValueError:
            raise DcaConfigError(f"{where}: 알 수 없는 통화 {currency_raw!r}") from None
        return Money.of(str(raw.get("amount")), currency)

    @staticmethod
    def _quantity(value: Any, where: str) -> Quantity | None:
        if value is None:
            return None
        return Quantity.of(str(value))
