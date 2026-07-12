"""Anthropic(Claude) API 어댑터.

TextCompletion 포트의 구현체. API 키/모델명은 조립 지점에서 주입한다
(환경변수 ANTHROPIC_API_KEY - .env.example 참고). 네트워크 실패와 예상 밖
응답은 AnalysisProviderError로 통일한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"


class AnalysisProviderError(Exception):
    """LLM 공급자 호출에 실패했다."""


@dataclass(frozen=True, slots=True)
class AnthropicTextCompletion:
    api_key: str
    model: str
    max_tokens: int = 1024
    timeout_seconds: float = 30.0

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }
        try:
            response = httpx.post(
                _API_URL, json=payload, headers=headers, timeout=self.timeout_seconds
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise AnalysisProviderError(f"Anthropic API 호출 실패: {error}") from error

        body = response.json()
        try:
            blocks = body["content"]
            text = "".join(block["text"] for block in blocks if block.get("type") == "text")
        except (KeyError, TypeError) as error:
            raise AnalysisProviderError(f"예상 밖의 응답 형식: {body!r}") from error
        if not text.strip():
            raise AnalysisProviderError("응답에 텍스트가 없다")
        return text
