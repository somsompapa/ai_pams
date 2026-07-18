"""JsonIndustryClassificationRepository 통합 테스트 (실제 파일시스템 왕복)."""

from pathlib import Path

from pams.equity.domain.industry_classification import IndustryClassification
from pams.equity.infrastructure import JsonIndustryClassificationRepository


class TestJsonIndustryClassificationRepository:
    def test_load_returns_empty_dict_when_file_missing(self, tmp_path: Path) -> None:
        repo = JsonIndustryClassificationRepository(tmp_path / "industry_map.json")
        assert repo.load() == {}

    def test_save_then_load_round_trips(self, tmp_path: Path) -> None:
        repo = JsonIndustryClassificationRepository(tmp_path / "industry_map.json")
        entries = {
            "KR:005930": IndustryClassification(code="26410"),
            "US:AAPL": IndustryClassification(code="3571", name="Electronic Computers"),
        }
        repo.save(entries)
        loaded = repo.load()
        assert loaded == entries

    def test_save_overwrites_previous_contents(self, tmp_path: Path) -> None:
        repo = JsonIndustryClassificationRepository(tmp_path / "industry_map.json")
        repo.save({"KR:005930": IndustryClassification(code="26410")})
        repo.save({"KR:000660": IndustryClassification(code="26410")})
        loaded = repo.load()
        assert "KR:005930" not in loaded
        assert "KR:000660" in loaded

    def test_load_ignores_malformed_entries(self, tmp_path: Path) -> None:
        path = tmp_path / "industry_map.json"
        path.write_text('{"KR:005930": {"code": "26410"}, "KR:bad": {}}', encoding="utf-8")
        repo = JsonIndustryClassificationRepository(path)
        loaded = repo.load()
        assert list(loaded.keys()) == ["KR:005930"]
