"""SEC EDGAR XBRL companyfacts 어댑터 (FinancialStatementProvider 구현).

미국 상장기업 재무제표를 무료·키 불필요로 제공한다(연락처 포함 User-Agent만 필요 —
SEC 요구사항, 없으면 403). ai_stock 프로젝트에서 로컬 실측(AAPL)으로 검증된 두 버그를
그대로 반영한다:

  1. instant(특정 시점) 계정(Assets/StockholdersEquity/Liabilities 등)은 하나의 10-K가
     당기말·전기말 두 시점을 같은 fy로 함께 보고할 수 있다. end(보고 시점) 날짜가
     가장 늦은 값을 채택한다 — 아니면 먼저 온 값이 나중 값에 덮어써져 엉뚱한 시점이
     남는다(실측: AAPL FY2025 total_equity가 잘못된 시점 값으로 나온 사례).
  2. 후보 태그는 "먼저 데이터가 있는 것에서 멈추기"가 아니라 전체를 병합한다 — 회계기준
     변경으로 태그가 바뀐 회사(AAPL은 "Revenues"를 2018년 이전까지만 쓰고 이후
     "RevenueFromContractWithCustomerExcludingAssessedTax"로 전환)에서 옛 태그가
     "데이터 있음"으로 먼저 걸려 최근 연도를 못 채우는 문제를 막는다.
  3. ROE 분모는 controlling_interest_equity(StockholdersEquity 태그 단독)만 쓴다 —
     total_equity처럼 비지배지분 포함 태그를 폴백으로 섞지 않는다(DART 쪽에서 발견된
     동일 문제의 재발 방지).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from pams.equity.domain.financial_statement import (
    AnnualFinancials,
    AnnualFinancialsResult,
    FinancialStatementProviderError,
)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

_TAG_CANDIDATES: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ),
    "eps": ("EarningsPerShareDiluted",),
    "net_income": ("NetIncomeLoss",),
    "operating_income": ("OperatingIncomeLoss",),
    "gross_profit": ("GrossProfit",),
    "total_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    # ⚠️ ROE 분모 전용. StockholdersEquity 하나만 본다 — 비지배지분 포함 태그를
    # 섞으면 total_equity와 같은 문제(분모 과대)가 재현된다.
    "controlling_interest_equity": ("StockholdersEquity",),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "short_term_debt": ("LongTermDebtCurrent", "ShortTermBorrowings", "DebtCurrent"),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "shares_outstanding": ("CommonStockSharesOutstanding", "CommonStockSharesIssued"),
}
_UNIT_OVERRIDES: dict[str, str] = {"eps": "USD/shares", "shares_outstanding": "shares"}


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _extract_annual(
    facts_json: dict[str, Any], tag_candidates: tuple[str, ...], unit: str
) -> dict[int, Decimal]:
    us_gaap = facts_json.get("facts", {}).get("us-gaap", {})
    result: dict[int, Decimal] = {}
    for tag in tag_candidates:
        node = us_gaap.get(tag)
        if not node:
            continue
        units = node.get("units", {})
        values = units.get(unit) or (next(iter(units.values())) if units else [])
        by_fy: dict[int, tuple[str, Decimal]] = {}
        for entry in values:
            if not (
                entry.get("form") == "10-K"
                and entry.get("fp") == "FY"
                and entry.get("fy")
                and entry.get("val") is not None
            ):
                continue
            decimal_val = _to_decimal(entry["val"])
            if decimal_val is None:
                continue
            fy = int(entry["fy"])
            end = entry.get("end", "") or ""
            prev = by_fy.get(fy)
            if prev is None or end > prev[0]:
                by_fy[fy] = (end, decimal_val)
        for fy, (_end, val) in by_fy.items():
            if fy not in result:  # 먼저 온 후보 태그가 이미 채운 연도는 그대로 우선
                result[fy] = val
    return result


@dataclass(frozen=True, slots=True)
class SecEdgarFinancialStatementProvider:
    contact_email: str
    timeout_seconds: float = 30.0
    transport: httpx.BaseTransport | None = None  # 테스트 주입용

    def _headers(self) -> dict[str, str]:
        if not self.contact_email.strip():
            raise FinancialStatementProviderError(
                "SEC EDGAR 호출에는 연락처 포함 User-Agent가 필수(SEC 요구사항, 없으면 403). "
                "SEC_EDGAR_CONTACT_EMAIL 설정 필요."
            )
        return {"User-Agent": f"PAMS/0.1 ({self.contact_email})"}

    def _client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport, timeout=self.timeout_seconds)

    def _ticker_to_cik(self, ticker: str) -> str:
        try:
            with self._client() as client:
                response = client.get(_TICKERS_URL, headers=self._headers())
        except httpx.HTTPError as error:
            raise FinancialStatementProviderError(
                f"SEC ticker-CIK 매핑 조회 실패: {error}"
            ) from error
        if response.status_code >= 400:
            raise FinancialStatementProviderError(
                f"SEC ticker-CIK 매핑 HTTP {response.status_code}"
            )
        try:
            data = response.json()
        except ValueError as error:
            raise FinancialStatementProviderError("SEC ticker-CIK 응답이 JSON이 아니다") from error
        for entry in data.values():
            if str(entry.get("ticker", "")).upper() == ticker.upper():
                return str(entry["cik_str"]).zfill(10)
        hint = (
            " (숫자로만 된 심볼은 SEC 미등록 해외종목일 수 있다 — 예: 한국 종목은 market=KR로 조회)"
            if ticker.isdigit()
            else ""
        )
        raise FinancialStatementProviderError(f"SEC CIK 매핑 실패: ticker={ticker}{hint}")

    def annual_financials(self, asset_id: str, *, years: int = 4) -> AnnualFinancialsResult:
        cik = self._ticker_to_cik(asset_id)
        try:
            with self._client() as client:
                response = client.get(_FACTS_URL.format(cik=cik), headers=self._headers())
        except httpx.HTTPError as error:
            raise FinancialStatementProviderError(
                f"{asset_id} SEC companyfacts 조회 실패: {error}"
            ) from error
        if response.status_code >= 400:
            raise FinancialStatementProviderError(
                f"{asset_id} SEC companyfacts HTTP {response.status_code}"
            )
        try:
            facts = response.json()
        except ValueError as error:
            raise FinancialStatementProviderError(
                f"{asset_id} SEC companyfacts 응답이 JSON이 아니다"
            ) from error

        extracted = {
            field: _extract_annual(facts, tags, _UNIT_OVERRIDES.get(field, "USD"))
            for field, tags in _TAG_CANDIDATES.items()
        }
        all_years = sorted({y for values in extracted.values() for y in values})
        recent_years = all_years[-years:] if len(all_years) > years else all_years

        rows = []
        for fy in recent_years:
            total_liabilities = extracted["total_liabilities"].get(fy)
            total_assets = extracted["total_assets"].get(fy)
            total_equity = extracted["total_equity"].get(fy)
            if fy in extracted["total_liabilities"]:
                total_debt = total_liabilities
            elif total_assets is not None and total_equity is not None:
                total_debt = total_assets - total_equity
            else:
                total_debt = None

            long_term = extracted["long_term_debt"].get(fy)
            short_term = extracted["short_term_debt"].get(fy)
            interest_bearing = (
                (long_term or Decimal(0)) + (short_term or Decimal(0))
                if (fy in extracted["long_term_debt"] or fy in extracted["short_term_debt"])
                else None
            )

            rows.append(
                AnnualFinancials(
                    fiscal_year=fy,
                    revenue=extracted["revenue"].get(fy),
                    operating_income=extracted["operating_income"].get(fy),
                    net_income=extracted["net_income"].get(fy),
                    eps=extracted["eps"].get(fy),
                    gross_profit=extracted["gross_profit"].get(fy),
                    total_assets=total_assets,
                    total_equity=total_equity,
                    controlling_interest_equity=extracted["controlling_interest_equity"].get(fy),
                    total_debt=total_debt,
                    interest_bearing_debt=interest_bearing,
                    cash=extracted["cash"].get(fy),
                    operating_cash_flow=extracted["operating_cash_flow"].get(fy),
                    capex=extracted["capex"].get(fy),
                    shares_outstanding=extracted["shares_outstanding"].get(fy),
                )
            )
        return AnnualFinancialsResult(
            asset_id=asset_id.upper(),
            data_source="SEC EDGAR XBRL companyfacts",
            annual=tuple(rows),
        )
