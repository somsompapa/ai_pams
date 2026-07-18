"""POST /api/equity-score 통합 테스트. 실네트워크 없이 페이크 FinancialStatementProvider 주입."""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from pams.equity.domain.financial_statement import AnnualFinancials, AnnualFinancialsResult
from pams.interfaces.api.app import create_app

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


def _client(tmp_path: Path, provider: _FakeProvider, market: str = "US") -> TestClient:
    app = create_app(data_dir=tmp_path, equity_providers={market: provider})
    return TestClient(app)


_BASE_PAYLOAD = {
    "asset_id": "TEST",
    "market": "US",
    "wacc": "0.085",
    "terminal_growth": "0.025",
    "growth_path": ["0.1", "0.1", "0.1", "0.1", "0.1"],
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
