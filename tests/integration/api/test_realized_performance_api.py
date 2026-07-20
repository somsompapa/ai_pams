"""GET /api/realized-performance 통합 테스트."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pams.interfaces.api.app import create_app

_TRANSACTIONS_CSV = (
    "transaction_id,type,trade_date,asset_id,quantity,price,amount,fee,tax,currency,note\n"
    "t1,buy,2023-01-01,KRX:005930,10,100,,0,0,KRW,\n"
    "t2,sell,2024-01-01,KRX:005930,10,150,,0,0,KRW,\n"
)


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    (tmp_path / "transactions.csv").write_text(_TRANSACTIONS_CSV, encoding="utf-8")
    return tmp_path


class TestRealizedPerformanceApi:
    def test_requires_real_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PAMS_MODE", "demo")
        client = TestClient(create_app(data_dir=tmp_path))
        response = client.get("/api/realized-performance")
        assert response.status_code == 400

    def test_computes_fifo_realized_performance(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 데모 모드로 앱을 만들어(real_dashboard_service의 실제 프로젝트 데이터 요구를
        # 피한다 — data_dir은 별개로 transactions.csv 경로만 결정) 요청 직전에만
        # PAMS_MODE를 real로 바꾼다(_require_real_mode는 요청마다 os.environ을 다시 읽는다).
        client = TestClient(create_app(data_dir=data_dir))
        monkeypatch.setenv("PAMS_MODE", "real")
        response = client.get("/api/realized-performance")
        assert response.status_code == 200
        body = response.json()

        assert body["n_open_lots"] == 0
        assert len(body["by_currency"]) == 1
        krw = body["by_currency"][0]
        assert krw["currency"] == "KRW"
        assert krw["n_closed_lots"] == 1
        assert krw["total_cost"] == "1000"
        assert krw["total_realized_pnl"] == "500"
        assert float(krw["realized_return_pct"]) == 50
        assert krw["capital_weighted_cagr"] is not None
        assert abs(float(krw["capital_weighted_cagr"]) - 0.5) < 0.001

    def test_no_transactions_yields_empty_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "transactions.csv").write_text(
            "transaction_id,type,trade_date,asset_id,quantity,price,amount,fee,tax,currency,note\n",
            encoding="utf-8",
        )
        client = TestClient(create_app(data_dir=tmp_path))
        monkeypatch.setenv("PAMS_MODE", "real")
        response = client.get("/api/realized-performance")
        assert response.status_code == 200
        body = response.json()
        assert body["by_currency"] == []
        assert body["n_open_lots"] == 0
