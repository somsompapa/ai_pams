"""유스케이스: 거래 원장(Transaction)을 FIFO 매칭해 실현 CAGR·MDD를 산출한다."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pams.performance.domain.realized_lots import (
    RealizedPerformanceReport,
    compute_realized_performance,
)
from pams.portfolio.domain.transaction import Transaction


@dataclass(frozen=True, slots=True)
class ComputeRealizedPerformance:
    def execute(self, transactions: Sequence[Transaction]) -> RealizedPerformanceReport:
        return compute_realized_performance(transactions)
