"""performance 컨텍스트의 포트: 가치 이력 저장소.

포트폴리오 총자산을 날마다 적재해 TWR/리스크 계산의 시계열 원천이 된다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pams.performance.domain.history import PerformanceHistory, ValuationPoint


@runtime_checkable
class ValueHistoryRepository(Protocol):
    def append(self, point: ValuationPoint) -> None:
        """하루 1점. 같은 날짜에 다시 적재하면 마지막 값으로 교체한다."""
        ...

    def load(self) -> PerformanceHistory | None:
        """적재된 이력. 비어 있으면 None."""
        ...
