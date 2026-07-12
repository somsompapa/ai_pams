"""수집한 시세/환율/지표를 data/ 파일에 기록한다.

- prices.csv / fx.csv: 헤더가 없으면 만들고, 수집된 행을 append.
  같은 (키, 날짜) 행이 이미 있으면 교체(하루 1행)해 중복 적재를 막는다.
- market.yaml: 지표를 병합해 다시 쓴다(항상 최신값).

CsvPriceLookup/CsvFxLookup가 읽는 것과 동일한 형식이라, 수집 즉시 대시보드가 사용한다.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from pams.market_data.application import FetchResult

_PRICE_HEADER = ["asset_id", "price_date", "close", "currency"]
_FX_HEADER = ["base", "quote", "rate_date", "rate"]


# 각 파일의 중복제거 키 (행 → (식별자, 날짜))
def _price_key(row: list[str]) -> tuple[str, str]:
    return (row[0], row[1])


def _fx_key(row: list[str]) -> tuple[str, str]:
    return (f"{row[0]}/{row[1]}", row[2])


@dataclass(frozen=True, slots=True)
class MarketDataFileWriter:
    data_dir: Path

    def write(self, result: FetchResult) -> None:
        self._write_prices(result)
        self._write_fx(result)
        self._write_indicators(result)

    def _write_prices(self, result: FetchResult) -> None:
        if not result.prices:
            return
        path = self.data_dir / "prices.csv"
        rows = self._existing(path, _PRICE_HEADER, _price_key)
        for asset_id, quote in result.prices.items():
            row = [asset_id, quote.quote_date.isoformat(), str(quote.close), quote.currency.value]
            rows[_price_key(row)] = row
        self._write_rows(path, _PRICE_HEADER, rows, sort_key=_price_key)

    def _write_fx(self, result: FetchResult) -> None:
        if not result.fx:
            return
        path = self.data_dir / "fx.csv"
        rate_date = self._as_of(result)
        rows = self._existing(path, _FX_HEADER, _fx_key)
        for (base, quote), rate in result.fx.items():
            row = [base.value, quote.value, rate_date, str(rate)]
            rows[_fx_key(row)] = row
        self._write_rows(path, _FX_HEADER, rows, sort_key=_fx_key)

    def _write_indicators(self, result: FetchResult) -> None:
        if not result.indicators:
            return
        path = self.data_dir / "market.yaml"
        existing: dict[str, str] = {}
        if path.exists():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = {str(k): str(v) for k, v in loaded.items()}
        for name, value in result.indicators.items():
            existing[name] = str(value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(existing, allow_unicode=True, sort_keys=True), encoding="utf-8"
        )

    @staticmethod
    def _existing(
        path: Path, header: list[str], key: Callable[[list[str]], tuple[str, str]]
    ) -> dict[tuple[str, str], list[str]]:
        rows: dict[tuple[str, str], list[str]] = {}
        if not path.exists():
            return rows
        for row in csv.reader(path.read_text(encoding="utf-8-sig").splitlines()):
            if not row or row == header:
                continue
            rows[key(row)] = row
        return rows

    @staticmethod
    def _write_rows(
        path: Path,
        header: list[str],
        rows: dict[tuple[str, str], list[str]],
        *,
        sort_key: Callable[[list[str]], tuple[str, str]],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        ordered: list[list[str]] = sorted(rows.values(), key=sort_key)
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(header)
            writer.writerows(ordered)

    @staticmethod
    def _as_of(result: FetchResult) -> str:
        dates = [q.quote_date for q in result.prices.values()]
        return (max(dates) if dates else datetime.now(UTC).date()).isoformat()
