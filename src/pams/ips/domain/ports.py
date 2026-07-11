"""ips 컨텍스트의 포트: 투자헌장 저장소.

구현(YAML 파일, DB 등)은 infrastructure가 담당하며 언제든 교체 가능하다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pams.ips.domain.policy import PolicyStatement


@runtime_checkable
class PolicyRepository(Protocol):
    def load(self) -> PolicyStatement:
        """현재 유효한 투자헌장을 로드한다."""
        ...
