"""DashboardService: 모든 엔진 유스케이스를 조립해 대시보드 데이터를 만든다.

interfaces 계층은 유일한 조립 지점(composition root)이다.
모든 수치는 엔진이 계산하고, 여기서는 표시용 문자열로 변환만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from pams.ips.application import EvaluateCompliance
from pams.ips.domain import ComplianceReport, EvaluationContext, PolicyStatement
from pams.ips.infrastructure import YamlPolicyRepository
from pams.performance.application import ComputePerformanceReport
from pams.performance.domain import PerformanceHistory, PerformanceReport
from pams.portfolio.application import BuildPortfolioSnapshot
from pams.portfolio.domain import (
    AssetCatalog,
    FxLookup,
    PortfolioSnapshot,
    PriceLookup,
    TransactionRepository,
)
from pams.rebalancing.application import ProposeRebalancing
from pams.rebalancing.domain import RebalancingProposal, TradeDirection
from pams.rebalancing.infrastructure import YamlCostModelLoader
from pams.reporting.application.formatting import (
    asset_class_label,
    format_metric,
    format_money,
    format_percent,
    metric_label,
    percent_value,
)
from pams.risk.application import ComputeRiskReport
from pams.risk.domain import RiskReport, ValueSeries
from pams.risk.infrastructure import YamlRiskParametersLoader
from pams.shared_kernel.domain import AssetClass, Currency, Money, Percentage


@dataclass(frozen=True, slots=True)
class EngineOutputs:
    """엔진 유스케이스들의 도메인 출력 묶음 (published language)."""

    policy: PolicyStatement
    snapshot: PortfolioSnapshot
    risk: RiskReport
    compliance: ComplianceReport
    proposal: RebalancingProposal
    performance: PerformanceReport


@dataclass(frozen=True, slots=True)
class DashboardService:
    config_dir: Path
    transactions: TransactionRepository
    assets: AssetCatalog
    prices: PriceLookup
    fx: FxLookup
    portfolio_values: ValueSeries
    performance_history: PerformanceHistory
    market_metrics: dict[str, Decimal]  # 예: {"vix": Decimal("24.5")} - 시장 지표
    benchmark_values: ValueSeries | None = None  # 없으면 벤치마크 비교 지표 생략
    benchmark_history: PerformanceHistory | None = None

    def compute(self, *, as_of: date, base_currency: Currency) -> EngineOutputs:
        """모든 엔진 유스케이스를 실행해 도메인 출력 묶음을 만든다.

        대시보드(build)와 보고서 생성(CLI report)이 이 출력을 공유한다.
        """
        policy = YamlPolicyRepository(
            ips_path=self.config_dir / "ips" / "default.yaml",
            rules_path=self.config_dir / "rules" / "default.yaml",
        ).load()

        snapshot = BuildPortfolioSnapshot(
            transactions=self.transactions, assets=self.assets, prices=self.prices, fx=self.fx
        ).execute(as_of=as_of, base_currency=base_currency)

        risk_parameters = YamlRiskParametersLoader(self.config_dir / "risk" / "default.yaml").load()
        total = snapshot.total_value.amount
        position_weights = {
            v.asset.asset_id: v.market_value_base.amount / total for v in snapshot.valuations
        }
        risk = ComputeRiskReport().execute(
            portfolio_values=self.portfolio_values,
            parameters=risk_parameters,
            benchmark_values=self.benchmark_values,
            position_weights=position_weights,
        )

        metrics = {
            **snapshot.metrics(),
            **self.market_metrics,
            "drawdown": risk.metrics["drawdown"],
        }
        compliance = EvaluateCompliance(repository=_LoadedPolicy(policy)).execute(
            EvaluationContext(as_of=as_of, metrics=metrics)
        )

        costs = YamlCostModelLoader(self.config_dir / "costs" / "default.yaml").load()
        proposal = ProposeRebalancing(costs=costs).execute(
            as_of=as_of,
            base_currency=base_currency,
            current_values=_values_by_class(snapshot),
            targets=policy.targets,
            cost_bases=_cost_by_class(snapshot),
        )

        performance = ComputePerformanceReport().execute(
            history=self.performance_history,
            benchmark=self.benchmark_history,
            compliance_history=[(as_of, compliance.is_compliant)],
        )
        return EngineOutputs(
            policy=policy,
            snapshot=snapshot,
            risk=risk,
            compliance=compliance,
            proposal=proposal,
            performance=performance,
        )

    def build(self, *, as_of: date, base_currency: Currency) -> dict[str, Any]:
        outputs = self.compute(as_of=as_of, base_currency=base_currency)
        policy = outputs.policy
        snapshot = outputs.snapshot
        risk = outputs.risk
        compliance = outputs.compliance
        proposal = outputs.proposal
        performance = outputs.performance

        return {
            "as_of": as_of.isoformat(),
            "base_currency": base_currency.value,
            "policy_name": policy.name,
            "summary": self._summary(snapshot, performance.cumulative_twr, compliance),
            "weights": self._weights(snapshot),
            "targets": self._targets(snapshot, policy),
            "risk": [
                {"name": name, "label": metric_label(name), "value": format_metric(name, value)}
                for name, value in risk.metrics.items()
            ],
            "alerts": self._alerts(compliance),
            "rebalancing": self._rebalancing(proposal),
            "performance": {
                "cumulative": format_percent(performance.cumulative_twr),
                "benchmark_cumulative": (
                    format_percent(performance.cumulative_benchmark_twr)
                    if performance.cumulative_benchmark_twr is not None
                    else None
                ),
                "monthly": [
                    {
                        "label": p.label,
                        "twr": percent_value(p.twr),
                        "benchmark": (
                            percent_value(p.benchmark_twr) if p.benchmark_twr is not None else None
                        ),
                    }
                    for p in performance.monthly
                ],
            },
        }

    def _summary(
        self,
        snapshot: PortfolioSnapshot,
        cumulative_twr: Decimal,
        compliance: ComplianceReport,
    ) -> dict[str, Any]:
        values = self.portfolio_values.values
        today_change = values[-1] - values[-2]
        today_ratio = today_change / values[-2]
        return {
            "total_value": format_money(snapshot.total_value),
            "today_pnl": format_money(Money(today_change, snapshot.base_currency)),
            "today_pnl_percent": format_percent(today_ratio),
            "today_positive": today_change >= 0,
            "unrealized_pnl": format_money(snapshot.total_unrealized_pnl),
            "realized_pnl": format_money(snapshot.total_realized_pnl),
            "cumulative_twr": format_percent(cumulative_twr),
            "compliant": compliance.is_compliant,
            "violation_count": len(compliance.violations),
            "warning_count": len(compliance.warnings),
        }

    @staticmethod
    def _weights(snapshot: PortfolioSnapshot) -> dict[str, list[dict[str, str]]]:
        def entries_from(weights: dict[Any, Any], label_of: Any) -> list[dict[str, str]]:
            ordered = sorted(weights.items(), key=lambda item: item[1].ratio, reverse=True)
            return [
                {"label": label_of(key), "percent": percent_value(weight)}
                for key, weight in ordered
            ]

        return {
            "asset_class": entries_from(
                snapshot.weights_by_asset_class(), lambda ac: asset_class_label(ac.value)
            ),
            "country": entries_from(snapshot.weights_by_country(), str),
            "currency": entries_from(snapshot.weights_by_currency(), lambda c: c.value),
        }

    @staticmethod
    def _targets(snapshot: PortfolioSnapshot, policy: PolicyStatement) -> list[dict[str, Any]]:
        current = snapshot.weights_by_asset_class()
        cash_like_total = sum(
            (weight.ratio for ac, weight in current.items() if ac.is_cash_like), Decimal(0)
        )
        rows = []
        for target in policy.targets:
            if target.asset_class.is_cash_like:
                ratio = cash_like_total
            else:
                weight = current.get(target.asset_class)
                ratio = weight.ratio if weight is not None else Decimal(0)
            status = (
                "ok"
                if target.contains(Percentage.from_ratio(ratio))
                else ("over" if ratio > target.target.ratio else "under")
            )
            rows.append(
                {
                    "label": asset_class_label(target.asset_class.value),
                    "current": percent_value(ratio),
                    "target": percent_value(target.target),
                    "band": percent_value(target.band),
                    "status": status,
                }
            )
        return rows

    @staticmethod
    def _alerts(compliance: ComplianceReport) -> list[dict[str, str]]:
        return [
            {
                "severity": evaluation.rule.severity.value,
                "rule_id": evaluation.rule.rule_id,
                "message": evaluation.rule.description,
                "observed": ", ".join(
                    f"{name}={value}" for name, value in evaluation.observed.items()
                ),
            }
            for evaluation in (*compliance.violations, *compliance.warnings)
        ]

    @staticmethod
    def _rebalancing(proposal: Any) -> dict[str, Any]:
        return {
            "needed": proposal.is_rebalancing_needed,
            "total_sell": format_money(proposal.total_sell_amount),
            "total_buy": format_money(proposal.total_buy_amount),
            "total_cost": format_money(proposal.total_estimated_cost),
            "actions": [
                {
                    "asset_class": asset_class_label(action.asset_class.value),
                    "direction": "매도" if action.direction is TradeDirection.SELL else "매수",
                    "amount": format_money(action.amount),
                    "current": percent_value(action.current_weight),
                    "target": percent_value(action.target_weight),
                    "cost": format_money(action.estimated_cost),
                }
                for action in proposal.actions
            ],
        }


@dataclass(frozen=True, slots=True)
class _LoadedPolicy:
    """이미 로드된 PolicyStatement를 PolicyRepository 포트에 맞춘다."""

    policy: PolicyStatement

    def load(self) -> PolicyStatement:
        return self.policy


def _values_by_class(snapshot: PortfolioSnapshot) -> dict[AssetClass, Money]:
    """리밸런싱 입력: 자산군별 평가액. 현금성(현금/예수금/외화)은 CASH로 합산한다.

    IPS의 'cash' 목표는 현금성 전체를 의미하기 때문이다.
    """
    values: dict[AssetClass, Money] = {}

    def add(asset_class: AssetClass, amount: Money) -> None:
        key = AssetClass.CASH if asset_class.is_cash_like else asset_class
        current = values.get(key, Money.zero(amount.currency))
        values[key] = current + amount

    for valuation in snapshot.valuations:
        add(valuation.asset.asset_class, valuation.market_value_base)
    for cash in snapshot.cash_balances:
        add(AssetClass.DEPOSIT, cash.value_base)
    return values


def _cost_by_class(snapshot: PortfolioSnapshot) -> dict[AssetClass, Money]:
    """자산군별 취득원가(기준통화). 양도세 추정에 쓰인다 (현금성은 제외)."""
    costs: dict[AssetClass, Money] = {}
    for valuation in snapshot.valuations:
        asset_class = valuation.asset.asset_class
        if asset_class.is_cash_like:
            continue
        # cost_basis는 자산 통화 기준이므로 평가와 동일한 환율 스케일로 base로 환산한다:
        # 원가_base = 원가_local × (시장가치_base / 시장가치_local). 원화 자산은 스케일 1.
        local = valuation.market_value_local.amount
        if local <= 0:
            continue  # 수량 0 포지션 (원가도 0)
        ratio = valuation.market_value_base.amount / local
        cost_base = Money(valuation.position.cost_basis.amount * ratio, snapshot.base_currency)
        current = costs.get(asset_class, Money.zero(snapshot.base_currency))
        costs[asset_class] = current + cost_base
    return costs
