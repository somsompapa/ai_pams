"""sync_industry_classifications() 통합 테스트 — 페이크 재무제표 공급자 주입,
실제 config/assets/default.yaml·data/industry_map.json 파일시스템 왕복."""

from dataclasses import dataclass
from pathlib import Path

from pams.equity.domain.financial_statement import AnnualFinancialsResult
from pams.equity.domain.industry_classification import IndustryClassification
from pams.equity.infrastructure import JsonIndustryClassificationRepository
from pams.interfaces.wiring import sync_industry_classifications

_ASSETS_YAML = """
assets:
  - asset_id: KRX:005930
    name: 삼성전자
    asset_class: domestic_stock
    currency: KRW
    country: KR
  - asset_id: NASDAQ:AAPL
    name: Apple Inc.
    asset_class: us_stock
    currency: USD
    country: US
  - asset_id: KRX:069500
    name: KODEX 200
    asset_class: etf
    currency: KRW
    country: KR
"""


@dataclass(frozen=True, slots=True)
class _FakeProvider:
    classifications: dict[str, IndustryClassification]

    def annual_financials(self, asset_id: str, *, years: int = 4) -> AnnualFinancialsResult:
        raise NotImplementedError

    def industry_classification(self, asset_id: str) -> IndustryClassification | None:
        return self.classifications.get(asset_id)


def _project_root(tmp_path: Path) -> Path:
    (tmp_path / "config" / "assets").mkdir(parents=True)
    (tmp_path / "config" / "assets" / "default.yaml").write_text(_ASSETS_YAML, encoding="utf-8")
    return tmp_path


class TestSyncIndustryClassifications:
    def test_syncs_stock_assets_only_skips_etf(self, tmp_path: Path) -> None:
        root = _project_root(tmp_path)
        kr_provider = _FakeProvider({"005930": IndustryClassification(code="26410")})
        us_provider = _FakeProvider({"AAPL": IndustryClassification(code="3571")})

        result = sync_industry_classifications(
            root, provider_for_market=lambda m: kr_provider if m == "KR" else us_provider
        )

        assert result.synced == {
            "KR:005930": IndustryClassification(code="26410"),
            "US:AAPL": IndustryClassification(code="3571"),
        }
        assert result.errors == ()

    def test_writes_industry_map_json_to_disk(self, tmp_path: Path) -> None:
        root = _project_root(tmp_path)
        kr_provider = _FakeProvider({"005930": IndustryClassification(code="26410")})
        us_provider = _FakeProvider({"AAPL": IndustryClassification(code="3571")})

        sync_industry_classifications(
            root, provider_for_market=lambda m: kr_provider if m == "KR" else us_provider
        )

        loaded = JsonIndustryClassificationRepository(root / "data" / "industry_map.json").load()
        assert loaded["KR:005930"].code == "26410"

    def test_individual_lookup_failure_is_recorded_not_fatal(self, tmp_path: Path) -> None:
        root = _project_root(tmp_path)
        kr_provider = _FakeProvider({})  # 조회 실패 시뮬레이션
        us_provider = _FakeProvider({"AAPL": IndustryClassification(code="3571")})

        result = sync_industry_classifications(
            root, provider_for_market=lambda m: kr_provider if m == "KR" else us_provider
        )

        assert "KR:005930" not in result.synced
        assert "US:AAPL" in result.synced
        assert any("KR:005930" in e for e in result.errors)

    def test_no_registered_stocks_returns_empty_without_error(self, tmp_path: Path) -> None:
        (tmp_path / "config" / "assets").mkdir(parents=True)
        (tmp_path / "config" / "assets" / "default.yaml").write_text(
            "assets: []\n", encoding="utf-8"
        )
        result = sync_industry_classifications(
            tmp_path, provider_for_market=lambda _m: _FakeProvider({})
        )
        assert result.synced == {}
        assert result.errors == ()
