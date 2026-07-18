"""SecEdgarFinancialStatementProvider 통합 테스트 (HTTP는 MockTransport로 목킹).

ai_stock 프로젝트에서 로컬 실측(AAPL)으로 잡은 두 버그의 회귀 테스트를 포함:
  1. instant 계정 중복 fy — end 날짜가 더 늦은 값을 채택해야 한다.
  2. 태그 우선순위 — 후보 태그 전체를 병합해야 한다(먼저 온 태그가 옛 연도만 있어도
     최근 연도는 다음 후보에서 채워야 함).
"""

from decimal import Decimal

import httpx
import pytest

from pams.equity.domain.financial_statement import (
    FinancialStatementProvider,
    FinancialStatementProviderError,
)
from pams.equity.infrastructure import SecEdgarFinancialStatementProvider

_TICKERS_BODY = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}


def _fact_entry(fy: int, end: str, val: float, form: str = "10-K", fp: str = "FY") -> dict:
    return {"fy": fy, "fp": fp, "form": form, "end": end, "val": val}


class TestSecEdgarFinancialStatementProvider:
    def make(self, handler) -> SecEdgarFinancialStatementProvider:  # type: ignore[no-untyped-def]
        return SecEdgarFinancialStatementProvider(
            contact_email="test@example.com", transport=httpx.MockTransport(handler)
        )

    def test_satisfies_port(self) -> None:
        assert isinstance(self.make(lambda _r: httpx.Response(200)), FinancialStatementProvider)

    def test_missing_contact_email_rejected(self) -> None:
        provider = SecEdgarFinancialStatementProvider(contact_email="")
        with pytest.raises(FinancialStatementProviderError, match="User-Agent"):
            provider.annual_financials("AAPL")

    def test_tag_priority_merges_across_candidates_not_stops_at_first(self) -> None:
        """구 태그(Revenues)는 2022년만, 신 태그는 2023~2025만 있는 상황 —
        병합 후 3개년 모두 채워져야 한다(첫 태그에서 멈추면 2023~2025이 비게 됨)."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "company_tickers" in str(request.url):
                return httpx.Response(200, json=_TICKERS_BODY)
            facts = {
                "facts": {
                    "us-gaap": {
                        "Revenues": {"units": {"USD": [_fact_entry(2022, "2022-12-31", 100.0)]}},
                        "RevenueFromContractWithCustomerExcludingAssessedTax": {
                            "units": {
                                "USD": [
                                    _fact_entry(2023, "2023-12-31", 110.0),
                                    _fact_entry(2024, "2024-12-31", 121.0),
                                    _fact_entry(2025, "2025-12-31", 133.0),
                                ]
                            }
                        },
                    }
                }
            }
            return httpx.Response(200, json=facts)

        provider = self.make(handler)
        result = provider.annual_financials("AAPL", years=4)
        by_year = {row.fiscal_year: row.revenue for row in result.annual}
        assert by_year == {
            2022: Decimal("100.0"),
            2023: Decimal("110.0"),
            2024: Decimal("121.0"),
            2025: Decimal("133.0"),
        }

    def test_instant_account_duplicate_fy_picks_latest_end_date(self) -> None:
        """같은 fy에 당기말/전기말 두 시점이 섞여 들어와도, end가 더 늦은 값을 채택해야
        한다(먼저 온 순서가 아니라 end 비교) — AAPL FY2025 total_equity 실측 버그 재현."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "company_tickers" in str(request.url):
                return httpx.Response(200, json=_TICKERS_BODY)
            facts = {
                "facts": {
                    "us-gaap": {
                        "StockholdersEquity": {
                            "units": {
                                "USD": [
                                    _fact_entry(
                                        2025, "2024-12-31", 73_700_000_000.0
                                    ),  # 전기말(잘못된 값)
                                    _fact_entry(
                                        2025, "2025-12-31", 106_500_000_000.0
                                    ),  # 당기말(맞는 값)
                                ]
                            }
                        }
                    }
                }
            }
            return httpx.Response(200, json=facts)

        provider = self.make(handler)
        result = provider.annual_financials("AAPL", years=1)
        assert result.annual[0].total_equity == Decimal("106500000000.0")

    def test_total_debt_falls_back_to_assets_minus_equity(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "company_tickers" in str(request.url):
                return httpx.Response(200, json=_TICKERS_BODY)
            facts = {
                "facts": {
                    "us-gaap": {
                        "Assets": {"units": {"USD": [_fact_entry(2025, "2025-12-31", 1000.0)]}},
                        "StockholdersEquity": {
                            "units": {"USD": [_fact_entry(2025, "2025-12-31", 300.0)]}
                        },
                    }
                }
            }
            return httpx.Response(200, json=facts)

        provider = self.make(handler)
        result = provider.annual_financials("AAPL", years=1)
        assert result.annual[0].total_debt == Decimal("700.0")

    def test_total_debt_uses_real_zero_liabilities_not_fallback(self) -> None:
        """v1.5.3 버그 회귀: 부채총계가 진짜 0이어도 자산-자본 폴백으로 덮어쓰면 안 된다."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "company_tickers" in str(request.url):
                return httpx.Response(200, json=_TICKERS_BODY)
            facts = {
                "facts": {
                    "us-gaap": {
                        "Liabilities": {"units": {"USD": [_fact_entry(2025, "2025-12-31", 0.0)]}},
                        "Assets": {"units": {"USD": [_fact_entry(2025, "2025-12-31", 1000.0)]}},
                        "StockholdersEquity": {
                            "units": {"USD": [_fact_entry(2025, "2025-12-31", 300.0)]}
                        },
                    }
                }
            }
            return httpx.Response(200, json=facts)

        provider = self.make(handler)
        result = provider.annual_financials("AAPL", years=1)
        assert result.annual[0].total_debt == Decimal("0.0")

    def test_controlling_interest_equity_excludes_nci_inclusive_fallback(self) -> None:
        """ROE 분모 버그 재현: StockholdersEquity(지배주주지분) 태그가 없고 NCI 포함
        태그만 있으면 total_equity는 폴백으로 채워지지만, controlling_interest_equity는
        None으로 남아야 한다 — NCI 포함 값을 ROE 분모로 대체하지 않는다."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "company_tickers" in str(request.url):
                return httpx.Response(200, json=_TICKERS_BODY)
            facts = {
                "facts": {
                    "us-gaap": {
                        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": {
                            "units": {"USD": [_fact_entry(2025, "2025-12-31", 500.0)]}
                        },
                    }
                }
            }
            return httpx.Response(200, json=facts)

        provider = self.make(handler)
        result = provider.annual_financials("AAPL", years=1)
        row = result.annual[0]
        assert row.total_equity == Decimal("500.0")
        assert row.controlling_interest_equity is None

    def test_unknown_ticker_raises(self) -> None:
        provider = self.make(lambda _r: httpx.Response(200, json=_TICKERS_BODY))
        with pytest.raises(FinancialStatementProviderError, match="CIK"):
            provider.annual_financials("NOPE")

    def test_numeric_ticker_raises_with_kr_market_hint(self) -> None:
        """005930(삼성전자) 같은 숫자 심볼은 SEC 미등록이라 항상 실패한다 — market=KR로
        조회하라는 힌트를 메시지에 포함해 혼동(SEC/DART 오선택)을 줄인다."""
        provider = self.make(lambda _r: httpx.Response(200, json=_TICKERS_BODY))
        with pytest.raises(FinancialStatementProviderError, match="market=KR"):
            provider.annual_financials("005930")

    def test_shares_outstanding_extracted_for_dcf_auto_fetch(self) -> None:
        """종목 심볼만 입력해도 주당 적정가를 계산할 수 있도록 발행주식수도
        재무제표 조회에서 함께 채운다(shares 단위 us-gaap 태그)."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "company_tickers" in str(request.url):
                return httpx.Response(200, json=_TICKERS_BODY)
            facts = {
                "facts": {
                    "us-gaap": {
                        "CommonStockSharesOutstanding": {
                            "units": {"shares": [_fact_entry(2025, "2025-12-31", 15_000_000_000.0)]}
                        },
                    }
                }
            }
            return httpx.Response(200, json=facts)

        provider = self.make(handler)
        result = provider.annual_financials("AAPL", years=1)
        assert result.annual[0].shares_outstanding == Decimal("15000000000.0")

    def test_income_tax_expense_extracted_for_roic(self) -> None:
        """ROIC 유효세율 계산 전용(growth_metrics.py roic_latest)."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "company_tickers" in str(request.url):
                return httpx.Response(200, json=_TICKERS_BODY)
            facts = {
                "facts": {
                    "us-gaap": {
                        "IncomeTaxExpenseBenefit": {
                            "units": {"USD": [_fact_entry(2025, "2025-12-31", 250_000_000.0)]}
                        },
                    }
                }
            }
            return httpx.Response(200, json=facts)

        provider = self.make(handler)
        result = provider.annual_financials("AAPL", years=1)
        assert result.annual[0].income_tax_expense == Decimal("250000000.0")
