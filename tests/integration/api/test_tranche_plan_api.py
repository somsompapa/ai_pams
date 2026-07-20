"""POST /api/tranche-plans* 통합 테스트 (buy_rules.md B-2 분할매수 추적)."""

from pathlib import Path

from fastapi.testclient import TestClient

from pams.interfaces.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path))


def _score(total: str, items: list[dict[str, str]]) -> dict[str, object]:
    return {"total_score": total, "categories": [{"items": items}]}


_BASELINE = _score(
    "85",
    [
        {"metric": "ROE", "value": "0.18", "score": "10"},
        {"metric": "EPS 3Y CAGR", "value": "0.08", "score": "8"},
    ],
)

_CREATE_PAYLOAD = {
    "asset_id": "TEST",
    "first_tranche_price": "100",
    "target_quantity": "100",
    "baseline_score": _BASELINE,
}


class TestCreateTranchePlan:
    def test_creates_plan_with_tranches_bought_1(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/api/tranche-plans", json=_CREATE_PAYLOAD)
        assert response.status_code == 200
        body = response.json()
        assert body["asset_id"] == "TEST"
        assert body["tranches_bought"] == 1
        assert body["baseline_total_score"] == "85"

    def test_invalid_price_returns_400(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post(
            "/api/tranche-plans", json={**_CREATE_PAYLOAD, "first_tranche_price": "not-a-number"}
        )
        assert response.status_code == 400

    def test_leaves_audit_event(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        client.post("/api/tranche-plans", json=_CREATE_PAYLOAD)
        audit_log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "tranche_plan.created" in audit_log


class TestListAndDeleteTranchePlans:
    def test_list_returns_created_plans(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        client.post("/api/tranche-plans", json=_CREATE_PAYLOAD)
        response = client.get("/api/tranche-plans")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_delete_removes_plan(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        client.post("/api/tranche-plans", json=_CREATE_PAYLOAD)
        client.delete("/api/tranche-plans/TEST")
        response = client.get("/api/tranche-plans")
        assert response.json() == []


class TestAdvanceTranchePlan:
    def test_advance_increments_tranches_bought(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        client.post("/api/tranche-plans", json=_CREATE_PAYLOAD)
        response = client.post("/api/tranche-plans/TEST/advance")
        assert response.status_code == 200
        assert response.json()["tranches_bought"] == 2

    def test_advance_missing_plan_returns_404(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/api/tranche-plans/NOPE/advance")
        assert response.status_code == 404

    def test_advance_past_third_tranche_returns_400(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        client.post("/api/tranche-plans", json=_CREATE_PAYLOAD)
        client.post("/api/tranche-plans/TEST/advance")
        client.post("/api/tranche-plans/TEST/advance")
        response = client.post("/api/tranche-plans/TEST/advance")
        assert response.status_code == 400


class TestEvaluateTranchePlan:
    def test_price_trigger_not_met_yet(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        client.post("/api/tranche-plans", json=_CREATE_PAYLOAD)
        response = client.post(
            "/api/tranche-plans/TEST/evaluate",
            json={"current_price": "95", "current_score": _BASELINE},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["next_tranche"] == 2
        assert body["price_trigger_met"] is False
        assert body["recommended_amount_fraction"] is None

    def test_price_trigger_met_recommends_second_tranche(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        client.post("/api/tranche-plans", json=_CREATE_PAYLOAD)
        response = client.post(
            "/api/tranche-plans/TEST/evaluate",
            json={"current_price": "90", "current_score": _BASELINE},
        )
        body = response.json()
        assert body["price_trigger_met"] is True
        assert body["recommended_amount_fraction"] == "0.30"

    def test_real_logic_break_halts_recommendation(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        client.post("/api/tranche-plans", json=_CREATE_PAYLOAD)
        degraded = _score(
            "70",
            [
                {"metric": "ROE", "value": "0", "score": "0"},  # 10점 → 0점, 실질 하락
                {"metric": "EPS 3Y CAGR", "value": "0.08", "score": "8"},
            ],
        )
        response = client.post(
            "/api/tranche-plans/TEST/evaluate",
            json={"current_price": "90", "current_score": degraded},
        )
        body = response.json()
        assert body["logic_broken"] is True
        assert body["recommended_amount_fraction"] is None

    def test_data_gap_does_not_halt_recommendation(self, tmp_path: Path) -> None:
        """v1.6.1: baseline엔 실값이었는데 현재 '데이터 누락'(value="—")으로 바뀐
        항목의 하락분은 실질 논리훼손으로 세지 않는다."""
        client = _client(tmp_path)
        client.post("/api/tranche-plans", json=_CREATE_PAYLOAD)
        gapped = _score(
            "75",
            [
                {"metric": "ROE", "value": "—", "score": "0"},  # 데이터 누락으로 전환
                {"metric": "EPS 3Y CAGR", "value": "0.08", "score": "8"},
            ],
        )
        response = client.post(
            "/api/tranche-plans/TEST/evaluate",
            json={"current_price": "90", "current_score": gapped},
        )
        body = response.json()
        assert body["data_gap_only"] is True
        assert body["logic_broken"] is False
        assert body["recommended_amount_fraction"] is None

    def test_evaluate_missing_plan_returns_404(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post(
            "/api/tranche-plans/NOPE/evaluate",
            json={"current_price": "90", "current_score": _BASELINE},
        )
        assert response.status_code == 404

    def test_leaves_audit_event(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        client.post("/api/tranche-plans", json=_CREATE_PAYLOAD)
        client.post(
            "/api/tranche-plans/TEST/evaluate",
            json={"current_price": "90", "current_score": _BASELINE},
        )
        audit_log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "tranche_plan.evaluated" in audit_log
