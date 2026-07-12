"""config/market/symbols.yaml에 시세 자동수집 심볼 매핑을 추가한다."""

from __future__ import annotations

from pathlib import Path

import yaml

_HEADER = "# 시세 자동수집 심볼 매핑 (대시보드에서 관리됨)\n"


def upsert_price_symbol(path: Path, asset_id: str, yahoo_symbol: str) -> None:
    """prices 섹션에 asset_id → Yahoo 심볼 매핑을 추가/교체한다.

    이 매핑이 있어야 `fetch`가 해당 종목의 시세를 자동으로 받아온다.
    """
    document = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    if not isinstance(document, dict):
        document = {}
    prices = document.get("prices")
    if not isinstance(prices, dict):
        prices = {}
    prices[asset_id] = yahoo_symbol
    document["prices"] = prices

    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(document, allow_unicode=True, sort_keys=False, default_flow_style=False)
    path.write_text(_HEADER + body, encoding="utf-8")
