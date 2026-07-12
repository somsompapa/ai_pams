"""대시보드 API 통합 테스트.

데모 데이터 + 실제 config/ 파일로 전체 파이프라인
(거래 → 스냅샷 → 규칙 판정 → 리스크 → 리밸런싱 → 성과 → JSON)을 검증한다.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from pams.interfaces.api.app import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


class TestDashboardApi:
    def test_health(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_index_serves_dashboard_html(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "PAMS 대시보드" in response.text

    def test_dashboard_payload_structure(self, client: TestClient) -> None:
        data = client.get("/api/dashboard").json()
        assert set(data) >= {
            "as_of",
            "base_currency",
            "policy_name",
            "summary",
            "weights",
            "targets",
            "risk",
            "alerts",
            "rebalancing",
            "performance",
        }
        assert data["base_currency"] == "KRW"
        assert data["summary"]["total_value"].endswith("KRW")

    def test_weights_sum_to_100(self, client: TestClient) -> None:
        data = client.get("/api/dashboard").json()
        for group in ("asset_class", "country", "currency"):
            total = sum(Decimal(entry["percent"]) for entry in data["weights"][group])
            assert Decimal("99.9") <= total <= Decimal("100.1"), group

    def test_demo_scenario_triggers_concentration_rule(self, client: TestClient) -> None:
        """데모 포트폴리오는 삼성전자 비중이 20%를 넘어 분산투자 규칙이 발동해야 한다."""
        data = client.get("/api/dashboard").json()
        assert data["summary"]["compliant"] is False
        rule_ids = [alert["rule_id"] for alert in data["alerts"]]
        assert "max-single-position" in rule_ids

    def test_rebalancing_proposal_present(self, client: TestClient) -> None:
        data = client.get("/api/dashboard").json()
        rebalancing = data["rebalancing"]
        assert rebalancing["needed"] is True
        directions = {action["direction"] for action in rebalancing["actions"]}
        assert directions <= {"매도", "매수"}
        assert len(rebalancing["actions"]) >= 1

    def test_targets_cover_policy_asset_classes(self, client: TestClient) -> None:
        data = client.get("/api/dashboard").json()
        labels = {t["label"] for t in data["targets"]}
        assert {"국내주식", "미국주식", "채권", "현금"} <= labels
        for target in data["targets"]:
            assert target["status"] in {"ok", "over", "under"}

    def test_risk_metrics_include_benchmark_relative(self, client: TestClient) -> None:
        data = client.get("/api/dashboard").json()
        names = {metric["name"] for metric in data["risk"]}
        assert {"mdd", "drawdown", "sharpe", "var", "beta", "concentration_hhi"} <= names

    def test_monthly_performance_rows(self, client: TestClient) -> None:
        data = client.get("/api/dashboard").json()
        monthly = data["performance"]["monthly"]
        assert len(monthly) >= 6
        assert all("label" in row and "twr" in row for row in monthly)
