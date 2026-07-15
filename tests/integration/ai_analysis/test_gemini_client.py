"""GeminiTextCompletion 어댑터 통합 테스트 (HTTP는 MockTransport로 목킹)."""

import json

import httpx
import pytest

from pams.ai_analysis.domain import TextCompletion
from pams.ai_analysis.infrastructure import AnalysisProviderError, GeminiTextCompletion


def _ok_response(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class TestGeminiTextCompletion:
    def make(self, handler) -> GeminiTextCompletion:  # type: ignore[no-untyped-def]
        return GeminiTextCompletion(
            api_key="k", model="gemini-2.0-flash", transport=httpx.MockTransport(handler)
        )

    def test_satisfies_port(self) -> None:
        assert isinstance(self.make(lambda _r: httpx.Response(200)), TextCompletion)

    def test_returns_text_and_sends_key_and_prompts(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.read().decode()
            return httpx.Response(200, json=_ok_response("해설 결과"))

        result = self.make(handler).complete(system_prompt="시스템", user_prompt="사실 목록")
        assert result == "해설 결과"
        assert "key=k" in captured["url"]
        assert "gemini-2.0-flash:generateContent" in captured["url"]
        assert "시스템" in captured["body"]
        assert "사실 목록" in captured["body"]

    def test_sends_generous_max_output_tokens_by_default(self) -> None:
        """예전 1024 기본값 때문에 해설이 중간에 잘리던 문제 재발 방지."""
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.read().decode()
            return httpx.Response(200, json=_ok_response("해설 결과"))

        self.make(handler).complete(system_prompt="s", user_prompt="u")
        assert json.loads(captured["body"])["generationConfig"]["maxOutputTokens"] == 4096

    def test_http_error_wrapped(self) -> None:
        provider = self.make(lambda _r: httpx.Response(500, json={"error": "x"}))
        with pytest.raises(AnalysisProviderError):
            provider.complete(system_prompt="s", user_prompt="u")

    def test_empty_response_rejected(self) -> None:
        provider = self.make(lambda _r: httpx.Response(200, json=_ok_response("   ")))
        with pytest.raises(AnalysisProviderError):
            provider.complete(system_prompt="s", user_prompt="u")

    def test_malformed_response_rejected(self) -> None:
        provider = self.make(lambda _r: httpx.Response(200, json={"unexpected": True}))
        with pytest.raises(AnalysisProviderError):
            provider.complete(system_prompt="s", user_prompt="u")
