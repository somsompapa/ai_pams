"""VIX/KOSPI 등락률 자동조회 포트. infrastructure에서 구현한다(DIP) — 소스 교체 가능."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class MarketIndicatorProvider(Protocol):
    def fetch_vix(self) -> Decimal:
        """^VIX 최신 종가. 조회 실패 시 MarketRegimeProviderError."""
        ...

    def fetch_kospi_change_pct(self) -> Decimal:
        """KOSPI 전일 대비 등락률(%). 조회 실패 시 MarketRegimeProviderError."""
        ...
