"""CSV 파일 기반 시세/환율 조회.

증권사·데이터 API 어댑터가 붙기 전까지의 기본 공급자다. 사용자는
data/prices.csv, data/fx.csv 를 직접 채우거나 외부 스크립트로 갱신한다.

핵심 계약: as_of 당일 데이터가 없으면 '직전' 데이터를 쓴다 (주말/휴장 대응).
as_of 이후의 미래 데이터는 절대 반환하지 않는다.

형식:
- prices.csv: asset_id,price_date,close,currency
- fx.csv:     base,quote,rate_date,rate  (1 base = rate × quote)
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pams.shared_kernel.domain import Currency, Money


class CsvDataError(Exception):
    """CSV 시장 데이터 파일을 읽는 데 실패했다."""


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _read_rows(path: Path) -> list[tuple[int, dict[str, str | None]]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise CsvDataError(f"시장 데이터 파일을 읽을 수 없다: {path}") from error
    return list(enumerate(csv.DictReader(text.splitlines()), start=2))  # 1행 = 헤더


def _parse_date(value: str | None, where: str) -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        raise CsvDataError(f"{where}: 잘못된 날짜 {value!r}") from None


def _parse_decimal(value: str | None, where: str, field: str) -> Decimal:
    try:
        return Decimal((value or "").strip())
    except InvalidOperation:
        raise CsvDataError(f"{where}: {field} 값이 숫자가 아니다: {value!r}") from None


class CsvPriceLookup:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._prices: dict[str, list[tuple[date, Money]]] | None = None
        self._loaded_mtime: float | None = None

    def price_of(self, asset_id: str, as_of: date) -> Money | None:
        history = self._load().get(asset_id, [])
        for price_date, price in reversed(history):
            if price_date <= as_of:
                return price
        return None

    def _load(self) -> dict[str, list[tuple[date, Money]]]:
        # 파일이 갱신되면(매일 fetch 등) 자동으로 다시 읽는다.
        mtime = _mtime(self._path)
        if self._prices is not None and mtime == self._loaded_mtime:
            return self._prices
        self._loaded_mtime = mtime
        prices: dict[str, list[tuple[date, Money]]] = {}
        for row_number, row in _read_rows(self._path):
            where = f"{self._path} {row_number}행"
            asset_id = (row.get("asset_id") or "").strip()
            if not asset_id:
                raise CsvDataError(f"{where}: asset_id가 비어 있다")
            try:
                currency = Currency((row.get("currency") or "").strip())
            except ValueError:
                raise CsvDataError(f"{where}: 알 수 없는 통화 {row.get('currency')!r}") from None
            entry = (
                _parse_date(row.get("price_date"), where),
                Money(_parse_decimal(row.get("close"), where, "close"), currency),
            )
            prices.setdefault(asset_id, []).append(entry)
        for history in prices.values():
            history.sort(key=lambda pair: pair[0])
        self._prices = prices
        return prices


class CsvFxLookup:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._rates: dict[tuple[Currency, Currency], list[tuple[date, Decimal]]] | None = None
        self._loaded_mtime: float | None = None

    def rate_to(self, currency: Currency, base: Currency, as_of: date) -> Decimal | None:
        history = self._load().get((currency, base), [])
        for rate_date, rate in reversed(history):
            if rate_date <= as_of:
                return rate
        return None

    def _load(self) -> dict[tuple[Currency, Currency], list[tuple[date, Decimal]]]:
        mtime = _mtime(self._path)
        if self._rates is not None and mtime == self._loaded_mtime:
            return self._rates
        self._loaded_mtime = mtime
        rates: dict[tuple[Currency, Currency], list[tuple[date, Decimal]]] = {}
        for row_number, row in _read_rows(self._path):
            where = f"{self._path} {row_number}행"
            try:
                pair = (
                    Currency((row.get("base") or "").strip()),
                    Currency((row.get("quote") or "").strip()),
                )
            except ValueError:
                raise CsvDataError(
                    f"{where}: 알 수 없는 통화쌍 {row.get('base')!r}/{row.get('quote')!r}"
                ) from None
            entry = (
                _parse_date(row.get("rate_date"), where),
                _parse_decimal(row.get("rate"), where, "rate"),
            )
            rates.setdefault(pair, []).append(entry)
        for history in rates.values():
            history.sort(key=lambda pair: pair[0])
        self._rates = rates
        return rates
