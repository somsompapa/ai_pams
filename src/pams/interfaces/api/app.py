"""FastAPI 앱 팩토리.

기본값은 데모 데이터 소스로 조립된다. 실계좌/실시세 어댑터가 준비되면
create_app()에 다른 DashboardService를 주입하면 된다.

AI 해설은 TextCompletion 구현이 있어야 동작한다:
- 테스트/개발: create_app(completion=...) 주입
- 운영: 환경변수 GEMINI_API_KEY(권장) 또는 ANTHROPIC_API_KEY, PAMS_AI_MODEL(선택) 설정
"""

from __future__ import annotations

import base64
import csv
import io
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
from pams.equity.application import (
    CalculateDcf,
    CalculateRelativeValuation,
    LoadGrowthMetrics,
    ScoreCompany,
)
from pams.equity.domain import (
    CompanyScoreInputs,
    DcfAssumptions,
    PriceTrigger,
    RiskDeduction,
    StockTarget,
    ValuationError,
    band_trigger,
    evaluate_buy_gate,
    evaluate_sell_review,
)
from pams.equity.domain.financial_statement import (
    AnnualFinancials,
    AnnualFinancialsResult,
    FinancialStatementProvider,
    FinancialStatementProviderError,
)
from pams.equity.domain.score import CategoryScore, CompanyScoreReport, ScoreItem
from pams.equity.infrastructure import (
    DartFinancialStatementProvider,
    PriceTriggerConfigError,
    ScoringConfigError,
    SecEdgarFinancialStatementProvider,
    StockTargetConfigError,
    YamlScoringConfigLoader,
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
from pams.market_data.domain import MarketDataProviderError, QuoteProvider
from pams.market_data.infrastructure import (
    CsvPriceLookup,
    YahooQuoteProvider,
    upsert_fx_rate,
    upsert_price_symbol,
)
from pams.market_regime.application import GradeMarketRegime
from pams.market_regime.domain import Grade, MarketIndicatorProvider, MarketRegimeProviderError
from pams.market_regime.infrastructure import (
    RegimeConfigError,
    YahooMarketRegimeIndicatorProvider,
    YamlMarketRegimeConfigLoader,
)
from pams.performance.application import ComputeRealizedPerformance
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
    kind: Literal["summary", "risk", "market", "journal_draft", "stock_trigger"]
    note: str | None = None
    asset_id: str | None = None  # kind == stock_trigger일 때 필수


class RiskDeductionInput(BaseModel):
    """company_analysis_rules.md 3-5 리스크 감점 항목. reason은 정의된 4종 중 하나여야
    캡이 정상 적용된다(규제 리스크 확대/경쟁 심화 신호/경기민감업종 & 경기 후행국면/
    경영진 리스크 이슈)."""

    reason: str
    points: str
    basis: str = ""


class EquityScoreRequest(BaseModel):
    """종목 100점 스코어링 + DCF 요청. company_analysis_rules.md 3장 구현(equity.domain).

    숫자는 float 오차를 막기 위해 문자열로 받는다. DCF 가정과 정성 판단 항목(시장점유율
    추이·진입장벽·WACC 근거 등)은 사람이 입력해야 한다 — 임의 추정 금지 원칙은 여기서도
    동일하게 적용된다(계산 불가 항목은 서버가 0점+사유로 처리, 서버가 값을 지어내지 않음).
    """

    asset_id: str
    market: Literal["US", "KR"]
    is_financial: bool = False
    years: int = 4

    # DCF 가정 (기준 FCF는 조회된 재무제표 최신연도에서 자동 채움 — 미확보 시 DCF 생략)
    wacc: str
    terminal_growth: str
    growth_path: list[str]
    net_debt: str = "0"
    shares_outstanding: str | None = None
    current_price: str | None = None
    wacc_basis: str = ""

    # 3-4 밸류에이션 상대지표(PER/PBR/PEG) — DCF 교차검증 보조, 절대 기준 아님.
    # 백분위는 해당 종목 자신의 과거 5년 PER/PBR 밴드 내 위치(0~1, 업종 평균 아님).
    per_band_percentile: str | None = None
    pbr_band_percentile: str | None = None
    peg: str | None = None

    # 3-1 성장성 (매출/총자산 CAGR·EPS CAGR·FCF흑자연도는 조회된 재무제표로 자동 계산)
    industry_tam_cagr: str | None = None

    # 3-2 경쟁력
    market_share_trend: Literal["up", "flat", "down"] | None = None
    gross_margin_vs_industry_pp: str | None = None  # 비금융업
    roa_vs_industry_pp: str | None = None  # 금융업(is_financial=True) 대체지표
    entry_barrier_regulatory: bool = False
    entry_barrier_capital_intensity: Literal["none", "normal", "extreme"] = "none"
    entry_barrier_network_effect: bool = False
    entry_barrier_basis: str = ""

    # 3-3 재무
    roe: str | None = None
    roic: str | None = None
    op_margin_industry_rank: Literal["top30", "mid", "bottom"] | None = None
    debt_ratio: str | None = None  # 비금융업만(금융업은 예외 처리, company_analysis_rules.md 3-3)

    # 3-5 리스크
    risk_deductions: list[RiskDeductionInput] = []


class MarketRegimeRequest(BaseModel):
    """시장 국면(4장 A~E) 판정 요청. market_analysis_rules.md 4장 구현(market_regime.domain).

    5개 지표 중 일부만 입력해도 판정은 시도한다(3개 미만이면 '판단 보류'로 응답) —
    자동조회 대상이 아닌 지표(10년물·PER·외국인수급)는 항상 사람이 범주를 골라 입력한다.
    """

    vix: str | None = None
    circuit_breaker: str | None = None  # KOSPI 전일 대비 등락률(%), 예: "-5.3"
    treasury_10y: (
        Literal["stable_or_down", "mild_up", "flat", "spike", "spike_continued"] | None
    ) = None
    sp500_per: Literal["lower_mid", "mid", "upper_mid", "near_upper", "above_upper"] | None = None
    kospi_foreign_flow: (
        Literal["net_buy", "turning_buy", "mixed", "turning_sell", "heavy_sell"] | None
    ) = None


class BuyGateRequest(BaseModel):
    """매수 필수조건(buy_rules.md B-1) AND 게이트 판정 요청.

    /api/equity-score와 /api/market-regime 호출 결과를 클라이언트가 조립해 넘긴다
    (equity와 market_regime은 서로 다른 컨텍스트라 서버가 자동으로 묶지 않는다 —
    두 계산은 독립적으로 이미 끝난 상태에서, 이 엔드포인트는 4개 조건만 판정한다).
    """

    total_score: str  # 0~100, /api/equity-score의 score.total_score
    dcf_gap_ratio: str | None = None  # /api/equity-score dcf.gap.gap_ratio
    market_grade: Literal["A", "B", "C", "D", "E"] | None = None  # /api/market-regime final_grade
    investment_thesis: str = ""


class SellReviewRequest(BaseModel):
    """매도 판단 보조(sell_rules.md 5장) 요청. 자동집행 아님 — 신호만 드러낸다.

    S-1(논리훼손, OR): 성장 둔화·점유율 하락·산업구조 변화 중 하나라도 있으면 검토.
    S-2(과대평가): /api/equity-score dcf.gap.gap_ratio를 그대로 넘기면 +50%/+100%
    구간에 따라 25%/50% 부분매도를 제안한다.
    """

    revenue_yoy_growth_deceleration_pp: str | None = None  # 전년 대비 YoY 성장률 둔화폭
    market_share_declining_two_quarters: bool = False
    structural_disruption: bool = False
    structural_disruption_note: str = ""
    dcf_gap_ratio: str | None = None


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
    # portfolio_rules.md P-3 초우량 예외(단일종목 20%→30%). 임의 적용 금지 —
    # 반드시 사유 문장과 함께 설정한다.
    exceptional_quality_reason: str | None = None


class BulkImportAssetsRequest(BaseModel):
    """CSV 텍스트로 여러 종목을 한 번에 등록. 헤더: asset_id,name,asset_class,currency,
    country,sector,yahoo_symbol,exceptional_quality_reason (뒤 3개는 선택)."""

    csv_text: str


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


def _facts_for_stock(data: dict[str, Any], asset_id: str) -> list[str]:
    """특정 종목의 매수/익절/손절 트리거 상태만 뽑은 사실 목록."""
    stock = next((s for s in data["stocks"] if s["asset_id"] == asset_id), None)
    if stock is None:
        raise HTTPException(status_code=400, detail=f"보유 중인 주식 종목이 아니다: {asset_id}")
    return [
        f"기준일: {data['as_of']}",
        f"종목: {stock['name']} ({stock['asset_id']})",
        f"보유수량: {stock['quantity']}",
        f"평단가: {stock['avg_price']}",
        f"현재가: {stock['current_price']}",
        f"평가손익: {stock['unrealized_pnl']} ({stock['unrealized_percent']})",
        f"매수선(이하로 내려가면 매수): {stock['buy_trigger']}",
        f"익절선(이상으로 올라가면 매도): {stock['take_profit']}",
        f"손절선(이하로 내려가면 매도): {stock['stop_loss']}",
        f"현재 트리거 신호: {stock['signal_label']}",
    ]


def _serialize_annual_financials(row: AnnualFinancials) -> dict[str, Any]:
    return {
        "fiscal_year": row.fiscal_year,
        "revenue": str(row.revenue) if row.revenue is not None else None,
        "operating_income": str(row.operating_income) if row.operating_income is not None else None,
        "net_income": str(row.net_income) if row.net_income is not None else None,
        "eps": str(row.eps) if row.eps is not None else None,
        "gross_profit": str(row.gross_profit) if row.gross_profit is not None else None,
        "total_assets": str(row.total_assets) if row.total_assets is not None else None,
        "total_equity": str(row.total_equity) if row.total_equity is not None else None,
        "total_equity_derived": row.total_equity_derived,
        "controlling_interest_equity": (
            str(row.controlling_interest_equity)
            if row.controlling_interest_equity is not None
            else None
        ),
        "total_debt": str(row.total_debt) if row.total_debt is not None else None,
        "cash": str(row.cash) if row.cash is not None else None,
        "operating_cash_flow": (
            str(row.operating_cash_flow) if row.operating_cash_flow is not None else None
        ),
        "capex": str(row.capex) if row.capex is not None else None,
        "fcf": str(row.fcf) if row.fcf is not None else None,
    }


def _serialize_financials_result(result: AnnualFinancialsResult) -> dict[str, Any]:
    return {
        "asset_id": result.asset_id,
        "data_source": result.data_source,
        "annual": [_serialize_annual_financials(row) for row in result.annual],
        "fetch_errors": list(result.fetch_errors),
    }


def _serialize_score_item(item: ScoreItem) -> dict[str, Any]:
    return {
        "metric": item.metric,
        "value": item.value,
        "bucket": item.bucket,
        "score": str(item.score),
        "max_score": str(item.max_score),
        "note": item.note,
    }


def _serialize_category(category: CategoryScore) -> dict[str, Any]:
    return {
        "category": category.category,
        "max_score": str(category.max_score),
        "score": str(category.score),
        "items": [_serialize_score_item(item) for item in category.items],
    }


def _serialize_score_report(report: CompanyScoreReport) -> dict[str, Any]:
    return {
        "symbol": report.symbol,
        "as_of": report.as_of.isoformat(),
        "data_source": report.data_source,
        "total_score": str(report.total_score),
        "verdict": report.verdict.value,
        "buy_score_condition_met": report.buy_score_condition_met,
        "categories": [_serialize_category(c) for c in report.categories],
        "data_quality_flags": list(report.data_quality_flags),
    }


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
    equity_providers: dict[str, FinancialStatementProvider] | None = None,
    market_indicator_provider: MarketIndicatorProvider | None = None,
    equity_price_provider: QuoteProvider | None = None,
) -> FastAPI:
    dashboard_service = service if service is not None else default_dashboard_service()
    as_of = as_of_provider if as_of_provider is not None else _default_as_of
    access_password = (
        password if password is not None else os.environ.get("PAMS_PASSWORD", "").strip() or None
    )
    storage_dir = data_dir if data_dir is not None else _PROJECT_ROOT / "data"
    journal_repository = JsonlJournalRepository(storage_dir / "journal.jsonl")
    audit_recorder = RecordAuditEvent(trail=JsonlAuditTrail(storage_dir / "audit.jsonl"))
    injected_equity_providers = equity_providers or {}
    indicator_provider = market_indicator_provider or YahooMarketRegimeIndicatorProvider()
    price_provider = equity_price_provider or YahooQuoteProvider()
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
                exceptional_quality_reason=(
                    request.exceptional_quality_reason.strip()
                    if request.exceptional_quality_reason
                    else None
                ),
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
                    "exceptional_quality_reason": a.exceptional_quality_reason or "",
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

    @app.post("/api/assets/bulk-import")
    def bulk_import_assets(request: BulkImportAssetsRequest) -> dict[str, Any]:
        """보유 종목이 많을 때 하나씩 등록하지 않아도 되도록 CSV로 일괄 등록한다.
        한 행이 실패해도 나머지 행은 계속 처리한다(부분 실패 허용 — 실패 사유를 행 번호와
        함께 반환, 이미 등록된 종목이 있다는 이유로 전체를 되돌리지 않는다)."""
        _require_real_mode()
        config_dir = dashboard_service.config_dir
        try:
            reader = csv.DictReader(io.StringIO(request.csv_text))
        except csv.Error as error:
            raise HTTPException(status_code=400, detail=f"CSV 파싱 실패: {error}") from None

        required_columns = {"asset_id", "name", "asset_class", "currency", "country"}
        header = set(reader.fieldnames or [])
        missing_columns = required_columns - header
        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=f"CSV 헤더에 필수 열이 없다: {', '.join(sorted(missing_columns))}",
            )

        created: list[str] = []
        errors: list[dict[str, Any]] = []
        for row_number, row in enumerate(reader, start=2):  # 1행은 헤더이므로 데이터는 2행부터
            asset_id = (row.get("asset_id") or "").strip()
            try:
                if not asset_id:
                    raise ValueError("asset_id가 비어 있다")
                sector = (row.get("sector") or "").strip() or None
                yahoo_symbol = (row.get("yahoo_symbol") or "").strip() or None
                exceptional_reason = (row.get("exceptional_quality_reason") or "").strip() or None
                asset_req = AssetRequest(
                    asset_id=asset_id,
                    name=(row.get("name") or "").strip(),
                    asset_class=(row.get("asset_class") or "").strip(),
                    currency=(row.get("currency") or "").strip(),
                    country=(row.get("country") or "").strip(),
                    sector=sector,
                    yahoo_symbol=yahoo_symbol,
                    exceptional_quality_reason=exceptional_reason,
                )
                asset = _build_asset(asset_id, asset_req)
                append_asset(config_dir / "assets" / "default.yaml", asset)
                if yahoo_symbol:
                    upsert_price_symbol(
                        config_dir / "market" / "symbols.yaml", asset_id, yahoo_symbol
                    )
                created.append(asset.asset_id)
            except HTTPException as error:
                errors.append(
                    {"row": row_number, "asset_id": asset_id, "reason": str(error.detail)}
                )
            except (ValueError, AssetConfigError) as error:
                errors.append({"row": row_number, "asset_id": asset_id, "reason": str(error)})

        if created:
            record_audit(
                actor="user",
                action="asset.bulk_imported",
                detail=f"CSV 일괄 등록: {len(created)}건 성공, {len(errors)}건 실패",
                reason="웹 CSV 업로드",
            )
        return {
            "created": created,
            "created_count": len(created),
            "errors": errors,
            "error_count": len(errors),
        }

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
        if request.kind == "stock_trigger":
            if not request.asset_id or not request.asset_id.strip():
                raise HTTPException(
                    status_code=400, detail="종목 트리거 확인에는 asset_id가 필요하다"
                )
            facts = _facts_for_stock(data, request.asset_id.strip())
        else:
            facts = _facts_from_dashboard(data)
        try:
            narrative = GenerateAnalysis(completion=text_completion).execute(
                kind=AnalysisKind(request.kind),
                facts=facts,
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

    def _equity_financial_provider(market: str) -> FinancialStatementProvider:
        injected = injected_equity_providers.get(market)
        if injected is not None:
            return injected
        if market == "US":
            contact = os.environ.get("SEC_EDGAR_CONTACT_EMAIL", "").strip()
            return SecEdgarFinancialStatementProvider(contact_email=contact)
        if market == "KR":
            api_key = os.environ.get("DART_API_KEY", "").strip()
            return DartFinancialStatementProvider(
                api_key=api_key,
                corp_code_cache_path=storage_dir / ".dart_corp_code_cache.xml",
            )
        raise HTTPException(status_code=400, detail=f"알 수 없는 market: {market}")

    def _optional_decimal(label: str, value: str | None) -> Decimal | None:
        if value is None or value.strip() == "":
            return None
        try:
            return Decimal(value)
        except InvalidOperation:
            raise HTTPException(
                status_code=400, detail=f"{label}: 숫자 형식 오류({value!r})"
            ) from None

    def _required_decimal(label: str, value: str) -> Decimal:
        result = _optional_decimal(label, value)
        if result is None:
            raise HTTPException(status_code=400, detail=f"{label}: 필수 값이 비어 있다")
        return result

    def _money_str(value: Decimal) -> str:
        """DCF 산출값(적정가·기업가치 등) 표시용 반올림(소수 2자리) — 계산은 원본
        Decimal로 이미 끝난 뒤라 표시값 반올림이 정확도에 영향을 주지 않는다."""
        return str(value.quantize(Decimal("0.01")))

    def _ratio_str(value: Decimal | None) -> str | None:
        """CAGR 등 비율 표시용 반올림(소수 4자리) — ln()/exp()로 계산돼 전체 정밀도를
        그대로 노출하면 API 응답이 읽기 어렵다."""
        return str(value.quantize(Decimal("0.0001"))) if value is not None else None

    def _fetch_equity_price(asset_id: str, market: str) -> tuple[Decimal | None, str | None]:
        """현재가 자동조회. 실패해도 예외를 던지지 않는다 — (값, 실패사유) 튜플로
        돌려주고 값이 없으면 DCF 괴리율 계산만 생략한다(임의 대체 금지)."""
        candidates = (asset_id,) if market == "US" else (f"{asset_id}.KS", f"{asset_id}.KQ")
        errors: list[str] = []
        for symbol in candidates:
            try:
                quote = price_provider.latest_quote(symbol)
            except MarketDataProviderError as error:
                errors.append(f"{symbol}: {error}")
                continue
            if quote is not None:
                return quote.close, None
            errors.append(f"{symbol}: 조회 결과 없음")
        return None, f"현재가 자동조회 실패({'; '.join(errors)})"

    @app.post("/api/equity-score")
    def compute_equity_score(request: EquityScoreRequest) -> dict[str, Any]:
        """종목 100점 스코어링 + DCF (company_analysis_rules.md 3장, equity.domain).

        재무제표(SEC/DART)는 자동 조회하고, 정성 판단 항목·DCF 가정은 요청 본문으로 받는다
        — 계산 불가한 항목을 서버가 지어내지 않는다(임의 추정 금지).
        """
        provider = _equity_financial_provider(request.market)
        try:
            growth_report = LoadGrowthMetrics(provider=provider).execute(
                request.asset_id, years=request.years
            )
        except FinancialStatementProviderError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

        metrics = growth_report.metrics
        annual = growth_report.financials.annual
        base_fcf = annual[-1].fcf if annual else None

        # 종목 심볼만 입력해도 분석이 가능하도록, 현재가와 발행주식수는 명시 입력이
        # 없을 때만 자동조회를 시도한다(있으면 그대로 존중 — 임의 대체 금지).
        market_data_fetch_errors: list[str] = []
        current_price = _optional_decimal("current_price", request.current_price)
        if current_price is None:
            current_price, price_error = _fetch_equity_price(request.asset_id, request.market)
            if price_error is not None:
                market_data_fetch_errors.append(price_error)
        shares_outstanding = _optional_decimal("shares_outstanding", request.shares_outstanding)
        if shares_outstanding is None:
            shares_outstanding = annual[-1].shares_outstanding if annual else None
            if shares_outstanding is None:
                market_data_fetch_errors.append(
                    "발행주식수 자동조회 실패(재무제표에 미포함) — 직접 입력하면 "
                    "주당 적정가를 계산할 수 있다"
                )

        dcf_payload: dict[str, Any] | None = None
        dcf_score: Decimal | None = None
        if base_fcf is not None:
            try:
                assumptions = DcfAssumptions(
                    base_fcf=base_fcf,
                    wacc=_required_decimal("wacc", request.wacc),
                    terminal_growth=_required_decimal("terminal_growth", request.terminal_growth),
                    growth_path=tuple(
                        _required_decimal(f"growth_path[{i}]", g)
                        for i, g in enumerate(request.growth_path)
                    ),
                    net_debt=_optional_decimal("net_debt", request.net_debt) or Decimal(0),
                    shares_outstanding=shares_outstanding,
                    wacc_basis=request.wacc_basis,
                )
                dcf_report = CalculateDcf().execute(
                    assumptions,
                    current_price=current_price,
                )
                dcf_score = dcf_report.gap.score if dcf_report.gap is not None else None
                dcf_payload = {
                    "fair_value_per_share": (
                        _money_str(dcf_report.result.fair_value_per_share)
                        if dcf_report.result.fair_value_per_share is not None
                        else None
                    ),
                    # 발행주식수가 없어도 기업가치·자기자본가치는 유효하게 계산되므로
                    # 항상 보여준다(trigger_zones 실패가 이 값들까지 지우지 않는다).
                    "enterprise_value": _money_str(dcf_report.result.enterprise_value),
                    "equity_value": _money_str(dcf_report.result.equity_value),
                    "sensitivity_grid": {
                        k: (_money_str(v) if v is not None else None)
                        for k, v in dcf_report.sensitivity.items()
                    },
                    "trigger_zones": (
                        {
                            "buy_high_confidence_upper": _money_str(
                                dcf_report.zones.buy_high_confidence_upper
                            ),
                            "buy_base_case_upper": _money_str(dcf_report.zones.buy_base_case_upper),
                            "watch_lower": _money_str(dcf_report.zones.watch_lower),
                            "watch_upper": _money_str(dcf_report.zones.watch_upper),
                            "sell_25pct_lower": _money_str(dcf_report.zones.sell_25pct_lower),
                            "sell_50pct_lower": _money_str(dcf_report.zones.sell_50pct_lower),
                        }
                        if dcf_report.zones is not None
                        else None
                    ),
                    "trigger_zones_unavailable_reason": dcf_report.zones_unavailable_reason,
                    "gap": (
                        {
                            "gap_ratio": str(dcf_report.gap.gap_ratio.quantize(Decimal("0.0001"))),
                            "score": str(dcf_report.gap.score),
                            "label": dcf_report.gap.label,
                            "buy_price_condition_met": dcf_report.gap.buy_price_condition_met,
                        }
                        if dcf_report.gap is not None
                        else None
                    ),
                }
            except ValuationError as error:
                dcf_payload = {"error": str(error)}

        risk_deductions = tuple(
            RiskDeduction(
                reason=d.reason,
                points=_required_decimal(f"risk_deductions.{d.reason}.points", d.points),
                basis=d.basis,
            )
            for d in request.risk_deductions
        )

        try:
            scoring_config = YamlScoringConfigLoader(
                dashboard_service.config_dir / "equity_scoring" / "default.yaml"
            ).load()
        except ScoringConfigError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

        relative_valuation = CalculateRelativeValuation(
            config=scoring_config.relative_valuation
        ).execute(
            per_band_percentile=_optional_decimal(
                "per_band_percentile", request.per_band_percentile
            ),
            pbr_band_percentile=_optional_decimal(
                "pbr_band_percentile", request.pbr_band_percentile
            ),
            peg=_optional_decimal("peg", request.peg),
        )
        # 세 입력이 전부 미제공이면 "0점짜리 상대지표"가 아니라 DCF와 동일하게
        # 미산출로 처리한다(데이터 누락을 숨기지 않는다 — score_valuation()의 _missing()).
        relative_valuation_input_score = (
            None
            if request.per_band_percentile is None
            and request.pbr_band_percentile is None
            and request.peg is None
            else relative_valuation.score
        )

        inputs = CompanyScoreInputs(
            symbol=request.asset_id,
            as_of=as_of(),
            data_source=growth_report.financials.data_source,
            is_financial=request.is_financial,
            revenue_cagr_3y=None if request.is_financial else metrics.revenue_cagr_3y,
            total_assets_cagr_3y=metrics.total_assets_cagr_3y if request.is_financial else None,
            eps_cagr_3y=metrics.eps_cagr_3y,
            industry_tam_cagr=_optional_decimal("industry_tam_cagr", request.industry_tam_cagr),
            market_share_trend=request.market_share_trend,
            gross_margin_vs_industry_pp=(
                None
                if request.is_financial
                else _optional_decimal(
                    "gross_margin_vs_industry_pp", request.gross_margin_vs_industry_pp
                )
            ),
            roa_vs_industry_pp=(
                _optional_decimal("roa_vs_industry_pp", request.roa_vs_industry_pp)
                if request.is_financial
                else None
            ),
            entry_barrier_regulatory=request.entry_barrier_regulatory,
            entry_barrier_capital_intensity=request.entry_barrier_capital_intensity,
            entry_barrier_network_effect=request.entry_barrier_network_effect,
            entry_barrier_basis=request.entry_barrier_basis,
            # roe 미입력 시 자동조회된 재무제표에서 계산한 값을 쓴다(분모는 반드시
            # controlling_interest_equity — total_equity/총자본 아님, growth_metrics.py 참조).
            roe=(
                _optional_decimal("roe", request.roe)
                if request.roe is not None
                else metrics.roe_latest
            ),
            roic=_optional_decimal("roic", request.roic),
            wacc_estimate=_optional_decimal("wacc", request.wacc),
            wacc_basis=request.wacc_basis,
            op_margin_industry_rank=request.op_margin_industry_rank,
            fcf_positive_years=metrics.fcf_positive_years,
            # debt_ratio 미입력 시 자동조회된 재무제표(total_debt/total_equity)에서
            # 계산한 값을 쓴다(roe와 동일한 자동조회 우선순위 원칙).
            debt_ratio=(
                None
                if request.is_financial
                else (
                    _optional_decimal("debt_ratio", request.debt_ratio)
                    if request.debt_ratio is not None
                    else metrics.debt_ratio_latest
                )
            ),
            dcf_valuation_score=dcf_score,
            relative_valuation_score=relative_valuation_input_score,
            risk_deductions=risk_deductions,
        )

        score_report = ScoreCompany(config=scoring_config).execute(inputs)
        record_audit(
            actor="user",
            action="equity_score.computed",
            detail=f"종목분석: {request.asset_id} 총점 {score_report.total_score}",
            reason="웹 종목분석 요청",
        )
        return {
            "score": _serialize_score_report(score_report),
            "financials": _serialize_financials_result(growth_report.financials),
            "market_data": {
                "current_price": _money_str(current_price) if current_price is not None else None,
                "shares_outstanding": (
                    str(shares_outstanding) if shares_outstanding is not None else None
                ),
                "fetch_errors": market_data_fetch_errors,
            },
            "growth_metrics": {
                "revenue_cagr_3y": _ratio_str(metrics.revenue_cagr_3y),
                "revenue_cagr_3y_note": metrics.revenue_cagr_3y_note,
                "eps_cagr_3y": _ratio_str(metrics.eps_cagr_3y),
                "eps_cagr_3y_note": metrics.eps_cagr_3y_note,
                "total_assets_cagr_3y": _ratio_str(metrics.total_assets_cagr_3y),
                "total_assets_cagr_3y_note": metrics.total_assets_cagr_3y_note,
                "fcf_positive_years": metrics.fcf_positive_years,
                "fcf_positive_years_note": metrics.fcf_positive_years_note,
                "roa_latest": _ratio_str(metrics.roa_latest),
                "gross_margin_latest": _ratio_str(metrics.gross_margin_latest),
                "roe_latest": _ratio_str(metrics.roe_latest),
                "debt_ratio_latest": _ratio_str(metrics.debt_ratio_latest),
            },
            "dcf": dcf_payload,
            "relative_valuation": {
                "score": str(relative_valuation.score),
                "per_score": (
                    str(relative_valuation.per_score)
                    if relative_valuation.per_score is not None
                    else None
                ),
                "pbr_score": (
                    str(relative_valuation.pbr_score)
                    if relative_valuation.pbr_score is not None
                    else None
                ),
                "peg_adjustment": str(relative_valuation.peg_adjustment),
                "missing": list(relative_valuation.missing),
                "note": relative_valuation.note,
            },
        }

    @app.post("/api/market-regime")
    def compute_market_regime(request: MarketRegimeRequest) -> dict[str, Any]:
        """시장 국면(4장 A~E) 판정. buy_rules.md B-1 조건2(시장 상태 C 이상)의 근거."""
        try:
            config = YamlMarketRegimeConfigLoader(
                dashboard_service.config_dir / "market_regime" / "default.yaml"
            ).load()
        except RegimeConfigError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

        vix = _optional_decimal("vix", request.vix)
        circuit_breaker = _optional_decimal("circuit_breaker", request.circuit_breaker)
        fetch_errors: list[str] = []
        # 명시 입력이 있으면 그대로 존중하고, 없을 때만 자동조회를 시도한다(임의 대체 금지).
        if vix is None:
            try:
                vix = indicator_provider.fetch_vix()
            except MarketRegimeProviderError as error:
                fetch_errors.append(f"VIX 자동조회 실패: {error}")
        if circuit_breaker is None:
            try:
                circuit_breaker = indicator_provider.fetch_kospi_change_pct()
            except MarketRegimeProviderError as error:
                fetch_errors.append(f"KOSPI 등락률 자동조회 실패: {error}")

        observations: dict[str, Decimal | str | None] = {
            "vix": vix,
            "circuit_breaker": circuit_breaker,
            "treasury_10y": request.treasury_10y,
            "sp500_per": request.sp500_per,
            "kospi_foreign_flow": request.kospi_foreign_flow,
        }
        result = GradeMarketRegime(config=config).execute(observations, as_of=as_of())
        grade_text = result.final_grade.value if result.final_grade else "판단 보류"
        record_audit(
            actor="user",
            action="market_regime.graded",
            detail=f"시장국면 판정: {grade_text}",
            reason="웹 시장분석 요청",
        )
        return {
            "final_grade": result.final_grade.value if result.final_grade else None,
            "tie_broken": result.tie_broken,
            "action_guidance": result.action_guidance,
            "buy_allowed": result.buy_allowed,
            "fetch_errors": fetch_errors,
            "grade_tally": {g.value: count for g, count in result.grade_tally.items()},
            "indicator_grades": [
                {
                    "indicator": ig.indicator,
                    "observed": ig.observed,
                    "grade": ig.grade.value if ig.grade else None,
                    "basis": ig.basis,
                    "source": ig.source,
                    "note": ig.note,
                }
                for ig in result.indicator_grades
            ],
        }

    @app.post("/api/buy-gate")
    def compute_buy_gate(request: BuyGateRequest) -> dict[str, Any]:
        """매수 필수조건(buy_rules.md B-1) AND 게이트. 4개 조건 중 하나라도 미충족이면
        매수 금지 — /api/equity-score·/api/market-regime 결과를 조립해 판정만 한다."""
        total_score = _required_decimal("total_score", request.total_score)
        score_met = total_score >= 80

        market_grade = Grade(request.market_grade) if request.market_grade else None
        market_met = market_grade is not None and market_grade.at_least_as_safe_as(Grade.C)
        market_detail = market_grade.value if market_grade else "미확보(판단 보류 포함)"

        gap_ratio = _optional_decimal("dcf_gap_ratio", request.dcf_gap_ratio)
        price_met = gap_ratio is not None and gap_ratio <= Decimal("-0.10")
        price_detail = "미확보" if gap_ratio is None else str(gap_ratio.quantize(Decimal("0.0001")))

        result = evaluate_buy_gate(
            score_condition_met=score_met,
            score_detail=f"{total_score}점",
            market_grade_condition_met=market_met,
            market_grade_detail=market_detail,
            price_discount_condition_met=price_met,
            price_discount_detail=price_detail,
            investment_thesis=request.investment_thesis,
        )
        record_audit(
            actor="user",
            action="buy_gate.evaluated",
            detail=f"매수 게이트 판정: {'통과' if result.all_conditions_met else '미충족'}",
            reason="웹 매수판정 요청",
        )
        return {
            "all_conditions_met": result.all_conditions_met,
            "conditions": [
                {"condition": c.condition, "met": c.met, "detail": c.detail}
                for c in result.conditions
            ],
        }

    @app.post("/api/sell-review")
    def compute_sell_review(request: SellReviewRequest) -> dict[str, Any]:
        """매도 판단 보조(sell_rules.md 5장). 신호를 드러낼 뿐 자동집행하지 않는다 —
        실행 전 사용자 최종 확인 필수(S-4 체크리스트)."""
        result = evaluate_sell_review(
            revenue_yoy_growth_deceleration_pp=_optional_decimal(
                "revenue_yoy_growth_deceleration_pp", request.revenue_yoy_growth_deceleration_pp
            ),
            market_share_declining_two_quarters=request.market_share_declining_two_quarters,
            structural_disruption=request.structural_disruption,
            structural_disruption_note=request.structural_disruption_note,
            dcf_gap_ratio=_optional_decimal("dcf_gap_ratio", request.dcf_gap_ratio),
        )
        record_audit(
            actor="user",
            action="sell_review.evaluated",
            detail=f"매도 검토: {'권고' if result.review_recommended else '해당 없음'}",
            reason="웹 매도판정 요청",
        )
        return {
            "review_recommended": result.review_recommended,
            "thesis_break_triggered": result.thesis_break_triggered,
            "suggested_sell_fraction": (
                str(result.suggested_sell_fraction)
                if result.suggested_sell_fraction is not None
                else None
            ),
            "thesis_break_signals": [
                {"reason": s.reason, "triggered": s.triggered, "detail": s.detail}
                for s in result.thesis_break_signals
            ],
            "overvaluation_signal": {
                "reason": result.overvaluation_signal.reason,
                "triggered": result.overvaluation_signal.triggered,
                "detail": result.overvaluation_signal.detail,
            },
        }

    @app.get("/api/realized-performance")
    def get_realized_performance() -> dict[str, Any]:
        """실제 거래 원장(Transaction)을 FIFO로 랏 매칭해 실현 CAGR·MDD를 산출한다.
        PositionLedger의 이동평균 회계와는 별개의 사후 성과분석 관점이다."""
        _require_real_mode()
        transactions = _transaction_repository().list_all()
        report = ComputeRealizedPerformance().execute(transactions)
        return {
            "note": report.note,
            "n_open_lots": report.n_open_lots,
            "by_currency": [
                {
                    "currency": r.currency.value,
                    "n_closed_lots": r.n_closed_lots,
                    "total_cost": str(r.total_cost),
                    "total_proceeds": str(r.total_proceeds),
                    "total_realized_pnl": str(r.total_realized_pnl),
                    "realized_return_pct": (
                        str(r.realized_return_pct) if r.realized_return_pct is not None else None
                    ),
                    "capital_weighted_cagr": (
                        _ratio_str(r.capital_weighted_cagr)
                        if r.capital_weighted_cagr is not None
                        else None
                    ),
                    "realized_pnl_drawdown_approx": (
                        _ratio_str(r.realized_pnl_drawdown_approx)
                        if r.realized_pnl_drawdown_approx is not None
                        else None
                    ),
                }
                for r in report.by_currency
            ],
            "skipped": [
                {
                    "transaction_id": s.transaction_id,
                    "asset_id": s.asset_id,
                    "trade_date": s.trade_date.isoformat(),
                    "reason": s.reason,
                }
                for s in report.skipped
            ],
        }

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
