"""POST /api/buy-gate 통합 테스트."""

from pathlib import Path

from fastapi.testclient import TestClient

from pams.interfaces.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path))


_ALL_PASS_PAYLOAD = {
    "total_score": "85",
    "dcf_gap_ratio": "-0.15",
    "market_grade": "B",
    "investment_thesis": "3년 내 매출 CAGR 15% 지속 가능, 근거: OO",
}


class TestBuyGateApi:
    def test_all_conditions_met(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/api/buy-gate", json=_ALL_PASS_PAYLOAD)
        assert response.status_code == 200
        body = response.json()
        assert body["all_conditions_met"] is True
        assert len(body["conditions"]) == 4

    def test_score_below_80_blocks(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/api/buy-gate", json={**_ALL_PASS_PAYLOAD, "total_score": "79"})
        body = response.json()
        assert body["all_conditions_met"] is False

    def test_market_grade_d_blocks(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/api/buy-gate", json={**_ALL_PASS_PAYLOAD, "market_grade": "D"})
        body = response.json()
        assert body["all_conditions_met"] is False

    def test_missing_market_grade_blocks(self, tmp_path: Path) -> None:
        """market_grade 미확보(예: 시장국면 판단 보류)는 조건2 미충족으로 취급한다."""
        client = _client(tmp_path)
        response = client.post("/api/buy-gate", json={**_ALL_PASS_PAYLOAD, "market_grade": None})
        body = response.json()
        assert body["all_conditions_met"] is False

    def test_price_not_discounted_enough_blocks(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post(
            "/api/buy-gate", json={**_ALL_PASS_PAYLOAD, "dcf_gap_ratio": "-0.05"}
        )
        body = response.json()
        assert body["all_conditions_met"] is False

    def test_empty_thesis_blocks(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/api/buy-gate", json={**_ALL_PASS_PAYLOAD, "investment_thesis": ""})
        body = response.json()
        assert body["all_conditions_met"] is False

    def test_invalid_total_score_returns_400(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post(
            "/api/buy-gate", json={**_ALL_PASS_PAYLOAD, "total_score": "not-a-number"}
        )
        assert response.status_code == 400

    def test_buy_gate_leaves_audit_event(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        client.post("/api/buy-gate", json=_ALL_PASS_PAYLOAD)
        audit_log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "buy_gate.evaluated" in audit_log
