"""POST /api/market-regime 통합 테스트. 실제 config/market_regime/default.yaml을 그대로 쓴다."""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from pams.interfaces.api.app import create_app
from pams.market_regime.domain import MarketRegimeProviderError


@dataclass(frozen=True, slots=True)
class _FailingIndicatorProvider:
    """실네트워크를 절대 타지 않게 하는 기본 테스트용 공급자 — 항상 실패한다.
    자동조회 없이 명시 입력값만으로 검증하는 테스트에 쓴다."""

    def fetch_vix(self) -> Decimal:
        raise MarketRegimeProviderError("test: 자동조회 비활성")

    def fetch_kospi_change_pct(self) -> Decimal:
        raise MarketRegimeProviderError("test: 자동조회 비활성")


@dataclass(frozen=True, slots=True)
class _FakeIndicatorProvider:
    vix: Decimal
    kospi_change_pct: Decimal

    def fetch_vix(self) -> Decimal:
        return self.vix

    def fetch_kospi_change_pct(self) -> Decimal:
        return self.kospi_change_pct


def _client(tmp_path: Path, provider: object | None = None) -> TestClient:
    return TestClient(
        create_app(
            data_dir=tmp_path,
            market_indicator_provider=provider or _FailingIndicatorProvider(),
        )
    )


class TestMarketRegimeApi:
    def test_rulebook_example_1_yields_grade_a(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post(
            "/api/market-regime",
            json={
                "vix": "13",
                "circuit_breaker": "0",
                "treasury_10y": "stable_or_down",
                "sp500_per": "mid",
                "kospi_foreign_flow": "net_buy",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["final_grade"] == "A"
        assert body["tie_broken"] is False
        assert body["buy_allowed"] is True
        assert len(body["indicator_grades"]) == 5

    def test_rulebook_example_2_tie_yields_conservative_grade_d(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post(
            "/api/market-regime",
            json={
                "vix": "22",
                "circuit_breaker": "0",
                "treasury_10y": "spike",
                "sp500_per": "near_upper",
                "kospi_foreign_flow": "turning_buy",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["final_grade"] == "D"
        assert body["tie_broken"] is True
        assert body["buy_allowed"] is False

    def test_insufficient_indicators_returns_judgment_withheld(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/api/market-regime", json={"vix": "13"})
        assert response.status_code == 200
        body = response.json()
        assert body["final_grade"] is None
        assert body["buy_allowed"] is False

    def test_omitted_vix_and_circuit_breaker_auto_fetched(self, tmp_path: Path) -> None:
        provider = _FakeIndicatorProvider(vix=Decimal("13"), kospi_change_pct=Decimal("0"))
        client = _client(tmp_path, provider)
        response = client.post(
            "/api/market-regime",
            json={
                "treasury_10y": "stable_or_down",
                "sp500_per": "mid",
                "kospi_foreign_flow": "net_buy",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["final_grade"] == "A"
        assert body["fetch_errors"] == []
        vix_grade = next(ig for ig in body["indicator_grades"] if ig["indicator"] == "vix")
        assert vix_grade["observed"] == "13"

    def test_explicit_vix_overrides_auto_fetch(self, tmp_path: Path) -> None:
        """명시 입력이 있으면 자동조회 값으로 덮어쓰지 않는다."""
        provider = _FakeIndicatorProvider(vix=Decimal("40"), kospi_change_pct=Decimal("0"))
        client = _client(tmp_path, provider)
        response = client.post(
            "/api/market-regime",
            json={
                "vix": "13",
                "treasury_10y": "stable_or_down",
                "sp500_per": "mid",
                "kospi_foreign_flow": "net_buy",
            },
        )
        body = response.json()
        vix_grade = next(ig for ig in body["indicator_grades"] if ig["indicator"] == "vix")
        assert vix_grade["observed"] == "13"

    def test_auto_fetch_failure_degrades_to_missing_not_crash(self, tmp_path: Path) -> None:
        client = _client(tmp_path)  # 기본 _FailingIndicatorProvider — 항상 실패
        response = client.post(
            "/api/market-regime",
            json={
                "treasury_10y": "stable_or_down",
                "sp500_per": "mid",
                "kospi_foreign_flow": "net_buy",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["fetch_errors"]) == 2
        vix_grade = next(ig for ig in body["indicator_grades"] if ig["indicator"] == "vix")
        assert vix_grade["observed"] == "데이터 누락"
        # 자동조회 실패해도 나머지 3개 지표로는 여전히 판정 가능(3개 이상 확보)
        assert body["final_grade"] is not None

    def test_invalid_vix_returns_400(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/api/market-regime", json={"vix": "not-a-number"})
        assert response.status_code == 400

    def test_market_regime_leaves_audit_event(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        client.post(
            "/api/market-regime",
            json={
                "vix": "13",
                "circuit_breaker": "0",
                "treasury_10y": "stable_or_down",
                "sp500_per": "mid",
                "kospi_foreign_flow": "net_buy",
            },
        )
        audit_log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "market_regime.graded" in audit_log
