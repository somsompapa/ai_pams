"""CompareIndustryPeers 유스케이스 테스트 — 페이크 저장소·재무제표 공급자 주입.

피어 종목코드를 코드가 지어내지 않고 IndustryClassificationRepository에서만
찾는다는 계약을 검증한다(sync-industry가 미리 채워둔 맵)."""

from dataclasses import dataclass
from decimal import Decimal

from pams.equity.application.compare_industry_peers import CompareIndustryPeers
from pams.equity.domain.financial_statement import (
    AnnualFinancials,
    AnnualFinancialsResult,
    FinancialStatementProviderError,
)
from pams.equity.domain.growth_metrics import compute_growth_metrics
from pams.equity.domain.industry_classification import IndustryClassification


@dataclass(frozen=True, slots=True)
class _FakeClassificationRepository:
    entries: dict[str, IndustryClassification]

    def load(self) -> dict[str, IndustryClassification]:
        return self.entries

    def save(self, entries: dict[str, IndustryClassification]) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _FakeProvider:
    by_symbol: dict[str, AnnualFinancialsResult]

    def annual_financials(self, asset_id: str, *, years: int = 4) -> AnnualFinancialsResult:
        if asset_id not in self.by_symbol:
            raise FinancialStatementProviderError(f"{asset_id}: 없음")
        return self.by_symbol[asset_id]


def _result(symbol: str, gross_margin_row: Decimal) -> AnnualFinancialsResult:
    return AnnualFinancialsResult(
        asset_id=symbol,
        data_source="fake",
        annual=(
            AnnualFinancials(
                fiscal_year=2025,
                revenue=Decimal(1000),
                gross_profit=gross_margin_row * Decimal(1000),
            ),
        ),
    )


class TestCompareIndustryPeers:
    def test_finds_peers_with_same_market_and_code(self) -> None:
        repo = _FakeClassificationRepository(
            entries={
                "KR:005930": IndustryClassification(code="26410"),
                "KR:000660": IndustryClassification(code="26410"),
                "KR:035420": IndustryClassification(code="63910"),  # 다른 업종
                "US:AAPL": IndustryClassification(code="26410"),  # 다른 시장, 코드 같아도 제외
            }
        )
        provider = _FakeProvider(by_symbol={"000660": _result("000660", Decimal("0.30"))})
        target_metrics = compute_growth_metrics(
            (AnnualFinancials(fiscal_year=2025, revenue=Decimal(1000), gross_profit=Decimal(400)),)
        )
        result = CompareIndustryPeers(
            classification_repository=repo, provider_for_market=lambda _m: provider
        ).execute(asset_id="005930", market="KR", is_financial=False, target_metrics=target_metrics)
        assert result.peer_count == 1
        assert result.gross_margin_vs_industry_pp == Decimal("0.10")  # 0.40 - 0.30

    def test_no_classification_for_target_returns_note(self) -> None:
        repo = _FakeClassificationRepository(entries={})
        target_metrics = compute_growth_metrics(())
        result = CompareIndustryPeers(
            classification_repository=repo, provider_for_market=lambda _m: _FakeProvider({})
        ).execute(asset_id="005930", market="KR", is_financial=False, target_metrics=target_metrics)
        assert result.peer_count == 0
        assert result.note is not None

    def test_no_peers_sharing_code_returns_note(self) -> None:
        repo = _FakeClassificationRepository(
            entries={"KR:005930": IndustryClassification(code="26410")}
        )
        target_metrics = compute_growth_metrics(())
        result = CompareIndustryPeers(
            classification_repository=repo, provider_for_market=lambda _m: _FakeProvider({})
        ).execute(asset_id="005930", market="KR", is_financial=False, target_metrics=target_metrics)
        assert result.peer_count == 0
        assert result.note is not None

    def test_peer_fetch_failure_is_skipped_not_fatal(self) -> None:
        """피어 하나가 조회 실패해도 나머지 피어로 비교를 계속해야 한다."""
        repo = _FakeClassificationRepository(
            entries={
                "KR:005930": IndustryClassification(code="26410"),
                "KR:000660": IndustryClassification(code="26410"),
                "KR:999999": IndustryClassification(code="26410"),  # 조회 실패할 종목
            }
        )
        provider = _FakeProvider(by_symbol={"000660": _result("000660", Decimal("0.30"))})
        target_metrics = compute_growth_metrics(
            (AnnualFinancials(fiscal_year=2025, revenue=Decimal(1000), gross_profit=Decimal(400)),)
        )
        result = CompareIndustryPeers(
            classification_repository=repo, provider_for_market=lambda _m: provider
        ).execute(asset_id="005930", market="KR", is_financial=False, target_metrics=target_metrics)
        assert result.peer_count == 1
