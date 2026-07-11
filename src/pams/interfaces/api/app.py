"""FastAPI 앱 팩토리.

기본값은 데모 데이터 소스로 조립된다. 실계좌/실시세 어댑터가 준비되면
create_app()에 다른 DashboardService를 주입하면 된다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse

from pams.interfaces.api import demo
from pams.interfaces.api.service import DashboardService
from pams.shared_kernel.domain import Currency

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_STATIC_DIR = Path(__file__).resolve().parent / "static"


def default_dashboard_service() -> DashboardService:
    return DashboardService(
        config_dir=_PROJECT_ROOT / "config",
        transactions=demo.DemoTransactionRepository(),
        assets=demo.DemoAssetCatalog(),
        prices=demo.DemoPriceLookup(),
        fx=demo.DemoFxLookup(),
        portfolio_values=demo.demo_value_series(),
        benchmark_values=demo.demo_benchmark_series(),
        performance_history=demo.demo_performance_history(),
        benchmark_history=demo.demo_benchmark_history(),
        market_metrics={"vix": demo.DEMO_VIX},
    )


def create_app(service: DashboardService | None = None) -> FastAPI:
    dashboard_service = service if service is not None else default_dashboard_service()
    app = FastAPI(title="PAMS", version="0.1.0")

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        return dashboard_service.build(as_of=demo.AS_OF, base_currency=Currency.KRW)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "dashboard.html", media_type="text/html")

    return app
