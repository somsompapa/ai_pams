"""POST /api/market-regime 통합 테스트. 실제 config/market_regime/default.yaml을 그대로 쓴다."""

from pathlib import Path

from fastapi.testclient import TestClient

from pams.interfaces.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path))


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
