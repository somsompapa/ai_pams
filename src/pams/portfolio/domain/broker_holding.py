"""증권사 API가 보고하는 실계좌 보유내역 포트 - 표시 전용 참고자료.

거래이력(data/transactions.csv) 기반 PortfolioSnapshot의 cost_basis/quantity를
대체하지 않는다 - 과거 거래 로그가 있어야만 계산 가능한 실현손익·양도세는
이 값을 쓰지 않는다. 대시보드 주식 종목 표의 표시값(수량·평단가·현재가·평가금액)만
이 값으로 보강한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pams.shared_kernel.domain import Currency, DomainError, DomainValidationError


class BrokerProviderError(DomainError):
    """증권사 API 호출/응답 처리에 실패했다."""


@dataclass(frozen=True, slots=True)
class BrokerHolding:
    """증권사가 보고하는 종목별 실계좌 보유 스냅샷 (거래이력이 아니라 현재 상태)."""

    symbol: str  # 국내: 6자리 종목코드, 해외: 티커 (거래소 접두사 없음)
    quantity: Decimal
    avg_price: Decimal
    current_price: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise DomainValidationError(f"수량은 음수일 수 없다: {self.quantity}")
        if self.avg_price < 0 or self.current_price < 0:
            raise DomainValidationError("가격은 음수일 수 없다")


@runtime_checkable
class HoldingsProvider(Protocol):
    def holdings(self) -> Sequence[BrokerHolding]:
        """실계좌의 현재 보유 종목 스냅샷."""
        ...
