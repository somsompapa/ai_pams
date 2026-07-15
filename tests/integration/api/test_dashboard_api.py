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
            "holdings",
            "targets",
            "risk",
            "alerts",
            "rebalancing",
            "performance",
        }
        assert data["base_currency"] == "KRW"
        assert data["summary"]["total_value"].endswith("KRW")

    def test_asset_class_weights_include_amount(self, client: TestClient) -> None:
        data = client.get("/api/dashboard").json()
        for entry in data["weights"]["asset_class"]:
            assert entry["value"].endswith("KRW")
            assert "percent" in entry

    def test_today_actions_present(self, client: TestClient) -> None:
        data = client.get("/api/dashboard").json()
        assert "today_actions" in data
        actions = data["today_actions"]
        # 데모: 리밸런싱 밴드 이탈이 있어 최소 1건 이상
        assert isinstance(actions, list)
        if actions:
            a = actions[0]
            assert set(a) >= {
                "source",
                "asset",
                "direction",
                "direction_label",
                "reason",
            }
            assert a["direction"] in {"buy", "sell"}
            assert a["source"] in {"price_trigger", "rebalancing"}

    def test_today_actions_excludes_dca(self, client: TestClient) -> None:
        """DCA는 정해진 일정이라 '오늘의 액션'에 포함하지 않는다."""
        data = client.get("/api/dashboard").json()
        assert all(a["source"] != "dca" for a in data["today_actions"])

    def test_stock_allocation_section(self, client: TestClient) -> None:
        data = client.get("/api/dashboard").json()
        alloc = data["stock_allocation"]
        assert "configured" in alloc
        assert alloc["sleeve_value"].endswith("KRW")
        assert alloc["rows"]
        sample = alloc["rows"][0]
        assert set(sample) >= {
            "asset_id",
            "name",
            "current_weight",
            "target",
            "buy_trigger",
            "sell_trigger",
            "signal",
            "adjust_amount",
        }
        assert sample["signal"] in {"buy", "sell", "hold"}
        # 데모 주식 종목(삼성전자/애플)만 슬리브에 포함 - 채권/금 등은 제외
        ids = {r["asset_id"] for r in alloc["rows"]}
        assert "KRX:005930" in ids
        assert "KRX:114260" not in ids  # 채권은 주식 슬리브가 아니다

    def test_stocks_expose_sleeve_weight(self, client: TestClient) -> None:
        data = client.get("/api/dashboard").json()
        stocks = data["stocks"]
        assert stocks
        sample = stocks[0]
        assert "weight" in sample and "sleeve_weight" in sample
        # 슬리브 비중은 주식 종목끼리만 합쳐 100%가 되어야 한다
        total = sum(Decimal(s["sleeve_weight"]) for s in stocks)
        assert Decimal("99.9") <= total <= Decimal("100.1")

    def test_stock_sleeve_breakdown(self, client: TestClient) -> None:
        data = client.get("/api/dashboard").json()
        sleeve = data["stock_sleeve"]
        labels = {row["label"] for row in sleeve}
        assert labels == {"주식전체", "국내주식", "해외주식"}
        total_row = next(r for r in sleeve if r["label"] == "주식전체")
        assert total_row["percent"] == "100.00"
        assert total_row["value"].endswith("KRW")

    def test_holdings_expose_per_position_detail(self, client: TestClient) -> None:
        data = client.get("/api/dashboard").json()
        holdings = data["holdings"]
        assert holdings
        sample = holdings[0]
        assert set(sample) >= {
            "asset_id",
            "name",
            "asset_class",
            "quantity",
            "avg_price",
            "current_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_percent",
            "weight",
        }
        # 데모 보유 종목(삼성전자)이 종목 목록에 있어야 한다
        assert any(h["asset_id"] == "KRX:005930" for h in holdings)

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
