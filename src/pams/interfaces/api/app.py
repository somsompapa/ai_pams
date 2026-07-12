"""FastAPI 앱 팩토리.

기본값은 데모 데이터 소스로 조립된다. 실계좌/실시세 어댑터가 준비되면
create_app()에 다른 DashboardService를 주입하면 된다.

AI 해설은 TextCompletion 구현이 있어야 동작한다:
- 테스트/개발: create_app(completion=...) 주입
- 운영: 환경변수 ANTHROPIC_API_KEY(필수), PAMS_AI_MODEL(선택) 설정
"""

from __future__ import annotations

import base64
import os
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pams.ai_analysis.application import GenerateAnalysis
from pams.ai_analysis.domain import AnalysisKind, TextCompletion
from pams.ai_analysis.infrastructure import AnthropicTextCompletion
from pams.audit.application import RecordAuditEvent
from pams.audit.domain import AuditEvent
from pams.audit.infrastructure import JsonlAuditTrail
from pams.interfaces.api import demo
from pams.interfaces.api.service import DashboardService
from pams.journal.application import ListJournalEntries, RecordJournalEntry
from pams.journal.domain import JournalEntry
from pams.journal.infrastructure import JsonlJournalRepository
from pams.shared_kernel.domain import Currency, DomainError

_PROJECT_ROOT = Path(os.environ.get("PAMS_ROOT") or Path(__file__).resolve().parents[4])
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_DEFAULT_AI_MODEL = "claude-sonnet-5"


class JournalRequest(BaseModel):
    title: str
    what: str
    why: str
    rule_basis: str = ""
    ai_draft: str | None = None


class AnalysisRequest(BaseModel):
    kind: Literal["summary", "risk", "market", "journal_draft"]
    note: str | None = None


def _is_real_mode() -> bool:
    return os.environ.get("PAMS_MODE", "demo").strip().lower() == "real"


def default_dashboard_service() -> DashboardService:
    """PAMS_MODE=real이면 data/·config/ 파일 기반, 아니면 데모 데이터."""
    if _is_real_mode():
        from pams.interfaces.wiring import real_dashboard_service

        return real_dashboard_service(_PROJECT_ROOT)
    return DashboardService(
        config_dir=_PROJECT_ROOT / "config",
        transactions=demo.DemoTransactionRepository(),
        assets=demo.DemoAssetCatalog(),
        prices=demo.DemoPriceLookup(),
        fx=demo.DemoFxLookup(),
        portfolio_values=demo.demo_value_series(),
        performance_history=demo.demo_performance_history(),
        market_metrics={"vix": demo.DEMO_VIX},
        benchmark_values=demo.demo_benchmark_series(),
        benchmark_history=demo.demo_benchmark_history(),
    )


def _default_as_of() -> date:
    """데모 모드는 데모 기준일에 고정, 실데이터 모드는 오늘."""
    return date.today() if _is_real_mode() else demo.AS_OF


def _completion_from_env() -> TextCompletion | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.environ.get("PAMS_AI_MODEL", "").strip() or _DEFAULT_AI_MODEL
    return AnthropicTextCompletion(api_key=api_key, model=model)


def _facts_from_dashboard(data: dict[str, Any]) -> list[str]:
    """대시보드 데이터(엔진 출력의 표시형)를 AI에 전달할 사실 목록으로 변환한다."""
    summary = data["summary"]
    compliance_status = "준수" if summary["compliant"] else f"위반 {summary['violation_count']}건"
    facts = [
        f"기준일: {data['as_of']}",
        f"총자산: {summary['total_value']}",
        f"평가손익: {summary['unrealized_pnl']}",
        f"누적수익률(TWR): {summary['cumulative_twr']}",
        f"IPS 준수 여부: {compliance_status}",
    ]
    facts += [
        f"자산군 비중: {entry['label']} {entry['percent']}%"
        for entry in data["weights"]["asset_class"]
    ]
    facts += [f"리스크 지표: {metric['label']} {metric['value']}" for metric in data["risk"]]
    facts += [
        f"발동 규칙[{alert['severity']}]: {alert['rule_id']} - {alert['message']}"
        f" (관측값 {alert['observed']})"
        for alert in data["alerts"]
    ]
    rebalancing = data["rebalancing"]
    if rebalancing["needed"]:
        facts.append(
            f"리밸런싱 제안: 총 매도 {rebalancing['total_sell']}, "
            f"총 매수 {rebalancing['total_buy']}, 예상 비용 {rebalancing['total_cost']}"
        )
        facts += [
            f"리밸런싱 액션: {action['asset_class']} {action['direction']} {action['amount']}"
            f" (현재 {action['current']}% → 목표 {action['target']}%)"
            for action in rebalancing["actions"]
        ]
    else:
        facts.append("리밸런싱: 모든 자산군이 허용밴드 안에 있어 불필요")
    return facts


def _authorized(header: str | None, password: str) -> bool:
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    _username, _sep, provided = decoded.partition(":")
    return secrets.compare_digest(provided, password)


def create_app(
    service: DashboardService | None = None,
    *,
    data_dir: Path | None = None,
    completion: TextCompletion | None = None,
    as_of_provider: Callable[[], date] | None = None,
    password: str | None = None,
) -> FastAPI:
    dashboard_service = service if service is not None else default_dashboard_service()
    as_of = as_of_provider if as_of_provider is not None else _default_as_of
    access_password = (
        password if password is not None else os.environ.get("PAMS_PASSWORD", "").strip() or None
    )
    storage_dir = data_dir if data_dir is not None else _PROJECT_ROOT / "data"
    journal_repository = JsonlJournalRepository(storage_dir / "journal.jsonl")
    audit_recorder = RecordAuditEvent(trail=JsonlAuditTrail(storage_dir / "audit.jsonl"))
    text_completion = completion if completion is not None else _completion_from_env()

    app = FastAPI(title="PAMS", version="0.1.0")

    if access_password is not None:
        configured_password = access_password

        @app.middleware("http")
        async def basic_auth(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            if request.url.path == "/api/health" or _authorized(
                request.headers.get("Authorization"), configured_password
            ):
                return await call_next(request)
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="PAMS"'})

    @app.exception_handler(DomainError)
    def domain_error_handler(_request: Any, error: DomainError) -> Any:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": str(error)})

    def record_audit(actor: str, action: str, detail: str, reason: str) -> None:
        audit_recorder.execute(
            event=AuditEvent(
                event_id=f"evt-{uuid.uuid4().hex}",
                occurred_at=datetime.now(UTC),
                actor=actor,
                action=action,
                detail=detail,
                reason=reason,
            )
        )

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        return dashboard_service.build(as_of=as_of(), base_currency=Currency.KRW)

    @app.get("/api/audit")
    def list_audit(limit: int = 50) -> dict[str, Any]:
        from pams.audit.application import ListAuditEvents

        events = ListAuditEvents(trail=audit_recorder.trail).execute()
        recent = list(reversed(events))[: max(1, min(limit, 500))]
        return {
            "events": [
                {
                    "occurred_at": e.occurred_at.isoformat(),
                    "actor": e.actor,
                    "action": e.action,
                    "detail": e.detail,
                    "reason": e.reason,
                }
                for e in recent
            ]
        }

    @app.get("/api/journal")
    def list_journal() -> dict[str, Any]:
        entries = ListJournalEntries(repository=journal_repository).execute()
        return {
            "entries": [
                {
                    "entry_id": e.entry_id,
                    "entry_date": e.entry_date.isoformat(),
                    "title": e.title,
                    "what": e.what,
                    "why": e.why,
                    "rule_basis": e.rule_basis,
                    "ai_draft": e.ai_draft,
                }
                for e in entries
            ]
        }

    @app.post("/api/journal", status_code=201)
    def record_journal(request: JournalRequest) -> dict[str, Any]:
        today = as_of()
        entry = JournalEntry(
            entry_id=f"{today.isoformat()}-{uuid.uuid4().hex[:8]}",
            entry_date=today,
            title=request.title,
            what=request.what,
            why=request.why,
            rule_basis=request.rule_basis,
            ai_draft=request.ai_draft,
        )
        RecordJournalEntry(repository=journal_repository).execute(entry=entry)
        record_audit(
            actor="user",
            action="journal.recorded",
            detail=f"투자일지 {entry.entry_id} 기록: {entry.title}",
            reason=entry.why,
        )
        return {
            "entry_id": entry.entry_id,
            "entry_date": entry.entry_date.isoformat(),
            "title": entry.title,
            "what": entry.what,
            "why": entry.why,
            "rule_basis": entry.rule_basis,
            "ai_draft": entry.ai_draft,
        }

    @app.post("/api/analysis")
    def generate_analysis(request: AnalysisRequest) -> dict[str, str]:
        if text_completion is None:
            raise HTTPException(
                status_code=503,
                detail="AI 해설을 사용할 수 없다 - ANTHROPIC_API_KEY를 설정하라",
            )
        data = dashboard_service.build(as_of=as_of(), base_currency=Currency.KRW)
        narrative = GenerateAnalysis(completion=text_completion).execute(
            kind=AnalysisKind(request.kind),
            facts=_facts_from_dashboard(data),
            note=request.note,
        )
        record_audit(
            actor="user",
            action="analysis.generated",
            detail=f"AI 해설 생성 ({narrative.kind})",
            reason="사용자 요청",
        )
        return {"kind": narrative.kind.value, "text": narrative.text}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "dashboard.html", media_type="text/html")

    @app.get("/manifest.json", include_in_schema=False)
    def manifest() -> FileResponse:
        return FileResponse(_STATIC_DIR / "manifest.json", media_type="application/manifest+json")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(_STATIC_DIR / "sw.js", media_type="text/javascript")

    @app.get("/static/{filename}", include_in_schema=False)
    def static_file(filename: str) -> FileResponse:
        target = (_STATIC_DIR / filename).resolve()
        if not target.is_file() or target.parent != _STATIC_DIR.resolve():
            raise HTTPException(status_code=404)
        return FileResponse(target)

    return app
