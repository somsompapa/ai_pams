"""DartFinancialStatementProvider 통합 테스트 (HTTP는 MockTransport로 목킹).

ai_stock 프로젝트에서 로컬 실측(HYBE 352820, 신한지주 055550)으로 잡은 버그의
회귀 테스트를 포함: 계정명 공백 불일치, total_equity 역산 폴백, 은행업 cash 대체 라벨.
"""

import io
import zipfile
from decimal import Decimal

import httpx
import pytest

from pams.equity.domain.financial_statement import (
    FinancialStatementProvider,
    FinancialStatementProviderError,
)
from pams.equity.infrastructure import DartFinancialStatementProvider

_CORP_CODE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list><corp_code>00164742</corp_code><corp_name>HYBE</corp_name><stock_code>352820</stock_code></list>
  <list><corp_code>00382199</corp_code><corp_name>Shinhan</corp_name><stock_code>055550</stock_code></list>
</result>"""


def _corp_code_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", _CORP_CODE_XML)
    return buf.getvalue()


def _dart_item(account_nm: str, amount: str) -> dict:
    return {"account_nm": account_nm, "thstrm_amount": amount}


class TestDartFinancialStatementProvider:
    def make(self, handler, tmp_path) -> DartFinancialStatementProvider:  # type: ignore[no-untyped-def]
        return DartFinancialStatementProvider(
            api_key="test-key",
            corp_code_cache_path=tmp_path / "corp_code_cache.xml",
            transport=httpx.MockTransport(handler),
        )

    def test_satisfies_port(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        assert isinstance(
            self.make(lambda _r: httpx.Response(200), tmp_path), FinancialStatementProvider
        )

    def test_missing_api_key_rejected(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        provider = DartFinancialStatementProvider(
            api_key="", corp_code_cache_path=tmp_path / "x.xml"
        )
        with pytest.raises(FinancialStatementProviderError, match="API 키"):
            provider.annual_financials("352820")

    def test_unknown_stock_code_raises(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        def handler(request: httpx.Request) -> httpx.Response:
            if "corpCode" in str(request.url):
                return httpx.Response(200, content=_corp_code_zip_bytes())
            return httpx.Response(200, json={"status": "013", "message": "no data"})

        provider = self.make(handler, tmp_path)
        with pytest.raises(FinancialStatementProviderError, match="corp_code"):
            provider.annual_financials("999999")

    def test_account_name_whitespace_mismatch_is_normalized(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """HYBE 실측 버그 재현: '영업활동으로 인한 현금흐름'처럼 공백 섞인 실제 계정명이
        후보('영업활동으로인한현금흐름')와 정규화 후에는 일치해야 한다."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "corpCode" in str(request.url):
                return httpx.Response(200, content=_corp_code_zip_bytes())
            year = request.url.params.get("bsns_year")
            if year != "2025":
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            return httpx.Response(
                200,
                json={
                    "status": "000",
                    "list": [_dart_item("영업활동으로 인한 현금흐름", "529,846,000,000")],
                },
            )

        provider = self.make(handler, tmp_path)
        result = provider.annual_financials("352820", years=1)
        assert len(result.annual) == 1
        assert result.annual[0].operating_cash_flow == Decimal("529846000000")

    def test_total_equity_derived_when_account_match_fails(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """신한지주 실측 버그 재현: '자본총계' 매칭 실패 시 자산총계-부채총계로 역산해야
        하고, total_equity_derived 플래그가 True로 표시돼야 한다(투명성)."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "corpCode" in str(request.url):
                return httpx.Response(200, content=_corp_code_zip_bytes())
            year = request.url.params.get("bsns_year")
            if year != "2025":
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            return httpx.Response(
                200,
                json={
                    "status": "000",
                    "list": [
                        _dart_item("자산총계", "786,013,485,000,000"),
                        _dart_item("부채총계", "725,641,161,000,000"),
                        # '자본총계' 계정 자체가 응답에 없음(실측 상황 재현)
                    ],
                },
            )

        provider = self.make(handler, tmp_path)
        result = provider.annual_financials("055550", years=1)
        row = result.annual[0]
        assert row.total_equity == Decimal("60372324000000")
        assert row.total_equity_derived is True

    def test_controlling_interest_equity_matched_separately_from_total_equity(
        self, tmp_path
    ) -> None:  # type: ignore[no-untyped-def]
        """ROE 분모 버그 재현: total_equity(자본총계, 비지배지분 포함)와
        controlling_interest_equity(지배기업소유주지분)는 다른 계정이며 둘 다 채워져야
        한다 — total_equity를 ROE 분모로 대체하면 안 된다(실측: 신한지주 8.5점 밴드 차이)."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "corpCode" in str(request.url):
                return httpx.Response(200, content=_corp_code_zip_bytes())
            year = request.url.params.get("bsns_year")
            if year != "2025":
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            return httpx.Response(
                200,
                json={
                    "status": "000",
                    "list": [
                        _dart_item("자본총계", "60,372,324,000,000"),
                        _dart_item("지배기업소유주지분", "38,450,000,000,000"),
                    ],
                },
            )

        provider = self.make(handler, tmp_path)
        result = provider.annual_financials("055550", years=1)
        row = result.annual[0]
        assert row.total_equity == Decimal("60372324000000")
        assert row.controlling_interest_equity == Decimal("38450000000000")

    def test_financial_sector_cash_fallback_label(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """신한지주 실측 버그 재현: BS 라벨('현금및현금성자산') 없이 CF표 라벨
        ('기말의 현금 및 현금성자산')만 있어도 cash가 매칭돼야 한다."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "corpCode" in str(request.url):
                return httpx.Response(200, content=_corp_code_zip_bytes())
            year = request.url.params.get("bsns_year")
            if year != "2025":
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            return httpx.Response(
                200,
                json={
                    "status": "000",
                    "list": [_dart_item("기말의 현금 및 현금성자산", "12,345,678,900")],
                },
            )

        provider = self.make(handler, tmp_path)
        result = provider.annual_financials("055550", years=1)
        assert result.annual[0].cash == Decimal("12345678900")

    def test_partial_year_failure_recorded_not_fatal(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """일부 연도 조회가 실패해도 전체를 실패시키지 않고, 나머지 연도 + 실패 사유를
        함께 반환해야 한다(결측 사실을 숨기지 않음)."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "corpCode" in str(request.url):
                return httpx.Response(200, content=_corp_code_zip_bytes())
            year = request.url.params.get("bsns_year")
            if year == "2025":
                return httpx.Response(
                    200, json={"status": "000", "list": [_dart_item("매출액", "1,000")]}
                )
            return httpx.Response(
                200, json={"status": "013", "message": "조회된 데이타가 없습니다."}
            )

        provider = self.make(handler, tmp_path)
        result = provider.annual_financials("352820", years=4)
        assert len(result.annual) == 1
        assert result.annual[0].fiscal_year == 2025
        assert len(result.fetch_errors) == 3
        assert all("013" in err for err in result.fetch_errors)

    def test_corp_code_map_cached_to_disk_not_refetched(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        calls = {"corp_code": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if "corpCode" in str(request.url):
                calls["corp_code"] += 1
                return httpx.Response(200, content=_corp_code_zip_bytes())
            return httpx.Response(200, json={"status": "013", "message": "no data"})

        cache_path = tmp_path / "corp_code_cache.xml"
        provider = DartFinancialStatementProvider(
            api_key="test-key",
            corp_code_cache_path=cache_path,
            transport=httpx.MockTransport(handler),
        )
        provider.annual_financials("352820", years=1)
        provider.annual_financials("055550", years=1)
        assert calls["corp_code"] == 1
        assert cache_path.exists()


class TestSharesOutstanding:
    """종목 심볼만 입력해도 DCF 주당 적정가가 나오도록, 재무제표와 별도 API
    (stockTotqySttus)로 발행주식수를 조회한다."""

    def make(self, handler, tmp_path) -> DartFinancialStatementProvider:  # type: ignore[no-untyped-def]
        return DartFinancialStatementProvider(
            api_key="test-key",
            corp_code_cache_path=tmp_path / "corp_code_cache.xml",
            transport=httpx.MockTransport(handler),
        )

    def test_distributed_shares_preferred_from_total_row(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "corpCode" in url:
                return httpx.Response(200, content=_corp_code_zip_bytes())
            if "stockTotqySttus" in url:
                return httpx.Response(
                    200,
                    json={
                        "status": "000",
                        "list": [
                            {
                                "se": "보통주",
                                "istc_totqy": "100,000,000",
                                "distb_stock_co": "99,000,000",
                            },
                            {
                                "se": "우선주",
                                "istc_totqy": "1,000,000",
                                "distb_stock_co": "900,000",
                            },
                            {
                                "se": "합계",
                                "istc_totqy": "101,000,000",
                                "distb_stock_co": "99,900,000",
                            },
                        ],
                    },
                )
            year = request.url.params.get("bsns_year")
            if year != "2025":
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            return httpx.Response(
                200, json={"status": "000", "list": [_dart_item("매출액", "1,000")]}
            )

        provider = self.make(handler, tmp_path)
        result = provider.annual_financials("352820", years=1)
        assert result.annual[0].shares_outstanding == Decimal("99900000")

    def test_falls_back_to_issued_shares_when_distributed_missing(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "corpCode" in url:
                return httpx.Response(200, content=_corp_code_zip_bytes())
            if "stockTotqySttus" in url:
                return httpx.Response(
                    200,
                    json={
                        "status": "000",
                        "list": [{"se": "합계", "istc_totqy": "101,000,000"}],
                    },
                )
            year = request.url.params.get("bsns_year")
            if year != "2025":
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            return httpx.Response(
                200, json={"status": "000", "list": [_dart_item("매출액", "1,000")]}
            )

        provider = self.make(handler, tmp_path)
        result = provider.annual_financials("352820", years=1)
        assert result.annual[0].shares_outstanding == Decimal("101000000")

    def test_fetch_failure_leaves_shares_outstanding_none_not_fatal(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """발행주식수 조회가 실패해도 나머지 재무제표는 정상 반환돼야 한다(부분 실패
        허용) — DCF는 여전히 기업가치까지는 계산 가능해야 하므로 전체를 실패시키지 않는다."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "corpCode" in url:
                return httpx.Response(200, content=_corp_code_zip_bytes())
            if "stockTotqySttus" in url:
                return httpx.Response(500, json={"status": "500", "message": "error"})
            year = request.url.params.get("bsns_year")
            if year != "2025":
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            return httpx.Response(
                200, json={"status": "000", "list": [_dart_item("매출액", "1,000")]}
            )

        provider = self.make(handler, tmp_path)
        result = provider.annual_financials("352820", years=1)
        assert result.annual[0].revenue == Decimal("1000")
        assert result.annual[0].shares_outstanding is None


class TestEpsFallback:
    """삼성전자(005930) 실사용 사례 재현: EPS 계정명 매칭이 실패해도 순이익÷발행주식수로
    역산해야 한다(항등식 기반, total_equity_derived와 같은 관례) — 임의추정 금지는
    지키면서 이미 조회된 값으로 계산 가능한 항목까지 '데이터 누락' 처리하지 않는다."""

    def make(self, handler, tmp_path) -> DartFinancialStatementProvider:  # type: ignore[no-untyped-def]
        return DartFinancialStatementProvider(
            api_key="test-key",
            corp_code_cache_path=tmp_path / "corp_code_cache.xml",
            transport=httpx.MockTransport(handler),
        )

    def test_eps_derived_from_net_income_and_shares_when_account_missing(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "corpCode" in url:
                return httpx.Response(200, content=_corp_code_zip_bytes())
            if "stockTotqySttus" in url:
                return httpx.Response(
                    200,
                    json={"status": "000", "list": [{"se": "합계", "distb_stock_co": "5,000"}]},
                )
            year = request.url.params.get("bsns_year")
            if year != "2025":
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            return httpx.Response(
                200,
                json={
                    "status": "000",
                    # '기본주당이익' 등 EPS 계정 자체가 응답에 없음(실측 상황 재현) —
                    # 순이익만 있음
                    "list": [_dart_item("당기순이익", "1,000,000")],
                },
            )

        provider = self.make(handler, tmp_path)
        result = provider.annual_financials("352820", years=1)
        row = result.annual[0]
        assert row.eps == Decimal("200")  # 1,000,000 / 5,000
        assert row.eps_derived is True

    def test_direct_eps_account_preferred_over_derived(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "corpCode" in url:
                return httpx.Response(200, content=_corp_code_zip_bytes())
            if "stockTotqySttus" in url:
                return httpx.Response(
                    200,
                    json={"status": "000", "list": [{"se": "합계", "distb_stock_co": "5,000"}]},
                )
            year = request.url.params.get("bsns_year")
            if year != "2025":
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            return httpx.Response(
                200,
                json={
                    "status": "000",
                    "list": [
                        _dart_item("당기순이익", "1,000,000"),
                        _dart_item("기본주당이익", "150"),
                    ],
                },
            )

        provider = self.make(handler, tmp_path)
        result = provider.annual_financials("352820", years=1)
        row = result.annual[0]
        assert row.eps == Decimal("150")  # 공시된 값 그대로, 역산하지 않음
        assert row.eps_derived is False

    def test_eps_stays_none_when_shares_outstanding_also_missing(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """발행주식수까지 조회 실패하면 역산 자체가 불가능하므로 정직하게 None으로
        남는다(임의추정 금지 — 데이터가 진짜 없을 때는 없다고 해야 한다)."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "corpCode" in url:
                return httpx.Response(200, content=_corp_code_zip_bytes())
            if "stockTotqySttus" in url:
                return httpx.Response(500, json={"status": "500", "message": "error"})
            year = request.url.params.get("bsns_year")
            if year != "2025":
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            return httpx.Response(
                200, json={"status": "000", "list": [_dart_item("당기순이익", "1,000,000")]}
            )

        provider = self.make(handler, tmp_path)
        result = provider.annual_financials("352820", years=1)
        row = result.annual[0]
        assert row.eps is None
        assert row.eps_derived is False


class TestIncomeTaxExpense:
    """ROIC 유효세율 계산 전용 계정(법인세비용) 조회 — growth_metrics.py의
    roic_latest 산식이 이 필드에 의존한다."""

    def make(self, handler, tmp_path) -> DartFinancialStatementProvider:  # type: ignore[no-untyped-def]
        return DartFinancialStatementProvider(
            api_key="test-key",
            corp_code_cache_path=tmp_path / "corp_code_cache.xml",
            transport=httpx.MockTransport(handler),
        )

    def test_extracts_income_tax_expense_account(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "corpCode" in url:
                return httpx.Response(200, content=_corp_code_zip_bytes())
            if "stockTotqySttus" in url:
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            year = request.url.params.get("bsns_year")
            if year != "2025":
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            return httpx.Response(
                200,
                json={
                    "status": "000",
                    "list": [_dart_item("법인세비용", "250,000,000")],
                },
            )

        provider = self.make(handler, tmp_path)
        result = provider.annual_financials("352820", years=1)
        assert result.annual[0].income_tax_expense == Decimal("250000000")
