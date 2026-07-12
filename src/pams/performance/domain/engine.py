"""PerformanceEngine: 기간별 TWR, 벤치마크 비교, 승률, 규칙 준수율."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum, unique

from pams.performance.domain.history import PerformanceCalculationError, PerformanceHistory


@unique
class PeriodType(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


def _period_label(period_type: PeriodType, day: date) -> str:
    match period_type:
        case PeriodType.MONTHLY:
            return f"{day.year:04d}-{day.month:02d}"
        case PeriodType.QUARTERLY:
            return f"{day.year:04d}-Q{(day.month - 1) // 3 + 1}"
        case PeriodType.YEARLY:
            return f"{day.year:04d}"


@dataclass(frozen=True, slots=True)
class PeriodPerformance:
    """한 기간(월/분기/연)의 성과. 벤치마크가 없으면 비교 값은 None이다."""

    label: str
    twr: Decimal
    benchmark_twr: Decimal | None

    @property
    def excess(self) -> Decimal | None:
        if self.benchmark_twr is None:
            return None
        return self.twr - self.benchmark_twr


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    as_of: date
    cumulative_twr: Decimal
    cumulative_benchmark_twr: Decimal | None
    monthly: tuple[PeriodPerformance, ...]
    quarterly: tuple[PeriodPerformance, ...]
    yearly: tuple[PeriodPerformance, ...]
    win_rate: Decimal | None  # 실현손익 기준 이익 거래 비율
    compliance_rate: Decimal | None  # 규칙 준수 판정 비율

    @property
    def cumulative_excess(self) -> Decimal | None:
        if self.cumulative_benchmark_twr is None:
            return None
        return self.cumulative_twr - self.cumulative_benchmark_twr


def _period_returns(history: PerformanceHistory, period_type: PeriodType) -> dict[str, Decimal]:
    """구간 성장배수를 기간 버킷으로 묶어 기간별 TWR을 만든다."""
    buckets: dict[str, Decimal] = {}
    for end_date, factor in history.growth_factors():
        label = _period_label(period_type, end_date)
        buckets[label] = buckets.get(label, Decimal(1)) * factor
    return {label: product - 1 for label, product in buckets.items()}


def _win_rate(realized_pnls: Sequence[Decimal]) -> Decimal:
    if not realized_pnls:
        raise PerformanceCalculationError("실현손익 목록이 비어 있으면 승률을 계산할 수 없다")
    wins = sum(1 for pnl in realized_pnls if pnl > 0)
    return Decimal(wins) / Decimal(len(realized_pnls))


def _compliance_rate(compliance_history: Sequence[tuple[date, bool]]) -> Decimal:
    if not compliance_history:
        raise PerformanceCalculationError("준수 이력이 비어 있으면 준수율을 계산할 수 없다")
    compliant = sum(1 for _day, is_compliant in compliance_history if is_compliant)
    return Decimal(compliant) / Decimal(len(compliance_history))


class PerformanceEngine:
    def analyze(
        self,
        *,
        history: PerformanceHistory,
        benchmark: PerformanceHistory | None = None,
        realized_pnls: Sequence[Decimal] | None = None,
        compliance_history: Sequence[tuple[date, bool]] | None = None,
    ) -> PerformanceReport:
        benchmark_by_type: dict[PeriodType, dict[str, Decimal]] = {}
        if benchmark is not None:
            benchmark_by_type = {
                period_type: _period_returns(benchmark, period_type) for period_type in PeriodType
            }

        def breakdown(period_type: PeriodType) -> tuple[PeriodPerformance, ...]:
            benchmark_returns = benchmark_by_type.get(period_type, {})
            return tuple(
                PeriodPerformance(label=label, twr=twr, benchmark_twr=benchmark_returns.get(label))
                for label, twr in sorted(_period_returns(history, period_type).items())
            )

        return PerformanceReport(
            as_of=history.end_date,
            cumulative_twr=history.cumulative_twr(),
            cumulative_benchmark_twr=(
                benchmark.cumulative_twr() if benchmark is not None else None
            ),
            monthly=breakdown(PeriodType.MONTHLY),
            quarterly=breakdown(PeriodType.QUARTERLY),
            yearly=breakdown(PeriodType.YEARLY),
            win_rate=_win_rate(realized_pnls) if realized_pnls is not None else None,
            compliance_rate=(
                _compliance_rate(compliance_history) if compliance_history is not None else None
            ),
        )
