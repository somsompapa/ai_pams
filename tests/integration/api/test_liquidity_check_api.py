"""POST /api/liquidity-check 통합 테스트 (portfolio_rules.md P-5, v1.6.1 신규)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from pams.interfaces.api.app import create_app
from pams.market_data.domain import DailyBar, MarketDataProviderError, Quote


@dataclass(frozen=True, slots=True)
class _FakeDailyVolumeProvider:
    bars_by_symbol: dict[str, tuple[DailyBar, ...]]

    def latest_quote(self, symbol: str) -> Quote | None:
        return None

    def recent_daily_bars(self, symbol: str, *, days: int = 20) -> tuple[DailyBar, ...]:
        return self.bars_by_symbol.get(symbol, ())


@dataclass(frozen=True, slots=True)
class _FailingQuoteProvider:
    def latest_quote(self, symbol: str) -> Quote | None:
        raise MarketDataProviderError(f"{symbol}: 요청 실패")


def _bars(close: str, volume: int, count: int = 20) -> tuple[DailyBar, ...]:
    return tuple(
        DailyBar(quote_date=date(2026, 1, d + 1), close=Decimal(close), volume=volume)
        for d in range(count)
    )


def _client(tmp_path: Path, price_provider: object | None = None) -> TestClient:
    return TestClient(
        create_app(
            data_dir=tmp_path, equity_price_provider=price_provider or _FailingQuoteProvider()
        )  # type: ignore[arg-type]
    )


class TestLiquidityCheckApi:
    def test_sufficient_liquidity(self, tmp_path: Path) -> None:
        provider = _FakeDailyVolumeProvider({"TEST": _bars("100", 1_000_000)})
        client = _client(tmp_path, provider)
        response = client.post(
            "/api/liquidity-check",
            json={"asset_id": "TEST", "market": "US", "planned_first_tranche_amount": "5000000"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["sufficient"] is True
        assert body["average_daily_trading_value"] == "100000000.00"
        assert body["days_observed"] == 20

    def test_insufficient_liquidity(self, tmp_path: Path) -> None:
        provider = _FakeDailyVolumeProvider({"TEST": _bars("100", 1000)})
        client = _client(tmp_path, provider)
        response = client.post(
            "/api/liquidity-check",
            json={"asset_id": "TEST", "market": "US", "planned_first_tranche_amount": "5000000"},
        )
        body = response.json()
        assert body["sufficient"] is False

    def test_kr_market_tries_ks_then_kq_suffix(self, tmp_path: Path) -> None:
        provider = _FakeDailyVolumeProvider({"005930.KQ": _bars("70000", 500_000)})
        client = _client(tmp_path, provider)
        response = client.post(
            "/api/liquidity-check",
            json={"asset_id": "005930", "market": "KR", "planned_first_tranche_amount": "1000000"},
        )
        body = response.json()
        assert body["sufficient"] is True

    def test_provider_without_daily_bars_support_returns_note(self, tmp_path: Path) -> None:
        """price_provider가 recent_daily_bars를 지원하지 않으면(선택 기능) 조용히
        판정 불가로 처리한다 — 예외를 던지지 않는다."""
        client = _client(tmp_path)
        response = client.post(
            "/api/liquidity-check",
            json={"asset_id": "TEST", "market": "US", "planned_first_tranche_amount": "5000000"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["sufficient"] is None
        assert body["note"] is not None

    def test_invalid_amount_returns_400(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post(
            "/api/liquidity-check",
            json={
                "asset_id": "TEST",
                "market": "US",
                "planned_first_tranche_amount": "not-a-number",
            },
        )
        assert response.status_code == 400

    def test_leaves_audit_event(self, tmp_path: Path) -> None:
        provider = _FakeDailyVolumeProvider({"TEST": _bars("100", 1_000_000)})
        client = _client(tmp_path, provider)
        client.post(
            "/api/liquidity-check",
            json={"asset_id": "TEST", "market": "US", "planned_first_tranche_amount": "5000000"},
        )
        audit_log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "liquidity_check.evaluated" in audit_log
