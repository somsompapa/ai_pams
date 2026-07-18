"""DART Open API(전자공시시스템) 어댑터 (FinancialStatementProvider 구현).

한국 상장기업 재무제표. API 키 필요(DART_API_KEY, 무료 발급). ai_stock 프로젝트에서
로컬 실측(HYBE 352820, 신한지주 055550)으로 검증된 계정명 정규화·폴백 로직을 그대로
반영한다:

  1. 계정명에 섞인 공백("영업활동으로 인한 현금흐름" 등)이 후보 목록과 정확히 일치하지
     않아 매칭에 실패하는 문제 — 양쪽 공백을 제거하고 비교한다.
  2. "자본총계" 계정명 매칭이 실패해도 자산총계·부채총계가 있으면
     total_equity = total_assets - total_liabilities로 역산한다(항등식 기반이라
     임의 추정이 아니다).
  3. 은행지주처럼 BS 표기("현금및현금성자산") 없이 CF표 라벨("기말의 현금 및
     현금성자산")만 쓰는 경우를 위한 cash 대체 후보.
  4. ROE 분모는 total_equity(자본총계, 비지배지분 포함)가 아니라 지배기업소유주지분이어야
     한다 — DART 신한지주(055550) 실측에서 이 둘의 차이가 8.5점 밴드 하나를 넘어갈 만큼
     크다는 사실을 발견하고 별도 필드(controlling_interest_equity)로 분리했다.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

from pams.equity.domain.financial_statement import (
    AnnualFinancials,
    AnnualFinancialsResult,
    FinancialStatementProviderError,
)

_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
_FINANCIALS_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
_STOCK_TOTQY_URL = "https://opendart.fss.or.kr/api/stockTotqySttus.json"

# ⚠️ "주식의총수현황"(stockTotqySttus) 응답 필드명은 DART 공식 API 문서 기준 최선 추정이며
# 실제 응답으로 검증되지 않았다(재무제표 계정명 매칭과 달리 이 엔드포인트는 이 프로젝트에서
# 아직 실측 데이터로 확인된 적이 없다 — v1.5의 KRX 외국인수급 API와 같은 종류의 미검증 상태).
# 후보 키를 여러 개 두어 방어적으로 파싱하되(계정명 매칭과 같은 패턴), 전부 실패하면 조용히
# None을 반환한다(임의 추정 없이 "자동조회 실패" 그대로 두는 편이 잘못된 값을 채우는 것보다
# 안전하다). 실제 응답으로 검증되면 후보 목록을 정리할 것.
_DISTRIBUTED_SHARES_KEYS = ("distb_stock_co", "distb_stock_qy")
_ISSUED_SHARES_KEYS = ("istc_totqy", "isu_stock_totqy")
_SHARE_CLASS_TOTAL_LABELS = ("합계", "계")

_ACCOUNT_MAP: dict[str, tuple[str, ...]] = {
    # ⚠️ 은행/보험/증권/지주는 K-IFRS상 "매출액"·"매출총이익" 개념 자체가 없다(이자수익·
    # 수수료수익·보험수익이 각각 별도 계정). 이자수익+수수료수익 등을 합산해 흉내내지
    # 않는다 — rulebook이 정의하지 않은 산식을 코드가 발명하는 셈이라 금지 원칙 위반.
    "revenue": ("매출액", "수익(매출액)", "영업수익"),
    "operating_income": ("영업이익", "영업이익(손실)"),
    "net_income": ("당기순이익", "당기순이익(손실)", "분기순이익(손실)"),
    "eps": (
        "기본주당이익",
        "기본주당순이익",
        "주당순이익",
        "희석주당이익",
        "기본및희석주당이익",
        "기본및희석주당순이익",
    ),
    "gross_profit": ("매출총이익",),
    "total_assets": ("자산총계",),
    "total_liabilities": ("부채총계",),
    "total_equity": ("자본총계",),
    # ⚠️ ROE 분모 전용. total_equity(자본총계)는 비지배지분·신종자본증권을 포함해
    # ROE 분모로 쓰면 왜곡된다(실측: 신한지주 total_equity 60.37조 vs 이 값 38.45조).
    "controlling_interest_equity": (
        "지배기업소유주지분",
        "지배기업의소유주에게귀속되는자본",
        "지배기업의소유지분",
        "지배기업소유지분",
        "지배주주지분",
    ),
    "cash": ("현금및현금성자산", "기말의현금및현금성자산"),
    "operating_cash_flow": (
        "영업활동현금흐름",
        "영업활동으로인한현금흐름",
        "영업활동순현금흐름",
        "영업활동으로인한순현금흐름",
    ),
    "capex": ("유형자산의취득",),
    # ROIC 유효세율 계산 전용(income_tax_expense÷(net_income+income_tax_expense)).
    "income_tax_expense": ("법인세비용", "법인세비용(수익)"),
}


def _normalize(name: str) -> str:
    return (name or "").replace(" ", "").replace("　", "").strip()


def _to_decimal(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


@dataclass(frozen=True, slots=True)
class DartFinancialStatementProvider:
    api_key: str
    fs_div: str = "CFS"  # CFS=연결재무제표(기본, 대기업 권장) | OFS=별도재무제표
    corp_code_cache_path: Path = field(default_factory=lambda: Path(".dart_corp_code_cache.xml"))
    timeout_seconds: float = 30.0
    transport: httpx.BaseTransport | None = None  # 테스트 주입용

    def _client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport, timeout=self.timeout_seconds)

    def _corp_code_map(self) -> dict[str, str]:
        if self.corp_code_cache_path.exists():
            xml_bytes = self.corp_code_cache_path.read_bytes()
        else:
            try:
                with self._client() as client:
                    response = client.get(_CORP_CODE_URL, params={"crtfc_key": self.api_key})
                response.raise_for_status()
                zf = zipfile.ZipFile(io.BytesIO(response.content))
                xml_bytes = zf.read(zf.namelist()[0])
            except (httpx.HTTPError, zipfile.BadZipFile) as error:
                raise FinancialStatementProviderError(
                    f"DART corpCode.xml 조회/압축해제 실패: {error}"
                ) from error
            try:
                self.corp_code_cache_path.write_bytes(xml_bytes)
            except OSError:
                pass  # 캐시 저장 실패는 치명적이지 않음(매번 재다운로드될 뿐)

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as error:
            raise FinancialStatementProviderError(
                f"DART corpCode.xml 파싱 실패: {error}"
            ) from error
        mapping: dict[str, str] = {}
        for item in root.findall("list"):
            stock_code = (item.findtext("stock_code") or "").strip()
            corp_code = (item.findtext("corp_code") or "").strip()
            if stock_code:
                mapping[stock_code] = corp_code
        return mapping

    def _fetch_year(self, corp_code: str, year: int) -> dict[str, Any] | None:
        with self._client() as client:
            response = client.get(
                _FINANCIALS_URL,
                params={
                    "crtfc_key": self.api_key,
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": "11011",
                    "fs_div": self.fs_div,
                },
            )
        data: dict[str, Any] = response.json()
        return data

    def _fetch_shares_outstanding(self, corp_code: str, year: int) -> Decimal | None:
        """발행주식수(유통주식수 우선, 없으면 발행주식총수) 조회. 실패하면 조용히 None —
        이 값이 없어도 재무제표 나머지는 정상 반환돼야 하므로 예외를 던지지 않는다."""
        try:
            with self._client() as client:
                response = client.get(
                    _STOCK_TOTQY_URL,
                    params={
                        "crtfc_key": self.api_key,
                        "corp_code": corp_code,
                        "bsns_year": str(year),
                        "reprt_code": "11011",
                    },
                )
            data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if data.get("status") != "000":
            return None

        rows = data.get("list", [])
        total_row = next(
            (row for row in rows if _normalize(row.get("se", "")) in _SHARE_CLASS_TOTAL_LABELS),
            None,
        )
        candidate_rows = [total_row] if total_row is not None else rows
        for row in candidate_rows:
            if row is None:
                continue
            for key in _DISTRIBUTED_SHARES_KEYS + _ISSUED_SHARES_KEYS:
                value = _to_decimal(row.get(key))
                if value is not None and value > 0:
                    return value
        return None

    def annual_financials(self, asset_id: str, *, years: int = 4) -> AnnualFinancialsResult:
        if not self.api_key.strip():
            raise FinancialStatementProviderError(
                "DART API 키 필요 — DART_API_KEY 설정 또는 api_key 파라미터 전달."
            )
        corp_map = self._corp_code_map()
        corp_code = corp_map.get(asset_id)
        if not corp_code:
            raise FinancialStatementProviderError(
                f"DART corp_code 매핑 실패: stock_code={asset_id} (종목코드 확인 필요)"
            )

        this_year = date.today().year
        target_years = list(range(this_year - years, this_year))

        rows: list[AnnualFinancials] = []
        fetch_errors: list[str] = []
        for year in target_years:
            try:
                data = self._fetch_year(corp_code, year)
            except httpx.HTTPError as error:
                fetch_errors.append(f"{year}: 요청 실패 {error}")
                continue
            except ValueError as error:
                fetch_errors.append(f"{year}: 응답이 JSON이 아님 {error}")
                continue
            if data is None or data.get("status") != "000":
                status = data.get("status") if data else None
                message = data.get("message") if data else None
                fetch_errors.append(f"{year}: DART status={status} msg={message}")
                continue

            items = data.get("list", [])
            normalized = {
                idx: _normalize(it.get("account_nm") or "") for idx, it in enumerate(items)
            }
            values: dict[str, Decimal | None] = {}
            for field_name, names in _ACCOUNT_MAP.items():
                candidates = {_normalize(n) for n in names}
                value = None
                for idx, it in enumerate(items):
                    if normalized[idx] in candidates:
                        value = _to_decimal(it.get("thstrm_amount"))
                        break
                values[field_name] = value

            total_equity = values["total_equity"]
            total_equity_derived = False
            if (
                total_equity is None
                and values["total_assets"] is not None
                and values["total_liabilities"] is not None
            ):
                total_equity = values["total_assets"] - values["total_liabilities"]
                total_equity_derived = True

            shares_outstanding = self._fetch_shares_outstanding(corp_code, year)

            eps = values["eps"]
            eps_derived = False
            if (
                eps is None
                and values["net_income"] is not None
                and shares_outstanding is not None
                and shares_outstanding > 0
            ):
                # EPS 계정명 매칭 실패 시 순이익÷발행주식수로 역산(항등식 기반, 임의
                # 추정 아님) — total_equity_derived와 같은 관례. 연결 순이익 전체를 쓰므로
                # 지배주주 귀속 순이익 기준 공시 EPS와는 소폭 다를 수 있다(eps_derived로 표시).
                eps = values["net_income"] / shares_outstanding
                eps_derived = True

            rows.append(
                AnnualFinancials(
                    fiscal_year=year,
                    revenue=values["revenue"],
                    operating_income=values["operating_income"],
                    net_income=values["net_income"],
                    eps=eps,
                    eps_derived=eps_derived,
                    gross_profit=values["gross_profit"],
                    total_assets=values["total_assets"],
                    total_equity=total_equity,
                    total_equity_derived=total_equity_derived,
                    controlling_interest_equity=values["controlling_interest_equity"],
                    # v1.4 정의: 부채비율 = 총부채(DART '부채총계')/자기자본
                    total_debt=values["total_liabilities"],
                    cash=values["cash"],
                    operating_cash_flow=values["operating_cash_flow"],
                    capex=values["capex"],
                    shares_outstanding=shares_outstanding,
                    income_tax_expense=values["income_tax_expense"],
                )
            )
        return AnnualFinancialsResult(
            asset_id=asset_id,
            data_source=f"DART Open API(fnlttSinglAcntAll, fs_div={self.fs_div})",
            annual=tuple(rows),
            fetch_errors=tuple(fetch_errors),
        )
