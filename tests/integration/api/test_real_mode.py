"""실데이터 모드(wiring + CLI) 통합 테스트.

실제 config/를 복사하고 data/ 파일을 채운 임시 프로젝트로
'거래 CSV → 스냅샷 적재(CLI 유스케이스) → 대시보드' 전체 흐름을 검증한다.
"""

import shutil
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pams.interfaces.api.app import create_app
from pams.interfaces.wiring import (
    RealDataError,
    real_base_currency,
    real_dashboard_service,
    real_valuation_recorder,
)
from pams.shared_kernel.domain import Currency

REPO_ROOT = Path(__file__).resolve().parents[3]
AS_OF = date(2026, 7, 10)

TRANSACTIONS = (
    "transaction_id,type,trade_date,asset_id,quantity,price,amount,fee,tax,currency,note\n"
    """t1,deposit,2026-01-02,,,,20000000,0,0,KRW,초기 입금
t2,buy,2026-01-05,KRX:005930,100,70000,,1050,0,KRW,
t3,buy,2026-02-03,KRX:114260,20,100000,,600,0,KRW,
"""
)

PRICES = """asset_id,price_date,close,currency
KRX:005930,2026-07-08,74000,KRW
KRX:005930,2026-07-09,74500,KRW
KRX:005930,2026-07-10,75000,KRW
KRX:114260,2026-07-08,101000,KRW
KRX:114260,2026-07-09,101000,KRW
KRX:114260,2026-07-10,101000,KRW
"""


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    shutil.copytree(REPO_ROOT / "config", tmp_path / "config")
    data = tmp_path / "data"
    data.mkdir()
    (data / "transactions.csv").write_text(TRANSACTIONS, encoding="utf-8")
    (data / "prices.csv").write_text(PRICES, encoding="utf-8")
    (data / "fx.csv").write_text("base,quote,rate_date,rate\n", encoding="utf-8")
    (data / "market.yaml").write_text('vix: "24.5"\n', encoding="utf-8")
    return tmp_path


class TestSnapshotBackfill:
    def test_backfill_three_days_then_dashboard(self, project_root: Path) -> None:
        base = real_base_currency(project_root)
        assert base is Currency.KRW

        recorder = real_valuation_recorder(project_root)
        for day in (date(2026, 7, 8), date(2026, 7, 9), AS_OF):
            point = recorder.execute(as_of=day, base_currency=base)
            assert point.value > 0

        service = real_dashboard_service(project_root)
        client = TestClient(create_app(service, as_of_provider=lambda: AS_OF))
        data = client.get("/api/dashboard").json()
        # 총자산 = 삼성 100×75,000 + 국고채 20×101,000 + 예수금
        #        = 7,500,000 + 2,020,000 + (20,000,000-7,001,050-2,000,600)
        assert data["summary"]["total_value"] == "20,518,350 KRW"
        assert data["base_currency"] == "KRW"
        # 벤치마크 파일이 없으므로 비교 지표는 없다
        assert data["performance"]["benchmark_cumulative"] is None

    def test_insufficient_history_gives_actionable_error(self, project_root: Path) -> None:
        with pytest.raises(RealDataError, match="snapshot"):
            real_dashboard_service(project_root)

    def test_missing_market_metrics_gives_actionable_error(self, project_root: Path) -> None:
        (project_root / "data" / "market.yaml").unlink()
        recorder = real_valuation_recorder(project_root)
        for day in (date(2026, 7, 8), date(2026, 7, 9), AS_OF):
            recorder.execute(as_of=day, base_currency=Currency.KRW)
        with pytest.raises(RealDataError, match="market.yaml"):
            real_dashboard_service(project_root)

    def test_benchmark_file_enables_comparison(self, project_root: Path) -> None:
        (project_root / "data" / "benchmark.csv").write_text(
            "bench_date,value\n2026-07-08,2650\n2026-07-09,2660\n2026-07-10,2670\n",
            encoding="utf-8",
        )
        recorder = real_valuation_recorder(project_root)
        for day in (date(2026, 7, 8), date(2026, 7, 9), AS_OF):
            recorder.execute(as_of=day, base_currency=Currency.KRW)
        service = real_dashboard_service(project_root)
        data = service.build(as_of=AS_OF, base_currency=Currency.KRW)
        assert data["performance"]["benchmark_cumulative"] is not None


class TestTransactionEntry:
    def _client(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("PAMS_MODE", "real")
        recorder = real_valuation_recorder(project_root)
        for day in (date(2026, 7, 8), date(2026, 7, 9), AS_OF):
            recorder.execute(as_of=day, base_currency=Currency.KRW)
        service = real_dashboard_service(project_root)
        return TestClient(
            create_app(service, data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )

    def test_post_transaction_appends_and_reflects(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.post(
            "/api/transactions",
            json={
                "type": "sell",
                "currency": "KRW",
                "asset_id": "KRX:005930",
                "quantity": "30",
                "price": "82000",
                "note": "일부 매도",
            },
        )
        assert response.status_code == 201
        # 파일에 실제로 append 되었는가
        csv_text = (project_root / "data" / "transactions.csv").read_text(encoding="utf-8")
        assert "sell" in csv_text and "82000" in csv_text
        # 재조회 시 보유수량이 100 → 70주로 반영된다
        service = real_dashboard_service(project_root)
        data = service.build(as_of=AS_OF, base_currency=Currency.KRW)
        samsung = next(s for s in data["stocks"] if s["asset_id"] == "KRX:005930")
        assert samsung["quantity"] == "70.0000"

    def test_invalid_transaction_rejected(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        # 트레이드인데 price 누락 → 400
        response = client.post(
            "/api/transactions",
            json={"type": "buy", "currency": "KRW", "asset_id": "KRX:005930", "quantity": "1"},
        )
        assert response.status_code == 400

    def test_demo_mode_blocks_entry(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PAMS_MODE", "demo")
        client = TestClient(
            create_app(data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )
        response = client.post(
            "/api/transactions",
            json={"type": "deposit", "currency": "KRW", "amount": "1000"},
        )
        assert response.status_code == 400


class TestTransactionListEditDelete:
    def _client(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("PAMS_MODE", "real")
        recorder = real_valuation_recorder(project_root)
        for day in (date(2026, 7, 8), date(2026, 7, 9), AS_OF):
            recorder.execute(as_of=day, base_currency=Currency.KRW)
        service = real_dashboard_service(project_root)
        return TestClient(
            create_app(service, data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )

    def test_list_transactions_returns_all(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.get("/api/transactions")
        assert response.status_code == 200
        ids = {t["transaction_id"] for t in response.json()["transactions"]}
        assert ids == {"t1", "t2", "t3"}

    def test_edit_transaction_updates_row(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.put(
            "/api/transactions/t2",
            json={
                "type": "buy",
                "currency": "KRW",
                "asset_id": "KRX:005930",
                "quantity": "120",
                "price": "70000",
                "note": "수량 정정",
            },
        )
        assert response.status_code == 200
        service = real_dashboard_service(project_root)
        data = service.build(as_of=AS_OF, base_currency=Currency.KRW)
        samsung = next(s for s in data["stocks"] if s["asset_id"] == "KRX:005930")
        assert samsung["quantity"] == "120.0000"

    def test_edit_unknown_transaction_rejected(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.put(
            "/api/transactions/nope",
            json={"type": "deposit", "currency": "KRW", "amount": "1000"},
        )
        assert response.status_code == 400

    def test_delete_transaction_removes_row(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.delete("/api/transactions/t3")
        assert response.status_code == 204
        csv_text = (project_root / "data" / "transactions.csv").read_text(encoding="utf-8")
        assert "t3" not in csv_text

    def test_demo_mode_blocks_list_edit_delete(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PAMS_MODE", "demo")
        client = TestClient(
            create_app(data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )
        assert client.get("/api/transactions").status_code == 400
        assert client.delete("/api/transactions/t1").status_code == 400


class TestReconcile:
    def _client(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("PAMS_MODE", "real")
        recorder = real_valuation_recorder(project_root)
        for day in (date(2026, 7, 8), date(2026, 7, 9), AS_OF):
            recorder.execute(as_of=day, base_currency=Currency.KRW)
        service = real_dashboard_service(project_root)
        return TestClient(
            create_app(service, data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )

    def test_reconcile_cash_creates_deposit_for_shortfall(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        # 계산상 예수금 10,998,350 (20,000,000 - 7,001,050 - 2,000,600)
        response = client.post(
            "/api/reconcile/cash",
            json={"currency": "KRW", "target_balance": "11998350", "note": "통장 확인"},
        )
        assert response.status_code == 201
        assert response.json()["diff"] == "1000000"
        csv_text = (project_root / "data" / "transactions.csv").read_text(encoding="utf-8")
        assert "deposit" in csv_text and "통장 확인" in csv_text

    def test_reconcile_cash_creates_withdrawal_for_excess(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.post(
            "/api/reconcile/cash", json={"currency": "KRW", "target_balance": "9998350"}
        )
        assert response.status_code == 201
        assert response.json()["diff"] == "-1000000"

    def test_reconcile_cash_noop_when_matching(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.post(
            "/api/reconcile/cash", json={"currency": "KRW", "target_balance": "10998350"}
        )
        assert response.status_code == 201
        assert response.json() == {"transaction_id": None, "diff": "0"}

    def test_reconcile_holding_creates_buy_for_shortfall(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.post(
            "/api/reconcile/holding", json={"asset_id": "KRX:005930", "target_quantity": "110"}
        )
        assert response.status_code == 201
        assert response.json()["diff"] == "10"
        service = real_dashboard_service(project_root)
        data = service.build(as_of=AS_OF, base_currency=Currency.KRW)
        samsung = next(s for s in data["stocks"] if s["asset_id"] == "KRX:005930")
        assert samsung["quantity"] == "110.0000"

    def test_reconcile_holding_creates_sell_for_excess(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.post(
            "/api/reconcile/holding", json={"asset_id": "KRX:005930", "target_quantity": "90"}
        )
        assert response.status_code == 201
        assert response.json()["diff"] == "-10"

    def test_reconcile_holding_without_price_data_rejected(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.post(
            "/api/reconcile/holding", json={"asset_id": "KRX:999999", "target_quantity": "5"}
        )
        assert response.status_code == 400

    def test_demo_mode_blocks_reconcile(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PAMS_MODE", "demo")
        client = TestClient(
            create_app(data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )
        response = client.post(
            "/api/reconcile/cash", json={"currency": "KRW", "target_balance": "1"}
        )
        assert response.status_code == 400


class TestAssetAndTriggerEntry:
    def _client(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("PAMS_MODE", "real")
        recorder = real_valuation_recorder(project_root)
        for day in (date(2026, 7, 8), date(2026, 7, 9), AS_OF):
            recorder.execute(as_of=day, base_currency=Currency.KRW)
        service = real_dashboard_service(project_root)
        return TestClient(
            create_app(service, data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )

    def test_register_new_asset_then_trade_it(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        resp = client.post(
            "/api/assets",
            json={
                "asset_id": "NASDAQ:NVDA",
                "name": "엔비디아",
                "asset_class": "us_stock",
                "currency": "USD",
                "country": "US",
                "yahoo_symbol": "NVDA",
            },
        )
        assert resp.status_code == 201
        # 자산 파일과 심볼 파일에 반영
        assets_yaml = (project_root / "config" / "assets" / "default.yaml").read_text("utf-8")
        assert "NASDAQ:NVDA" in assets_yaml
        symbols_yaml = (project_root / "config" / "market" / "symbols.yaml").read_text("utf-8")
        assert "NASDAQ:NVDA" in symbols_yaml and "NVDA" in symbols_yaml

    def test_duplicate_asset_rejected(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        resp = client.post(
            "/api/assets",
            json={
                "asset_id": "KRX:005930",
                "name": "삼성전자",
                "asset_class": "domestic_stock",
                "currency": "KRW",
                "country": "KR",
            },
        )
        assert resp.status_code == 400

    def test_save_trigger_then_reflected_in_stocks(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        resp = client.post(
            "/api/triggers",
            json={
                "asset_id": "KRX:005930",
                "currency": "KRW",
                "buy_at": "70000",
                "take_profit_at": "90000",
                "stop_loss_at": "60000",
            },
        )
        assert resp.status_code == 201
        service = real_dashboard_service(project_root)
        data = service.build(as_of=AS_OF, base_currency=Currency.KRW)
        samsung = next(s for s in data["stocks"] if s["asset_id"] == "KRX:005930")
        assert samsung["buy_trigger"] == "70,000 KRW"
        assert samsung["take_profit"] == "90,000 KRW"
        assert samsung["stop_loss"] == "60,000 KRW"

    def test_invalid_trigger_rejected(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        # 매수선이 익절선보다 높으면 → 400
        resp = client.post(
            "/api/triggers",
            json={
                "asset_id": "KRX:005930",
                "currency": "KRW",
                "buy_at": "90000",
                "take_profit_at": "70000",
            },
        )
        assert resp.status_code == 400


class TestBulkTriggers:
    def _client(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("PAMS_MODE", "real")
        recorder = real_valuation_recorder(project_root)
        for day in (date(2026, 7, 8), date(2026, 7, 9), AS_OF):
            recorder.execute(as_of=day, base_currency=Currency.KRW)
        service = real_dashboard_service(project_root)
        return TestClient(
            create_app(service, data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )

    def test_bulk_apply_computes_and_saves_for_equities_only(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.post(
            "/api/triggers/bulk",
            json={
                "stop_loss_percent": "20",
                "take_profit_percent": "20",
                "buy_dip_percent": "20",
            },
        )
        assert response.status_code == 201
        body = response.json()
        applied_ids = {a["asset_id"] for a in body["applied"]}
        assert applied_ids == {"KRX:005930"}  # 채권(KRX:114260)은 주식이 아니라 제외
        assert body["skipped"] == []
        yaml_text = (project_root / "config" / "triggers" / "default.yaml").read_text("utf-8")
        assert "KRX:005930" in yaml_text

    def test_bulk_apply_skips_when_order_invalid(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        # 매수%를 극단적으로 크게 주면 매수선이 손절선보다 낮아져 순서 검증에 걸린다.
        response = client.post(
            "/api/triggers/bulk",
            json={
                "stop_loss_percent": "1",
                "take_profit_percent": "20",
                "buy_dip_percent": "50",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["applied"] == []
        assert body["skipped"][0]["asset_id"] == "KRX:005930"

    def test_demo_mode_blocks_bulk_triggers(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PAMS_MODE", "demo")
        client = TestClient(
            create_app(data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )
        response = client.post(
            "/api/triggers/bulk",
            json={
                "stop_loss_percent": "20",
                "take_profit_percent": "20",
                "buy_dip_percent": "20",
            },
        )
        assert response.status_code == 400


class TestAssetListEditDelete:
    def _client(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("PAMS_MODE", "real")
        recorder = real_valuation_recorder(project_root)
        for day in (date(2026, 7, 8), date(2026, 7, 9), AS_OF):
            recorder.execute(as_of=day, base_currency=Currency.KRW)
        service = real_dashboard_service(project_root)
        return TestClient(
            create_app(service, data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )

    def test_list_assets_returns_all(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.get("/api/assets")
        assert response.status_code == 200
        ids = {a["asset_id"] for a in response.json()["assets"]}
        assert {"KRX:005930", "KRX:114260"} <= ids

    def test_edit_asset_updates_entry(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.put(
            "/api/assets/KRX:069500",
            json={
                "asset_id": "KRX:069500",
                "name": "KODEX 200 (수정됨)",
                "asset_class": "etf",
                "currency": "KRW",
                "country": "KR",
            },
        )
        assert response.status_code == 200
        assets_yaml = (project_root / "config" / "assets" / "default.yaml").read_text("utf-8")
        assert "KODEX 200 (수정됨)" in assets_yaml

    def test_edit_unknown_asset_rejected(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.put(
            "/api/assets/NOPE",
            json={
                "asset_id": "NOPE",
                "name": "X",
                "asset_class": "etf",
                "currency": "KRW",
                "country": "KR",
            },
        )
        assert response.status_code == 400

    def test_delete_asset_without_transactions_succeeds(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.delete("/api/assets/KRX:069500")
        assert response.status_code == 204
        assets_yaml = (project_root / "config" / "assets" / "default.yaml").read_text("utf-8")
        assert "KRX:069500" not in assets_yaml

    def test_delete_asset_with_transactions_rejected(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        # KRX:005930은 거래내역(t2)이 있어 삭제 불가
        response = client.delete("/api/assets/KRX:005930")
        assert response.status_code == 400
        assets_yaml = (project_root / "config" / "assets" / "default.yaml").read_text("utf-8")
        assert "KRX:005930" in assets_yaml

    def test_demo_mode_blocks_asset_endpoints(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PAMS_MODE", "demo")
        client = TestClient(
            create_app(data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )
        assert client.get("/api/assets").status_code == 400
        assert client.delete("/api/assets/KRX:069500").status_code == 400


class TestTriggerDelete:
    def _client(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("PAMS_MODE", "real")
        recorder = real_valuation_recorder(project_root)
        for day in (date(2026, 7, 8), date(2026, 7, 9), AS_OF):
            recorder.execute(as_of=day, base_currency=Currency.KRW)
        service = real_dashboard_service(project_root)
        return TestClient(
            create_app(service, data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )

    def test_delete_removes_saved_trigger(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        client.post(
            "/api/triggers",
            json={"asset_id": "KRX:005930", "currency": "KRW", "buy_at": "70000"},
        )
        response = client.delete("/api/triggers/KRX:005930")
        assert response.status_code == 204
        service = real_dashboard_service(project_root)
        data = service.build(as_of=AS_OF, base_currency=Currency.KRW)
        samsung = next(s for s in data["stocks"] if s["asset_id"] == "KRX:005930")
        assert samsung["signal"] == "none"

    def test_delete_unknown_trigger_rejected(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.delete("/api/triggers/KRX:114260")
        assert response.status_code == 400

    def test_demo_mode_blocks_trigger_delete(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PAMS_MODE", "demo")
        client = TestClient(
            create_app(data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )
        assert client.delete("/api/triggers/KRX:005930").status_code == 400


class TestStockTargets:
    def _client(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("PAMS_MODE", "real")
        recorder = real_valuation_recorder(project_root)
        for day in (date(2026, 7, 8), date(2026, 7, 9), AS_OF):
            recorder.execute(as_of=day, base_currency=Currency.KRW)
        service = real_dashboard_service(project_root)
        return TestClient(
            create_app(service, data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )

    def test_list_returns_configured_targets(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.get("/api/stock-targets")
        assert response.status_code == 200
        ids = {t["asset_id"] for t in response.json()["targets"]}
        assert "KRX:005930" in ids

    def test_save_upserts_target(self, project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.post(
            "/api/stock-targets",
            json={
                "asset_id": "KRX:114260",
                "target_percent": "30",
                "buy_band": "5",
                "sell_band": "5",
            },
        )
        assert response.status_code == 201
        yaml_text = (project_root / "config" / "stock_targets" / "default.yaml").read_text("utf-8")
        assert "KRX:114260" in yaml_text

    def test_save_rejects_invalid_percent(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.post(
            "/api/stock-targets",
            json={
                "asset_id": "KRX:114260",
                "target_percent": "not-a-number",
                "buy_band": "5",
                "sell_band": "5",
            },
        )
        assert response.status_code == 400

    def test_delete_removes_target(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.delete("/api/stock-targets/KRX:005930")
        assert response.status_code == 204
        yaml_text = (project_root / "config" / "stock_targets" / "default.yaml").read_text("utf-8")
        assert "KRX:005930" not in yaml_text

    def test_delete_unknown_target_rejected(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(project_root, monkeypatch)
        response = client.delete("/api/stock-targets/NOPE")
        assert response.status_code == 400

    def test_demo_mode_blocks_stock_targets(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PAMS_MODE", "demo")
        client = TestClient(
            create_app(data_dir=project_root / "data", as_of_provider=lambda: AS_OF)
        )
        assert client.get("/api/stock-targets").status_code == 400


class TestCli:
    def test_snapshot_command(self, project_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from pams.interfaces.cli.__main__ import main

        exit_code = main(["snapshot", "--date", "2026-07-10", "--root", str(project_root)])
        assert exit_code == 0
        assert "적재 완료" in capsys.readouterr().out
        assert (project_root / "data" / "value_history.jsonl").exists()

    def test_snapshot_failure_returns_nonzero(
        self, project_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from pams.interfaces.cli.__main__ import main

        (project_root / "data" / "transactions.csv").unlink()
        exit_code = main(["snapshot", "--date", "2026-07-10", "--root", str(project_root)])
        assert exit_code == 1
        assert "실패" in capsys.readouterr().err
