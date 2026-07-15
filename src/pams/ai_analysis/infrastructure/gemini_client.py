"""Google Gemini API 어댑터.

TextCompletion 포트의 구현체. API 키/모델명은 조립 지점에서 주입한다
(환경변수 GEMINI_API_KEY 또는 GOOGLE_API_KEY). 도메인 원칙(계산·판단 금지)은
프롬프트가 강제하며, 이 어댑터는 텍스트 왕복만 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from pams.ai_analysis.infrastructure.anthropic_client import AnalysisProviderError

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


@dataclass(frozen=True, slots=True)
class GeminiTextCompletion:
    api_key: str
    model: str = "gemini-2.0-flash"
    max_tokens: int = 4096
    timeout_seconds: float = 30.0
    transport: httpx.BaseTransport | None = None  # 테스트에서 목킹 주입

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        url = f"{_API_BASE}/{self.model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"maxOutputTokens": self.max_tokens},
        }
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = client.post(
                    url,
                    params={"key": self.api_key},
                    json=payload,
                    headers={"content-type": "application/json"},
                )
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise AnalysisProviderError(f"Gemini API 호출 실패: {error}") from error

        body = response.json()
        try:
            parts = body["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as error:
            raise AnalysisProviderError(f"예상 밖의 응답 형식: {body!r}") from error
        if not text.strip():
            raise AnalysisProviderError("Gemini가 빈 응답을 반환했다")
        return text
