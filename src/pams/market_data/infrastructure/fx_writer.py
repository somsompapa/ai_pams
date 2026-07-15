"""환율 수동 입력(upsert): data/fx.csv에 사용자가 직접 환율 한 건을 기록한다.

fetch(자동수집)가 못 받아온 통화쌍(예: JPY)을 웹에서 바로 채워 넣을 때 쓴다.
같은 (통화쌍, 날짜) 행이 있으면 교체한다 - MarketDataFileWriter와 동일한 규칙.
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from pams.shared_kernel.domain import Currency

_HEADER = ["base", "quote", "rate_date", "rate"]


def _sort_key(row: list[str]) -> tuple[str, str, str]:
    return (row[0], row[1], row[2])


def upsert_fx_rate(
    path: Path, base: Currency, quote: Currency, rate_date: date, rate: Decimal
) -> None:
    rows: dict[tuple[str, str, str], list[str]] = {}
    if path.exists():
        for row in csv.reader(path.read_text(encoding="utf-8-sig").splitlines()):
            if not row or row == _HEADER:
                continue
            rows[(row[0], row[1], row[2])] = row

    key = (base.value, quote.value, rate_date.isoformat())
    rows[key] = [base.value, quote.value, rate_date.isoformat(), str(rate)]

    ordered: list[list[str]] = sorted(rows.values(), key=_sort_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(_HEADER)
        writer.writerows(ordered)
