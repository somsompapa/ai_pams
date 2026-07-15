"""FastAPI 앱 팩토리.

기본값은 데모 데이터 소스로 조립된다. 실계좌/실시세 어댑터가 준비되면
create_app()에 다른 DashboardService를 주입하면 된다.

AI 해설은 TextCompletion 구현이 있어야 동작한다:
- 테스트/개발: create_app(completion=...) 주입
- 운영: 환경변수 GEMINI_API_KEY(권장) 또는 ANTHROPIC_API_KEY, PAMS_AI_MODEL(선택) 설정
"""

from __future__ import annotations

import base64
import os
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pams.ai_analysis.application import GenerateAnalysis
from pams.ai_analysis.domain import AnalysisKind, TextCompletion
from pams.ai_analysis.infrastructure import (
    AnalysisProviderError,
    AnthropicTextCompletion,
    GeminiTextCompletion,
)
from pams.asset.infrastructure import (
    AssetConfigError,
    YamlAssetCatalog,
    append_asset,
    delete_asset,
    update_asset,
)
from pams.audit.application import RecordAuditEvent
from pams.audit.domain import AuditEvent
from pams.audit.infrastructure import JsonlAuditTrail
from pams.equity.domain import PriceTrigger, StockTarget, band_trigger
from pams.equity.infrastructure import (
    PriceTriggerConfigError,
    StockTargetConfigError,
    YamlStockTargetLoader,
    delete_price_trigger,
    delete_stock_target,
    save_price_trigger,
    save_stock_target,
)
from pams.interfaces.api import demo
from pams.interfaces.api.service import DashboardService
from pams.journal.application import ListJournalEntries, RecordJournalEntry
from pams.journal.domain import JournalEntry
from pams.journal.infrastructure import JsonlJournalRepository
from pams.market_data.infrastructure import CsvPriceLookup, upsert_fx_rate, upsert_price_symbol
from pams.portfolio.domain import CashLedger, PositionLedger, Transaction, TransactionType
from pams.portfolio.infrastructure import CsvDataError, CsvTransactionRepository
from pams.shared_kernel.domain import (
    Asset,
    AssetClass,
    Currency,
    DomainError,
    Money,
    Percentage,
    Quantity,
)

_PROJECT_ROOT = Path(os.environ.get("PAMS_ROOT") or Path(__file__).resolve().parents[4])
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_DEFAULT_AI_MODEL = "claude-sonnet-5"
_DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"


class JournalRequest(BaseModel):
    title: str
    what: str
    why: str
    rule_basis: str = ""
    ai_draft: str | None = None


class AnalysisRequest(BaseModel):
    kind: Literal["summary", "risk", "market", "journal_draft"]
    note: str | None = None


class TransactionRequest(BaseModel):
    """웹 거래 입력. 숫자는 float 오차를 막기 위해 문자열로 받는다."""

    type: Literal["buy", "sell", "dividend", "interest", "deposit", "withdrawal", "fee", "tax"]
    currency: str
    trade_date: str | None = None
    asset_id: str | None = None
    quantity: str | None = None
    price: str | None = None
    amount: str | None = None
    fee: str | None = None
    tax: str | None = None
    note: str = ""


class AssetRequest(BaseModel):
    """새 종목 등록. Yahoo 심볼을 주면 시세 자동수집에도 추가된다."""

    asset_id: str
    name: str
    asset_class: str
    currency: str
    country: str
    sector: str | None = None
    yahoo_symbol: str | None = None


class TriggerRequest(BaseModel):
    """종목별 매수선/익절선/손절선. 숫자는 문자열로 받는다."""

    asset_id: str
    currency: str
    buy_at: str | None = None
    take_profit_at: str | None = None
    stop_loss_at: str | None = None


class BulkTriggerRequest(BaseModel):
    """평단가/현재가 대비 비율로 보유 종목 전체의 트리거를 일괄 계산·저장한다."""

    stop_loss_percent: str
    take_profit_percent: str
    buy_dip_percent: str


class StockTargetRequest(BaseModel):
    """종목별 목표비중(Tier 2, 주식 슬리브 대비)과 매수/매도 밴드."""

    asset_id: str
    target_percent: str
    buy_band: str
    sell_band: str


class FxRequest(BaseModel):
    """환율 수동 입력(1 base = rate × quote). fetch가 못 받아온 통화쌍을 채운다."""

    base: str
    quote: str
    rate: str
    rate_date: str | None = None


class CashReconcileRequest(BaseModel):
    """실제 현금 잔액에 맞춰 입금/출금 보정 거래를 만든다."""

    currency: str
    target_balance: str
    note: str = ""


class HoldingReconcileRequest(BaseModel):
    """실제 보유수량에 맞춰 매수/매도 보정 거래를 만든다."""

    asset_id: str
    target_quantity: str
    note: str = ""


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
    """환경변수로 AI 해설 공급자를 고른다. Gemini 키가 있으면 Gemini 우선."""
    model = os.environ.get("PAMS_AI_MODEL", "").strip()
    gemini_key = (
        os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
    )
    if gemini_key:
        return GeminiTextCompletion(api_key=gemini_key, model=model or _DEFAULT_GEMINI_MODEL)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        return AnthropicTextCompletion(api_key=anthropic_key, model=model or _DEFAULT_AI_MODEL)
    return None


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

    def _require_real_mode() -> None:
        if not _is_real_mode():
            raise HTTPException(
                status_code=400,
                detail="데모 모드에서는 설정 변경이 비활성이다 (PAMS_MODE=real에서만).",
            )

    def _transaction_repository() -> CsvTransactionRepository:
        return CsvTransactionRepository(storage_dir / "transactions.csv")

    def _build_transaction(transaction_id: str, request: TransactionRequest) -> Transaction:
        try:
            currency = Currency(request.currency)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"알 수 없는 통화: {request.currency}"
            ) from None
        try:
            trade_date = date.fromisoformat(request.trade_date) if request.trade_date else as_of()
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"잘못된 날짜: {request.trade_date}"
            ) from None

        def money(value: str | None) -> Money | None:
            return Money.of(value, currency) if value not in (None, "") else None

        return Transaction(
            transaction_id=transaction_id,
            transaction_type=TransactionType(request.type),
            trade_date=trade_date,
            asset_id=request.asset_id or None,
            quantity=Quantity.of(request.quantity) if request.quantity else None,
            price=money(request.price),
            amount=money(request.amount),
            fee=money(request.fee),
            tax=money(request.tax),
            note=request.note,
        )

    @app.post("/api/transactions", status_code=201)
    def record_transaction(request: TransactionRequest) -> dict[str, Any]:
        if not _is_real_mode():
            raise HTTPException(
                status_code=400,
                detail="데모 모드에서는 거래 입력이 비활성이다 (PAMS_MODE=real에서만 기록).",
            )
        transaction_id = f"{as_of().isoformat()}-{uuid.uuid4().hex[:8]}"
        transaction = _build_transaction(transaction_id, request)
        repository = _transaction_repository()
        try:
            repository.append(transaction)
        except CsvDataError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        record_audit(
            actor="user",
            action="transaction.recorded",
            detail=(
                f"거래 {transaction.transaction_id} 기록: {request.type} {request.asset_id or ''}"
            ),
            reason=request.note or "웹 거래 입력",
        )
        return {"transaction_id": transaction.transaction_id}

    @app.get("/api/transactions")
    def list_transactions() -> dict[str, Any]:
        _require_real_mode()
        rows = _transaction_repository().list_all()
        rows_sorted = sorted(rows, key=lambda t: (t.trade_date, t.transaction_id), reverse=True)

        def field(money: Money | None) -> str:
            return "" if money is None or money.is_zero else str(money.amount)

        return {
            "transactions": [
                {
                    "transaction_id": t.transaction_id,
                    "type": t.transaction_type.value,
                    "trade_date": t.trade_date.isoformat(),
                    "asset_id": t.asset_id or "",
                    "quantity": "" if t.quantity is None else str(t.quantity.value),
                    "price": "" if t.price is None else str(t.price.amount),
                    "amount": "" if t.amount is None else str(t.amount.amount),
                    "fee": field(t.fee),
                    "tax": field(t.tax),
                    "currency": t.currency.value,
                    "note": t.note,
                }
                for t in rows_sorted
            ]
        }

    @app.put("/api/transactions/{transaction_id}")
    def edit_transaction(transaction_id: str, request: TransactionRequest) -> dict[str, Any]:
        _require_real_mode()
        transaction = _build_transaction(transaction_id, request)
        try:
            _transaction_repository().update(transaction_id, transaction)
        except CsvDataError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        record_audit(
            actor="user",
            action="transaction.updated",
            detail=f"거래 {transaction_id} 수정: {request.type} {request.asset_id or ''}",
            reason=request.note or "웹 거래 수정",
        )
        return {"transaction_id": transaction.transaction_id}

    @app.delete("/api/transactions/{transaction_id}", status_code=204)
    def delete_transaction(transaction_id: str) -> Response:
        _require_real_mode()
        try:
            _transaction_repository().delete(transaction_id)
        except CsvDataError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        record_audit(
            actor="user",
            action="transaction.deleted",
            detail=f"거래 {transaction_id} 삭제",
            reason="웹 거래 삭제",
        )
        return Response(status_code=204)

    @app.post("/api/reconcile/cash", status_code=201)
    def reconcile_cash(request: CashReconcileRequest) -> dict[str, Any]:
        _require_real_mode()
        try:
            currency = Currency(request.currency)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"알 수 없는 통화: {request.currency}"
            ) from None
        try:
            target = Decimal(request.target_balance)
        except InvalidOperation:
            raise HTTPException(
                status_code=400, detail=f"잘못된 금액: {request.target_balance}"
            ) from None

        today = as_of()
        repository = _transaction_repository()
        balances = CashLedger().build(repository.transactions_until(today))
        current = balances.get(currency, Money.zero(currency)).amount
        diff = target - current
        if diff == 0:
            return {"transaction_id": None, "diff": "0"}

        transaction = Transaction(
            transaction_id=f"{today.isoformat()}-{uuid.uuid4().hex[:8]}",
            transaction_type=TransactionType.DEPOSIT if diff > 0 else TransactionType.WITHDRAWAL,
            trade_date=today,
            amount=Money(abs(diff), currency),
            note=request.note or "잔액 보정",
        )
        try:
            repository.append(transaction)
        except CsvDataError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        record_audit(
            actor="user",
            action="cash.reconciled",
            detail=(
                f"현금 잔액 보정({currency.value}): {current} → {target} "
                f"({transaction.transaction_type.value} {abs(diff)})"
            ),
            reason=request.note or "웹 잔액 맞추기",
        )
        return {"transaction_id": transaction.transaction_id, "diff": str(diff)}

    @app.post("/api/reconcile/holding", status_code=201)
    def reconcile_holding(request: HoldingReconcileRequest) -> dict[str, Any]:
        _require_real_mode()
        asset_id = request.asset_id.strip()
        try:
            target_quantity = Decimal(request.target_quantity)
        except InvalidOperation:
            raise HTTPException(
                status_code=400, detail=f"잘못된 수량: {request.target_quantity}"
            ) from None
        if target_quantity < 0:
            raise HTTPException(status_code=400, detail="수량은 0 이상이어야 한다")

        today = as_of()
        repository = _transaction_repository()
        positions = PositionLedger().build(repository.transactions_until(today))
        position = positions.get(asset_id)
        current_quantity = position.quantity.value if position is not None else Decimal(0)
        diff = target_quantity - current_quantity
        if diff == 0:
            return {"transaction_id": None, "diff": "0"}

        price = CsvPriceLookup(storage_dir / "prices.csv").price_of(asset_id, today)
        if price is None:
            raise HTTPException(
                status_code=400,
                detail=f"{asset_id}의 현재가를 찾을 수 없어 보정 거래를 만들 수 없다",
            )

        transaction = Transaction(
            transaction_id=f"{today.isoformat()}-{uuid.uuid4().hex[:8]}",
            transaction_type=TransactionType.BUY if diff > 0 else TransactionType.SELL,
            trade_date=today,
            asset_id=asset_id,
            quantity=Quantity.of(abs(diff)),
            price=price,
            note=request.note or "보유수량 보정",
        )
        try:
            repository.append(transaction)
        except CsvDataError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        record_audit(
            actor="user",
            action="holding.reconciled",
            detail=(
                f"보유수량 보정({asset_id}): {current_quantity} → {target_quantity} "
                f"({transaction.transaction_type.value} {abs(diff)})"
            ),
            reason=request.note or "웹 잔액 맞추기",
        )
        return {"transaction_id": transaction.transaction_id, "diff": str(diff)}

    def _build_asset(asset_id: str, request: AssetRequest) -> Asset:
        try:
            return Asset(
                asset_id=asset_id,
                name=request.name.strip(),
                asset_class=AssetClass(request.asset_class),
                currency=Currency(request.currency),
                country=request.country.strip(),
                sector=(request.sector.strip() if request.sector else None),
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=f"잘못된 자산군/통화: {error}") from None

    @app.get("/api/assets")
    def list_assets() -> dict[str, Any]:
        _require_real_mode()
        assets = YamlAssetCatalog(dashboard_service.config_dir / "assets" / "default.yaml").all()
        return {
            "assets": [
                {
                    "asset_id": a.asset_id,
                    "name": a.name,
                    "asset_class": a.asset_class.value,
                    "currency": a.currency.value,
                    "country": a.country,
                    "sector": a.sector or "",
                }
                for a in sorted(assets, key=lambda a: a.asset_id)
            ]
        }

    @app.post("/api/assets", status_code=201)
    def register_asset(request: AssetRequest) -> dict[str, Any]:
        _require_real_mode()
        asset = _build_asset(request.asset_id.strip(), request)
        config_dir = dashboard_service.config_dir
        try:
            append_asset(config_dir / "assets" / "default.yaml", asset)
        except AssetConfigError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if request.yahoo_symbol and request.yahoo_symbol.strip():
            upsert_price_symbol(
                config_dir / "market" / "symbols.yaml",
                asset.asset_id,
                request.yahoo_symbol.strip(),
            )
        record_audit(
            actor="user",
            action="asset.registered",
            detail=f"종목 등록: {asset.asset_id} ({asset.name})",
            reason="웹 종목 추가",
        )
        return {"asset_id": asset.asset_id}

    @app.put("/api/assets/{asset_id}")
    def edit_asset(asset_id: str, request: AssetRequest) -> dict[str, Any]:
        _require_real_mode()
        asset = _build_asset(asset_id, request)
        config_dir = dashboard_service.config_dir
        try:
            update_asset(config_dir / "assets" / "default.yaml", asset_id, asset)
        except AssetConfigError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if request.yahoo_symbol and request.yahoo_symbol.strip():
            upsert_price_symbol(
                config_dir / "market" / "symbols.yaml", asset.asset_id, request.yahoo_symbol.strip()
            )
        record_audit(
            actor="user",
            action="asset.updated",
            detail=f"종목 수정: {asset.asset_id} ({asset.name})",
            reason="웹 종목 수정",
        )
        return {"asset_id": asset.asset_id}

    @app.delete("/api/assets/{asset_id}", status_code=204)
    def remove_asset(asset_id: str) -> Response:
        _require_real_mode()
        transactions = _transaction_repository().list_all()
        referencing = sum(1 for t in transactions if t.asset_id == asset_id)
        if referencing:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{asset_id}: 거래 내역 {referencing}건이 있어 삭제할 수 없다 "
                    "(거래를 먼저 정리하라)"
                ),
            )
        try:
            delete_asset(dashboard_service.config_dir / "assets" / "default.yaml", asset_id)
        except AssetConfigError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        record_audit(
            actor="user",
            action="asset.deleted",
            detail=f"종목 삭제: {asset_id}",
            reason="웹 종목 삭제",
        )
        return Response(status_code=204)

    @app.post("/api/triggers", status_code=201)
    def save_trigger(request: TriggerRequest) -> dict[str, Any]:
        _require_real_mode()
        try:
            currency = Currency(request.currency)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"알 수 없는 통화: {request.currency}"
            ) from None

        def money(value: str | None) -> Money | None:
            return Money.of(value, currency) if value not in (None, "") else None

        trigger = PriceTrigger(
            asset_id=request.asset_id.strip(),
            buy_at=money(request.buy_at),
            take_profit_at=money(request.take_profit_at),
            stop_loss_at=money(request.stop_loss_at),
        )
        save_price_trigger(dashboard_service.config_dir / "triggers" / "default.yaml", trigger)
        record_audit(
            actor="user",
            action="trigger.saved",
            detail=f"트리거 설정: {trigger.asset_id}",
            reason="웹 트리거 설정",
        )
        return {"asset_id": trigger.asset_id}

    @app.delete("/api/triggers/{asset_id}", status_code=204)
    def remove_trigger(asset_id: str) -> Response:
        _require_real_mode()
        try:
            delete_price_trigger(
                dashboard_service.config_dir / "triggers" / "default.yaml", asset_id
            )
        except PriceTriggerConfigError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        record_audit(
            actor="user",
            action="trigger.deleted",
            detail=f"트리거 삭제: {asset_id}",
            reason="웹 트리거 삭제",
        )
        return Response(status_code=204)

    @app.post("/api/triggers/bulk", status_code=201)
    def bulk_save_triggers(request: BulkTriggerRequest) -> dict[str, Any]:
        """평단가/현재가 대비 비율(%)로 보유 종목 전체의 트리거를 일괄 계산·저장한다.

        비율은 사용자가 정하고, 계산은 band_trigger(도메인)가 기계적으로 한다.
        결과가 논리적 순서(손절<매수<익절)를 어기는 종목은 저장하지 않고 건너뛴다.
        """
        _require_real_mode()
        try:
            stop_loss_percent = Decimal(request.stop_loss_percent)
            take_profit_percent = Decimal(request.take_profit_percent)
            buy_dip_percent = Decimal(request.buy_dip_percent)
        except InvalidOperation:
            raise HTTPException(status_code=400, detail="비율은 숫자여야 한다") from None

        outputs = dashboard_service.compute(as_of=as_of(), base_currency=Currency.KRW)
        equities = [v for v in outputs.snapshot.valuations if v.asset.asset_class.is_equity_like]
        trigger_path = dashboard_service.config_dir / "triggers" / "default.yaml"

        applied: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        for v in equities:
            quantity = v.position.quantity.value
            if quantity == 0:
                continue
            avg_price = Money(
                v.position.cost_basis.amount / quantity, v.position.cost_basis.currency
            )
            try:
                trigger = band_trigger(
                    asset_id=v.asset.asset_id,
                    avg_price=avg_price,
                    current_price=v.price,
                    stop_loss_percent=stop_loss_percent,
                    take_profit_percent=take_profit_percent,
                    buy_dip_percent=buy_dip_percent,
                )
            except DomainError as error:
                skipped.append(
                    {"asset_id": v.asset.asset_id, "name": v.asset.name, "reason": str(error)}
                )
                continue
            save_price_trigger(trigger_path, trigger)
            assert trigger.buy_at is not None
            assert trigger.take_profit_at is not None
            assert trigger.stop_loss_at is not None
            applied.append(
                {
                    "asset_id": v.asset.asset_id,
                    "name": v.asset.name,
                    "buy_at": str(trigger.buy_at.amount),
                    "take_profit_at": str(trigger.take_profit_at.amount),
                    "stop_loss_at": str(trigger.stop_loss_at.amount),
                }
            )

        if applied:
            record_audit(
                actor="user",
                action="trigger.bulk_saved",
                detail=(
                    f"트리거 일괄 설정(손절{stop_loss_percent}%/익절{take_profit_percent}%/"
                    f"매수{buy_dip_percent}%): {len(applied)}건 적용, {len(skipped)}건 건너뜀"
                ),
                reason="웹 트리거 일괄 설정",
            )
        return {"applied": applied, "skipped": skipped}

    @app.get("/api/stock-targets")
    def list_stock_targets() -> dict[str, Any]:
        _require_real_mode()
        path = dashboard_service.config_dir / "stock_targets" / "default.yaml"
        targets: list[StockTarget] = []
        if path.exists():
            try:
                targets = list(YamlStockTargetLoader(path).load().targets)
            except StockTargetConfigError:
                targets = []
        return {
            "targets": [
                {
                    "asset_id": t.asset_id,
                    "target_percent": str(t.target.as_percent),
                    "buy_band": str(t.buy_band.as_percent),
                    "sell_band": str(t.sell_band.as_percent),
                }
                for t in sorted(targets, key=lambda t: t.asset_id)
            ]
        }

    @app.post("/api/stock-targets", status_code=201)
    def register_stock_target(request: StockTargetRequest) -> dict[str, Any]:
        _require_real_mode()
        try:
            target = StockTarget(
                asset_id=request.asset_id.strip(),
                target=Percentage.from_percent(request.target_percent),
                buy_band=Percentage.from_percent(request.buy_band),
                sell_band=Percentage.from_percent(request.sell_band),
            )
        except (DomainError, InvalidOperation) as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        save_stock_target(dashboard_service.config_dir / "stock_targets" / "default.yaml", target)
        record_audit(
            actor="user",
            action="stock_target.saved",
            detail=f"종목 목표비중 설정: {target.asset_id} {request.target_percent}%",
            reason="웹 종목 목표비중 설정",
        )
        return {"asset_id": target.asset_id}

    @app.delete("/api/stock-targets/{asset_id}", status_code=204)
    def remove_stock_target(asset_id: str) -> Response:
        _require_real_mode()
        try:
            delete_stock_target(
                dashboard_service.config_dir / "stock_targets" / "default.yaml", asset_id
            )
        except StockTargetConfigError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        record_audit(
            actor="user",
            action="stock_target.deleted",
            detail=f"종목 목표비중 삭제: {asset_id}",
            reason="웹 종목 목표비중 삭제",
        )
        return Response(status_code=204)

    @app.post("/api/fx", status_code=201)
    def save_fx_rate(request: FxRequest) -> dict[str, Any]:
        _require_real_mode()
        try:
            base = Currency(request.base)
            quote = Currency(request.quote)
        except ValueError:
            raise HTTPException(status_code=400, detail="알 수 없는 통화") from None
        try:
            rate = Decimal(request.rate)
        except InvalidOperation:
            raise HTTPException(status_code=400, detail=f"잘못된 환율: {request.rate}") from None
        if rate <= 0:
            raise HTTPException(status_code=400, detail="환율은 양수여야 한다")
        try:
            rate_date = date.fromisoformat(request.rate_date) if request.rate_date else as_of()
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"잘못된 날짜: {request.rate_date}"
            ) from None

        upsert_fx_rate(storage_dir / "fx.csv", base, quote, rate_date, rate)
        record_audit(
            actor="user",
            action="fx.saved",
            detail=f"환율 입력: {base.value}/{quote.value} {rate_date.isoformat()} = {rate}",
            reason="웹 환율 입력",
        )
        return {"base": base.value, "quote": quote.value, "rate_date": rate_date.isoformat()}

    @app.post("/api/analysis")
    def generate_analysis(request: AnalysisRequest) -> dict[str, str]:
        if text_completion is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "AI 해설을 사용할 수 없다 - GEMINI_API_KEY(또는 ANTHROPIC_API_KEY)를 설정하라"
                ),
            )
        data = dashboard_service.build(as_of=as_of(), base_currency=Currency.KRW)
        try:
            narrative = GenerateAnalysis(completion=text_completion).execute(
                kind=AnalysisKind(request.kind),
                facts=_facts_from_dashboard(data),
                note=request.note,
            )
        except AnalysisProviderError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
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
