"""POST /api/equity-score 통합 테스트. 실네트워크 없이 페이크 FinancialStatementProvider 주입."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from pams.equity.domain.financial_statement import AnnualFinancials, AnnualFinancialsResult
from pams.interfaces.api.app import create_app
from pams.market_data.domain import MarketDataProviderError, Quote, QuoteProvider
from pams.shared_kernel.domain import Currency

_NON_FINANCIAL_ANNUAL = (
    AnnualFinancials(
        fiscal_year=2022,
        revenue=Decimal(1000),
        eps=Decimal(10),
        operating_cash_flow=Decimal(150),
        capex=Decimal(50),
    ),
    AnnualFinancials(
        fiscal_year=2023,
        revenue=Decimal(1100),
        eps=Decimal(11),
        operating_cash_flow=Decimal(160),
        capex=Decimal(50),
    ),
    AnnualFinancials(
        fiscal_year=2024,
        revenue=Decimal(1210),
        eps=Decimal(12),
        operating_cash_flow=Decimal(170),
        capex=Decimal(50),
    ),
    AnnualFinancials(
        fiscal_year=2025,
        revenue=Decimal(1331),
        eps=Decimal(13),
        operating_cash_flow=Decimal(180),
        capex=Decimal(50),
    ),
)


@dataclass(frozen=True, slots=True)
class _FakeProvider:
    result: AnnualFinancialsResult

    def annual_financials(self, asset_id: str, *, years: int = 4) -> AnnualFinancialsResult:
        return self.result


@dataclass(frozen=True, slots=True)
class _FakeQuoteProvider:
    quotes: dict[str, Quote]

    def latest_quote(self, symbol: str) -> Quote | None:
        return self.quotes.get(symbol)


@dataclass(frozen=True, slots=True)
class _FailingQuoteProvider:
    def latest_quote(self, symbol: str) -> Quote | None:
        raise MarketDataProviderError(f"{symbol}: 요청 실패")


def _client(
    tmp_path: Path,
    provider: _FakeProvider,
    market: str = "US",
    price_provider: QuoteProvider | None = None,
) -> TestClient:
    # 실네트워크 호출을 막기 위해 기본값은 항상 실패하는 페이크로 둔다 — current_price가
    # 요청에 없으면(대부분의 기존 테스트) 자동조회가 시도되므로, 명시적으로 값을 주지
    # 않는 한 진짜 Yahoo Finance를 호출하면 안 된다.
    app = create_app(
        data_dir=tmp_path,
        equity_providers={market: provider},
        equity_price_provider=price_provider or _FailingQuoteProvider(),
    )
    return TestClient(app)


_BASE_PAYLOAD = {
    "asset_id": "TEST",
    "market": "US",
    "wacc": "0.085",
    "terminal_growth": "0.025",
    "growth_path": ["0.1", "0.1", "0.1", "0.1", "0.1"],
    "net_debt": "0",
    "shares_outstanding": "100",
    "market_share_trend": "up",
    "gross_margin_vs_industry_pp": "0.06",
    "entry_barrier_regulatory": True,
    "entry_barrier_capital_intensity": "normal",
    "roe": "0.18",
    "op_margin_industry_rank": "top30",
    "debt_ratio": "0.4",
}


class TestEquityScoreApi:
    def test_computes_score_and_dcf(self, tmp_path: Path) -> None:
        provider = _FakeProvider(
            AnnualFinancialsResult(
                asset_id="TEST", data_source="fake", annual=_NON_FINANCIAL_ANNUAL
            )
        )
        client = _client(tmp_path, provider)
        response = client.post("/api/equity-score", json=_BASE_PAYLOAD)
        assert response.status_code == 200
        body = response.json()

        # 성장성: revenue_cagr_3y = 10% 정확히 → 4개년 데이터로 계산됨
        growth = next(c for c in body["score"]["categories"] if c["category"] == "성장성")
        revenue_item = next(i for i in growth["items"] if i["metric"] == "매출 3Y CAGR")
        assert revenue_item["bucket"] == "10~15%"

        # DCF가 계산됐어야 함(기준 FCF = 마지막 연도 180-50=130)
        assert body["dcf"] is not None
        assert body["dcf"]["fair_value_per_share"] is not None
        assert "sensitivity_grid" in body["dcf"]

        assert body["financials"]["asset_id"] == "TEST"
        assert len(body["financials"]["annual"]) == 4

    def test_financial_sector_uses_total_assets_and_roa(self, tmp_path: Path) -> None:
        annual = (
            AnnualFinancials(fiscal_year=2022, total_assets=Decimal(660_000_000_000_000)),
            AnnualFinancials(fiscal_year=2023, total_assets=Decimal(691_795_333_000_000)),
            AnnualFinancials(fiscal_year=2024, total_assets=Decimal(739_764_256_000_000)),
            AnnualFinancials(
                fiscal_year=2025,
                total_assets=Decimal(786_013_485_000_000),
                net_income=Decimal(5_084_519_000_000),
            ),
        )
        provider = _FakeProvider(
            AnnualFinancialsResult(asset_id="055550", data_source="fake", annual=annual)
        )
        client = _client(tmp_path, provider, market="KR")
        payload = {
            **_BASE_PAYLOAD,
            "asset_id": "055550",
            "market": "KR",
            "is_financial": True,
            "roa_vs_industry_pp": "0.0005",
            "gross_margin_vs_industry_pp": None,
            "debt_ratio": None,
        }
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        body = response.json()

        growth = next(c for c in body["score"]["categories"] if c["category"] == "성장성")
        assert growth["items"][0]["metric"] == "총자산 3Y CAGR(금융업 대체지표)"

        comp = next(c for c in body["score"]["categories"] if c["category"] == "경쟁력")
        roa_item = next(i for i in comp["items"] if "ROA" in i["metric"])
        assert roa_item["score"] == "4"  # ±0.2%p 이내

        fin = next(c for c in body["score"]["categories"] if c["category"] == "재무")
        debt_item = next(i for i in fin["items"] if i["metric"] == "부채비율")
        assert debt_item["bucket"] == "금융업 예외"

    def test_relative_valuation_computed_when_inputs_provided(self, tmp_path: Path) -> None:
        provider = _FakeProvider(
            AnnualFinancialsResult(
                asset_id="TEST", data_source="fake", annual=_NON_FINANCIAL_ANNUAL
            )
        )
        client = _client(tmp_path, provider)
        payload = {
            **_BASE_PAYLOAD,
            "per_band_percentile": "0.15",
            "pbr_band_percentile": "0.50",
            "peg": "0.8",
        }
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        body = response.json()

        assert body["relative_valuation"]["score"] == "8.50"
        assert body["relative_valuation"]["missing"] == []

        valuation = next(c for c in body["score"]["categories"] if c["category"] == "밸류에이션")
        rel_item = next(i for i in valuation["items"] if "상대지표" in i["metric"])
        assert rel_item["value"] == "8.50"
        assert rel_item["note"] == ""

    def test_relative_valuation_stays_missing_when_no_inputs_provided(self, tmp_path: Path) -> None:
        """세 입력이 전부 없으면 0점짜리 상대지표가 아니라 '미산출'로 표시돼야 한다
        (데이터 누락을 숨기지 않는다)."""
        provider = _FakeProvider(
            AnnualFinancialsResult(
                asset_id="TEST", data_source="fake", annual=_NON_FINANCIAL_ANNUAL
            )
        )
        client = _client(tmp_path, provider)
        response = client.post("/api/equity-score", json=_BASE_PAYLOAD)
        assert response.status_code == 200
        body = response.json()

        valuation = next(c for c in body["score"]["categories"] if c["category"] == "밸류에이션")
        rel_item = next(i for i in valuation["items"] if "상대지표" in i["metric"])
        assert rel_item["value"] == "—"
        assert rel_item["bucket"] == "미산출"
        assert rel_item["score"] == "0"

    def test_roe_auto_fills_from_controlling_interest_equity_when_omitted(
        self, tmp_path: Path
    ) -> None:
        """roe를 요청에서 생략하면 자동조회된 재무제표(controlling_interest_equity 기준)로
        계산한 값을 써야 한다 — total_equity(총자본)가 아니라 지배주주지분 기준."""
        annual = (
            AnnualFinancials(
                fiscal_year=2025,
                net_income=Decimal("5084519000000"),
                total_equity=Decimal("60372324000000"),
                controlling_interest_equity=Decimal("38450000000000"),
            ),
        )
        provider = _FakeProvider(
            AnnualFinancialsResult(asset_id="TEST", data_source="fake", annual=annual)
        )
        client = _client(tmp_path, provider)
        payload = {**_BASE_PAYLOAD, "roe": None}
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        body = response.json()

        fin = next(c for c in body["score"]["categories"] if c["category"] == "재무")
        roe_item = next(i for i in fin["items"] if i["metric"] == "ROE")
        assert roe_item["value"] == "0.1322"
        assert body["growth_metrics"]["roe_latest"] == "0.1322"

    def test_debt_ratio_auto_fills_from_financials_when_omitted(self, tmp_path: Path) -> None:
        """debt_ratio를 요청에서 생략하면 이미 조회된 total_debt/total_equity로
        자동 계산한 값을 써야 한다 — 수동 입력만 받아 '데이터 누락 0점' 처리하지 않는다."""
        annual = (
            AnnualFinancials(fiscal_year=2025, total_debt=Decimal(600), total_equity=Decimal(400)),
        )
        provider = _FakeProvider(
            AnnualFinancialsResult(asset_id="TEST", data_source="fake", annual=annual)
        )
        client = _client(tmp_path, provider)
        payload = {**_BASE_PAYLOAD, "debt_ratio": None}
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        body = response.json()

        fin = next(c for c in body["score"]["categories"] if c["category"] == "재무")
        debt_item = next(i for i in fin["items"] if i["metric"] == "부채비율(총부채기준)")
        assert debt_item["value"] == "1.5000"
        assert body["growth_metrics"]["debt_ratio_latest"] == "1.5000"

    def test_missing_shares_outstanding_keeps_enterprise_value_drops_per_share_only(
        self, tmp_path: Path
    ) -> None:
        """shares_outstanding 없이는 주당 적정가·트리거 구간을 계산할 수 없지만,
        기업가치·자기자본가치는 발행주식수와 무관하게 유효하다 — 이것까지 통째로
        버리면(dcf.error) '데이터가 없어서 이 도구가 의미없다'는 오해를 만든다."""
        provider = _FakeProvider(
            AnnualFinancialsResult(
                asset_id="TEST", data_source="fake", annual=_NON_FINANCIAL_ANNUAL
            )
        )
        client = _client(tmp_path, provider)
        payload = {**_BASE_PAYLOAD, "shares_outstanding": None}
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        dcf = response.json()["dcf"]
        assert "error" not in dcf
        assert dcf["enterprise_value"] is not None
        assert dcf["equity_value"] is not None
        assert dcf["fair_value_per_share"] is None
        assert dcf["trigger_zones"] is None
        assert dcf["trigger_zones_unavailable_reason"] is not None

    def test_current_price_auto_fetched_when_omitted(self, tmp_path: Path) -> None:
        """종목 심볼만 입력해도 DCF 괴리율까지 나오도록, current_price 미입력 시
        시세 공급자에서 자동조회한 값을 쓴다."""
        provider = _FakeProvider(
            AnnualFinancialsResult(
                asset_id="TEST", data_source="fake", annual=_NON_FINANCIAL_ANNUAL
            )
        )
        quote_provider = _FakeQuoteProvider(
            quotes={
                "TEST": Quote(
                    symbol="TEST",
                    quote_date=date(2026, 7, 18),
                    close=Decimal("50"),
                    currency=Currency.USD,
                )
            }
        )
        client = _client(tmp_path, provider, price_provider=quote_provider)
        payload = {**_BASE_PAYLOAD, "current_price": None}
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        body = response.json()

        assert body["market_data"]["current_price"] == "50.00"
        assert body["market_data"]["fetch_errors"] == []
        assert body["dcf"]["gap"] is not None

    def test_current_price_fetch_failure_recorded_but_does_not_crash(self, tmp_path: Path) -> None:
        provider = _FakeProvider(
            AnnualFinancialsResult(
                asset_id="TEST", data_source="fake", annual=_NON_FINANCIAL_ANNUAL
            )
        )
        client = _client(tmp_path, provider, price_provider=_FailingQuoteProvider())
        payload = {**_BASE_PAYLOAD, "current_price": None}
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        body = response.json()

        assert body["market_data"]["current_price"] is None
        assert body["market_data"]["fetch_errors"]
        assert body["dcf"]["gap"] is None

    def test_kr_market_price_tries_ks_suffix_then_kq(self, tmp_path: Path) -> None:
        provider = _FakeProvider(
            AnnualFinancialsResult(
                asset_id="005930", data_source="fake", annual=_NON_FINANCIAL_ANNUAL
            )
        )
        quote_provider = _FakeQuoteProvider(
            quotes={
                "005930.KQ": Quote(
                    symbol="005930.KQ",
                    quote_date=date(2026, 7, 18),
                    close=Decimal("70000"),
                    currency=Currency.KRW,
                )
            }
        )
        client = _client(tmp_path, provider, market="KR", price_provider=quote_provider)
        payload = {
            **_BASE_PAYLOAD,
            "asset_id": "005930",
            "market": "KR",
            "current_price": None,
        }
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        assert response.json()["market_data"]["current_price"] == "70000.00"

    def test_shares_outstanding_auto_fetched_from_financials_when_omitted(
        self, tmp_path: Path
    ) -> None:
        """발행주식수를 요청에서 생략하면 재무제표 조회 결과(shares_outstanding)로
        자동 채운 값을 써야 한다 — 수동 입력 없이도 주당 적정가가 나와야 한다."""
        annual = _NON_FINANCIAL_ANNUAL[:-1] + (
            AnnualFinancials(
                fiscal_year=2025,
                revenue=Decimal(1331),
                eps=Decimal(13),
                operating_cash_flow=Decimal(180),
                capex=Decimal(50),
                shares_outstanding=Decimal(100),
            ),
        )
        provider = _FakeProvider(
            AnnualFinancialsResult(asset_id="TEST", data_source="fake", annual=annual)
        )
        client = _client(tmp_path, provider)
        payload = {**_BASE_PAYLOAD, "shares_outstanding": None}
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        body = response.json()

        assert body["market_data"]["shares_outstanding"] == "100"
        assert body["dcf"]["fair_value_per_share"] is not None

    def test_net_debt_auto_computed_from_total_debt_and_cash_when_omitted(
        self, tmp_path: Path
    ) -> None:
        """순부채를 생략하면 이미 조회된 총부채-현금으로 자동 계산해야 한다 — 무작정
        0으로 방치하면 순부채가 큰 회사는 기업가치가 왜곡된다."""
        annual = _NON_FINANCIAL_ANNUAL[:-1] + (
            AnnualFinancials(
                fiscal_year=2025,
                revenue=Decimal(1331),
                eps=Decimal(13),
                operating_cash_flow=Decimal(180),
                capex=Decimal(50),
                total_debt=Decimal(500),
                cash=Decimal(120),
            ),
        )
        provider = _FakeProvider(
            AnnualFinancialsResult(asset_id="TEST", data_source="fake", annual=annual)
        )
        client = _client(tmp_path, provider)
        payload = {**_BASE_PAYLOAD, "net_debt": None}
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        body = response.json()

        assert body["dcf"]["net_debt_used"] == "380"  # 500 - 120
        assert not any("순부채" in e for e in body["market_data"]["fetch_errors"])

    def test_net_debt_explicit_value_not_overridden(self, tmp_path: Path) -> None:
        annual = _NON_FINANCIAL_ANNUAL[:-1] + (
            AnnualFinancials(
                fiscal_year=2025,
                revenue=Decimal(1331),
                eps=Decimal(13),
                operating_cash_flow=Decimal(180),
                capex=Decimal(50),
                total_debt=Decimal(500),
                cash=Decimal(120),
            ),
        )
        provider = _FakeProvider(
            AnnualFinancialsResult(asset_id="TEST", data_source="fake", annual=annual)
        )
        client = _client(tmp_path, provider)
        payload = {**_BASE_PAYLOAD, "net_debt": "999"}
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        assert response.json()["dcf"]["net_debt_used"] == "999"

    def test_net_debt_falls_back_to_zero_with_note_when_total_debt_or_cash_missing(
        self, tmp_path: Path
    ) -> None:
        provider = _FakeProvider(
            AnnualFinancialsResult(
                asset_id="TEST", data_source="fake", annual=_NON_FINANCIAL_ANNUAL
            )
        )
        client = _client(tmp_path, provider)
        payload = {**_BASE_PAYLOAD, "net_debt": None}
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["dcf"]["net_debt_used"] == "0"
        assert body["market_data"]["fetch_errors"]

    def test_growth_path_auto_derived_from_historical_revenue_cagr_when_omitted(
        self, tmp_path: Path
    ) -> None:
        """예측기간 성장률을 생략하면 매출 3Y CAGR(10% 정확히, _NON_FINANCIAL_ANNUAL 기준)
        에서 영구성장률(2.5%)까지 선형으로 체감하는 5개년 경로를 자동 산출해야 한다."""
        provider = _FakeProvider(
            AnnualFinancialsResult(
                asset_id="TEST", data_source="fake", annual=_NON_FINANCIAL_ANNUAL
            )
        )
        client = _client(tmp_path, provider)
        payload = {**_BASE_PAYLOAD, "growth_path": None}
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        body = response.json()

        used = [Decimal(v) for v in body["dcf"]["growth_path_used"]]
        assert len(used) == 5
        assert abs(used[0] - Decimal("0.10")) < Decimal("0.0001")  # 매출 3Y CAGR 시작점
        assert abs(used[-1] - Decimal("0.025")) < Decimal("0.0001")  # 영구성장률 도착점
        assert used[0] > used[1] > used[2] > used[3] > used[4]  # 선형 체감

    def test_growth_path_explicit_value_not_overridden(self, tmp_path: Path) -> None:
        provider = _FakeProvider(
            AnnualFinancialsResult(
                asset_id="TEST", data_source="fake", annual=_NON_FINANCIAL_ANNUAL
            )
        )
        client = _client(tmp_path, provider)
        response = client.post("/api/equity-score", json=_BASE_PAYLOAD)
        assert response.status_code == 200
        body = response.json()
        assert body["dcf"]["growth_path_used"] == ["0.1000", "0.1000", "0.1000", "0.1000", "0.1000"]

    def test_growth_path_falls_back_to_static_default_when_no_historical_cagr(
        self, tmp_path: Path
    ) -> None:
        """과거 매출 CAGR 자체가 없으면(데이터 부족) 어쩔 수 없이 일반적인 기본값을
        쓰되, 그 사실을 fetch_errors로 명시해야 한다(조용히 넘어가지 않는다)."""
        annual = (
            AnnualFinancials(
                fiscal_year=2025,
                revenue=Decimal(1000),
                eps=Decimal(10),
                operating_cash_flow=Decimal(180),
                capex=Decimal(50),
            ),
        )
        provider = _FakeProvider(
            AnnualFinancialsResult(asset_id="TEST", data_source="fake", annual=annual)
        )
        client = _client(tmp_path, provider)
        payload = {**_BASE_PAYLOAD, "growth_path": None}
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["dcf"]["growth_path_used"] == ["0.1000", "0.1000", "0.0800", "0.0800", "0.0800"]
        assert body["market_data"]["fetch_errors"]

    def test_growth_path_uses_total_assets_cagr_for_financial_sector(self, tmp_path: Path) -> None:
        """금융업은 매출 개념이 없으므로(company_analysis_rules.md 3-1), 성장경로
        자동산출도 매출 CAGR이 아니라 총자산 3Y CAGR을 근거로 삼아야 한다."""
        annual = (
            AnnualFinancials(
                fiscal_year=2022,
                total_assets=Decimal(1000),
                net_income=Decimal(50),
                operating_cash_flow=Decimal(180),
                capex=Decimal(50),
            ),
            AnnualFinancials(
                fiscal_year=2023,
                total_assets=Decimal(1100),
                net_income=Decimal(55),
                operating_cash_flow=Decimal(180),
                capex=Decimal(50),
            ),
            AnnualFinancials(
                fiscal_year=2024,
                total_assets=Decimal(1210),
                net_income=Decimal(60),
                operating_cash_flow=Decimal(180),
                capex=Decimal(50),
            ),
            AnnualFinancials(
                fiscal_year=2025,
                total_assets=Decimal(1331),
                net_income=Decimal(65),
                operating_cash_flow=Decimal(180),
                capex=Decimal(50),
            ),
        )
        provider = _FakeProvider(
            AnnualFinancialsResult(asset_id="TEST", data_source="fake", annual=annual)
        )
        client = _client(tmp_path, provider)
        payload = {
            **_BASE_PAYLOAD,
            "growth_path": None,
            "is_financial": True,
            "roa_vs_industry_pp": "0.001",
            "gross_margin_vs_industry_pp": None,
        }
        response = client.post("/api/equity-score", json=payload)
        assert response.status_code == 200
        body = response.json()
        used = [Decimal(v) for v in body["dcf"]["growth_path_used"]]
        assert abs(used[0] - Decimal("0.10")) < Decimal("0.0001")  # 총자산 3Y CAGR 시작점

    def test_missing_base_fcf_skips_dcf_but_still_scores(self, tmp_path: Path) -> None:
        annual = (AnnualFinancials(fiscal_year=2025, revenue=Decimal(1000)),)
        provider = _FakeProvider(
            AnnualFinancialsResult(asset_id="TEST", data_source="fake", annual=annual)
        )
        client = _client(tmp_path, provider)
        response = client.post("/api/equity-score", json=_BASE_PAYLOAD)
        assert response.status_code == 200
        body = response.json()
        assert body["dcf"] is None

    def test_invalid_decimal_returns_400(self, tmp_path: Path) -> None:
        provider = _FakeProvider(
            AnnualFinancialsResult(
                asset_id="TEST", data_source="fake", annual=_NON_FINANCIAL_ANNUAL
            )
        )
        client = _client(tmp_path, provider)
        response = client.post("/api/equity-score", json={**_BASE_PAYLOAD, "wacc": "not-a-number"})
        assert response.status_code == 400
        assert "wacc" in response.json()["detail"]

    def test_provider_error_returns_502(self, tmp_path: Path) -> None:
        from pams.equity.domain.financial_statement import FinancialStatementProviderError

        @dataclass(frozen=True, slots=True)
        class _FailingProvider:
            def annual_financials(self, asset_id: str, *, years: int = 4) -> AnnualFinancialsResult:
                raise FinancialStatementProviderError("SEC 서버 응답 없음")

        client = _client(tmp_path, _FailingProvider())
        response = client.post("/api/equity-score", json=_BASE_PAYLOAD)
        assert response.status_code == 502

    def test_unknown_market_without_injected_provider_returns_400(self, tmp_path: Path) -> None:
        app = create_app(data_dir=tmp_path)
        client = TestClient(app)
        response = client.post("/api/equity-score", json={**_BASE_PAYLOAD, "market": "XX"})
        assert response.status_code == 422  # Literal["US","KR"] 검증에서 이미 걸러짐

    def test_equity_score_leaves_audit_event(self, tmp_path: Path) -> None:
        provider = _FakeProvider(
            AnnualFinancialsResult(
                asset_id="TEST", data_source="fake", annual=_NON_FINANCIAL_ANNUAL
            )
        )
        client = _client(tmp_path, provider)
        client.post("/api/equity-score", json=_BASE_PAYLOAD)
        audit_log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "equity_score.computed" in audit_log
