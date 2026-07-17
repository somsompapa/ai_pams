"""POST /api/sell-review 통합 테스트."""

from pathlib import Path

from fastapi.testclient import TestClient

from pams.interfaces.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path))


class TestSellReviewApi:
    def test_no_signals_recommends_nothing(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/api/sell-review", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["review_recommended"] is False
        assert body["suggested_sell_fraction"] is None

    def test_growth_deceleration_recommends_review(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post(
            "/api/sell-review", json={"revenue_yoy_growth_deceleration_pp": "0.06"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["review_recommended"] is True
        assert body["thesis_break_triggered"] is True

    def test_dcf_gap_100pct_suggests_50pct_sell(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/api/sell-review", json={"dcf_gap_ratio": "1.2"})
        assert response.status_code == 200
        body = response.json()
        assert body["review_recommended"] is True
        assert body["suggested_sell_fraction"] == "0.50"

    def test_dcf_gap_50pct_suggests_25pct_sell(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/api/sell-review", json={"dcf_gap_ratio": "0.55"})
        body = response.json()
        assert body["suggested_sell_fraction"] == "0.25"

    def test_structural_disruption_note_passed_through(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post(
            "/api/sell-review",
            json={"structural_disruption": True, "structural_disruption_note": "대체재 등장"},
        )
        body = response.json()
        signal = next(
            s for s in body["thesis_break_signals"] if s["reason"] == "산업 구조 변화"
        )
        assert signal["triggered"] is True
        assert signal["detail"] == "대체재 등장"

    def test_invalid_decimal_returns_400(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/api/sell-review", json={"dcf_gap_ratio": "not-a-number"})
        assert response.status_code == 400

    def test_sell_review_leaves_audit_event(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        client.post("/api/sell-review", json={"dcf_gap_ratio": "1.2"})
        audit_log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "sell_review.evaluated" in audit_log
