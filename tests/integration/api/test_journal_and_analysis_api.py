"""투자일지/AI 해설 API 통합 테스트."""

from pathlib import Path

from fastapi.testclient import TestClient

from pams.ai_analysis.infrastructure import AnalysisProviderError
from pams.interfaces.api.app import create_app

JOURNAL_BODY = {
    "title": "삼성전자 일부 매도",
    "what": "삼성전자 30주 매도 @75,000",
    "why": "max-single-position 규칙(20%) 위반 해소",
    "rule_basis": "max-single-position",
}


class FakeCompletion:
    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        assert "숫자" in system_prompt  # 제약이 전달되는지 확인
        assert "[사실]" in user_prompt
        return "포트폴리오는 단일 종목 집중도가 높은 상태다."


class TestJournalApi:
    def test_record_and_list(self, tmp_path: Path) -> None:
        client = TestClient(create_app(data_dir=tmp_path))
        created = client.post("/api/journal", json=JOURNAL_BODY)
        assert created.status_code == 201
        entry = created.json()
        assert entry["what"] == JOURNAL_BODY["what"]
        assert entry["entry_id"]

        listed = client.get("/api/journal").json()
        assert len(listed["entries"]) == 1
        assert listed["entries"][0]["rule_basis"] == "max-single-position"

    def test_blank_why_rejected_as_bad_request(self, tmp_path: Path) -> None:
        client = TestClient(create_app(data_dir=tmp_path))
        response = client.post("/api/journal", json={**JOURNAL_BODY, "why": "  "})
        assert response.status_code == 400
        assert "왜" in response.json()["detail"]

    def test_journal_recording_leaves_audit_event(self, tmp_path: Path) -> None:
        client = TestClient(create_app(data_dir=tmp_path))
        client.post("/api/journal", json=JOURNAL_BODY)
        audit_log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "journal.recorded" in audit_log


class FailingCompletion:
    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        raise AnalysisProviderError("Gemini API 호출 실패: 401 Unauthorized")


class TestAnalysisApi:
    def test_analysis_with_injected_completion(self, tmp_path: Path) -> None:
        client = TestClient(create_app(data_dir=tmp_path, completion=FakeCompletion()))
        response = client.post("/api/analysis", json={"kind": "summary"})
        assert response.status_code == 200
        body = response.json()
        assert body["kind"] == "summary"
        assert "집중도" in body["text"]
        audit_log = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "analysis.generated" in audit_log

    def test_analysis_unavailable_without_provider(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        import pytest

        assert isinstance(monkeypatch, pytest.MonkeyPatch)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        client = TestClient(create_app(data_dir=tmp_path))
        response = client.post("/api/analysis", json={"kind": "summary"})
        assert response.status_code == 503

    def test_unknown_kind_rejected(self, tmp_path: Path) -> None:
        client = TestClient(create_app(data_dir=tmp_path, completion=FakeCompletion()))
        response = client.post("/api/analysis", json={"kind": "fortune_telling"})
        assert response.status_code == 422

    def test_provider_failure_returns_actionable_error_not_bare_500(self, tmp_path: Path) -> None:
        """AI 공급자 호출이 실패하면(키 오류·네트워크 등) 원인이 담긴 502를 반환한다.

        예전에는 AnalysisProviderError를 아무 데서도 잡지 않아 빈 500으로
        새어나가, 사용자는 "실패(500)"만 보고 원인을 알 수 없었다.
        """
        client = TestClient(create_app(data_dir=tmp_path, completion=FailingCompletion()))
        response = client.post("/api/analysis", json={"kind": "summary"})
        assert response.status_code == 502
        assert "401 Unauthorized" in response.json()["detail"]

    def test_stock_trigger_analysis_uses_that_stocks_facts_only(self, tmp_path: Path) -> None:
        client = TestClient(create_app(data_dir=tmp_path, completion=FakeCompletion()))
        response = client.post(
            "/api/analysis", json={"kind": "stock_trigger", "asset_id": "KRX:005930"}
        )
        assert response.status_code == 200
        assert response.json()["kind"] == "stock_trigger"

    def test_stock_trigger_requires_asset_id(self, tmp_path: Path) -> None:
        client = TestClient(create_app(data_dir=tmp_path, completion=FakeCompletion()))
        response = client.post("/api/analysis", json={"kind": "stock_trigger"})
        assert response.status_code == 400
        assert "asset_id" in response.json()["detail"]

    def test_stock_trigger_unknown_asset_rejected(self, tmp_path: Path) -> None:
        client = TestClient(create_app(data_dir=tmp_path, completion=FakeCompletion()))
        response = client.post("/api/analysis", json={"kind": "stock_trigger", "asset_id": "NOPE"})
        assert response.status_code == 400
