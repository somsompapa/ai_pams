"""Position: 한 자산의 보유 상태 (수량, 매입원가, 실현손익)."""

from __future__ import annotations

from dataclasses import dataclass

from pams.shared_kernel.domain import (
    CurrencyMismatchError,
    DomainValidationError,
    Money,
    Quantity,
)


@dataclass(frozen=True, slots=True)
class Position:
    """이동평균법 기준 보유 상태. 매수 부대비용(수수료·세금)은 원가에 산입된다."""

    asset_id: str
    quantity: Quantity
    cost_basis: Money  # 총 매입원가
    realized_pnl: Money  # 매도로 확정된 손익 누계

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise DomainValidationError("asset_id는 비어 있을 수 없다")
        if self.cost_basis.currency is not self.realized_pnl.currency:
            raise CurrencyMismatchError(
                f"cost_basis({self.cost_basis.currency})와 "
                f"realized_pnl({self.realized_pnl.currency})의 통화가 다르다"
            )
        if self.quantity.is_zero and not self.cost_basis.is_zero:
            raise DomainValidationError("수량이 0인 포지션의 원가는 0이어야 한다")

    @property
    def average_cost(self) -> Money:
        """1단위당 평균 매입원가."""
        if self.quantity.is_zero:
            return Money.zero(self.cost_basis.currency)
        return Money(self.cost_basis.amount / self.quantity.value, self.cost_basis.currency)
