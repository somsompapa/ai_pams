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

from pams.equity.domain import (
    EvaluatePriceTriggers,
    EvaluateStockAllocation,
    StockSignal,
    StockTarget,
    StockTargetPlan,
)
from pams.equity.infrastructure import (
    PriceTriggerConfigError,
    StockTargetConfigError,
    YamlPriceTriggerLoader,
    YamlStockTargetLoader,
)
from pams.ips.application import EvaluateCompliance
from pams.ips.domain import ComplianceReport, EvaluationContext, PolicyStatement
from pams.ips.infrastructure import YamlPolicyRepository
from pams.performance.application import ComputePerformanceReport
from pams.performance.domain import PerformanceHistory, PerformanceReport
from pams.portfolio.application import BuildPortfolioSnapshot
from pams.portfolio.domain import (
    AssetCatalog,
    BrokerHolding,
    FxLookup,
    HoldingsProvider,
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
    format_number,
    format_percent,
    metric_description,
    metric_label,
    percent_value,
)
from pams.risk.application import ComputeRiskReport
from pams.risk.domain import RiskReport, ValueSeries
from pams.risk.infrastructure import YamlRiskParametersLoader
from pams.shared_kernel.domain import AssetClass, Currency, Money, Percentage


def _broker_override(
    holding: BrokerHolding,
    *,
    local_price: Money,
    local_quantity: Decimal,
    market_value_base: Money,
) -> dict[str, Any]:
    """실계좌 보유내역(holding)으로 주식 종목 표의 표시값을 재계산한다.

    거래이력 기반 계산은 건드리지 않는다 - 이 함수의 결과는 표시용 dict의 일부
    필드만 덮어쓰는 데 쓰인다. market_value_base는 기존 계산이
    (local_price × local_quantity × 환율)로 만든 값이므로, 그 비율로 환율을
    역산해 새 환율 조회 없이도 같은 통화 환산 기준을 유지한다.
    """
    quantity = holding.quantity
    avg_price = holding.avg_price
    current_price = holding.current_price
    cost_amount = avg_price * quantity
    market_value_local = current_price * quantity
    unrealized_pnl_local = market_value_local - cost_amount
    pnl_ratio = unrealized_pnl_local / cost_amount if cost_amount != 0 else Decimal(0)

    local_denominator = local_price.amount * local_quantity
    fx_rate = market_value_base.amount / local_denominator if local_denominator != 0 else Decimal(1)
    market_value_base_amount = market_value_local * fx_rate
    unrealized_pnl_base_amount = unrealized_pnl_local * fx_rate

    return {
        "quantity": format_number(quantity),
        "avg_price": format_money(Money(avg_price, holding.currency)),
        "current_price": format_money(Money(current_price, holding.currency)),
        "market_value": format_money(Money(market_value_base_amount, market_value_base.currency)),
        "unrealized_pnl": format_money(
            Money(unrealized_pnl_base_amount, market_value_base.currency)
        ),
        "unrealized_percent": format_percent(pnl_ratio),
        "unrealized_positive": unrealized_pnl_base_amount >= 0,
    }


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
    holdings_provider: HoldingsProvider | None = (
        None  # 있으면 주식 종목 표시값을 실계좌 값으로 보강
    )

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
            "today_actions": self._today_actions(snapshot, proposal, as_of),
            "weights": self._weights(snapshot),
            "holdings": self._holdings(snapshot),
            "stocks": self._stocks(snapshot),
            "stock_sleeve": self._stock_sleeve(snapshot),
            "stock_allocation": self._stock_allocation(snapshot, base_currency),
            "targets": self._targets(snapshot, policy),
            "risk": [
                {
                    "name": name,
                    "label": metric_label(name),
                    "value": format_metric(name, value),
                    "description": metric_description(name),
                }
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

    def _today_actions(
        self, snapshot: PortfolioSnapshot, proposal: RebalancingProposal, as_of: date
    ) -> list[dict[str, Any]]:
        """오늘 무엇을 사고/팔지 — 신호원을 우선순위로 합친 액션 목록.

        1) 가격 트리거(사용자가 정한 매수/매도 가격선을 현재가가 건드림)
        2) 리밸런싱 밴드 이탈(자산군 단위)
        DCA(정기매수)는 이미 정해진 일정이라 '액션'이 아니므로 포함하지 않는다.
        시스템은 신호까지만 제시하고 실행은 사용자가 한다.
        """
        names = {v.asset.asset_id: v.asset.name for v in snapshot.valuations}
        actions: list[dict[str, Any]] = []

        # 1) 가격 트리거
        trigger_path = self.config_dir / "triggers" / "default.yaml"
        if trigger_path.exists():
            try:
                plan = YamlPriceTriggerLoader(trigger_path).load()
            except PriceTriggerConfigError:
                plan = None
            if plan is not None:
                prices = {v.asset.asset_id: v.price for v in snapshot.valuations}
                for row in EvaluatePriceTriggers(plan).execute(current_prices=prices).firing:
                    hit = row.trigger.evaluate(row.current_price)
                    assert hit is not None  # firing이므로 hit이 있다
                    is_buy = row.signal is StockSignal.BUY
                    op = "≤" if hit.label in ("매수", "손절") else "≥"
                    actions.append(
                        {
                            "source": "price_trigger",
                            "source_label": "가격 트리거",
                            "asset_id": row.asset_id,
                            "asset": names.get(row.asset_id, row.asset_id),
                            "direction": "buy" if is_buy else "sell",
                            "direction_label": hit.label,  # 매수/익절/손절
                            "reason": (
                                f"현재가 {format_money(row.current_price)} "
                                f"{op} {hit.label}선 {format_money(hit.bound)}"
                            ),
                            "guide": "",
                        }
                    )

        # 2) 리밸런싱 밴드 이탈(자산군 단위)
        for a in proposal.actions:
            is_buy = a.direction is TradeDirection.BUY
            actions.append(
                {
                    "source": "rebalancing",
                    "source_label": "리밸런싱",
                    "asset_id": a.asset_class.value,
                    "asset": asset_class_label(a.asset_class.value),
                    "direction": "buy" if is_buy else "sell",
                    "direction_label": "매수" if is_buy else "매도",
                    "reason": (
                        f"밴드 이탈: 현재 {percent_value(a.current_weight)}% "
                        f"→ 목표 {percent_value(a.target_weight)}%"
                    ),
                    "guide": format_money(a.amount),
                }
            )

        # 매수/매도 신호를 앞으로, 신호원 순서 유지
        order_key = {"price_trigger": 0, "rebalancing": 1}
        actions.sort(key=lambda x: order_key.get(x["source"], 9))
        return actions

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

        values = snapshot.values_by_asset_class()
        weights = snapshot.weights_by_asset_class()
        asset_class = [
            {
                "label": asset_class_label(ac.value),
                "percent": percent_value(weight),
                "value": format_money(values[ac]),
            }
            for ac, weight in sorted(weights.items(), key=lambda item: item[1].ratio, reverse=True)
        ]

        return {
            "asset_class": asset_class,
            "country": entries_from(snapshot.weights_by_country(), str),
            "currency": entries_from(snapshot.weights_by_currency(), lambda c: c.value),
        }

    @staticmethod
    def _stock_sleeve(snapshot: PortfolioSnapshot) -> list[dict[str, str]]:
        """주식(국내주식·미국주식·ETF) 전체 대비 국내/해외 구성.

        국가는 자산 마스터의 country(KR 기준)로 나눈다 - ETF도 국내/해외가 갈리므로
        asset_class만으로는 구분할 수 없다.
        """
        equities = [
            v
            for v in snapshot.valuations
            if v.asset.asset_class.is_equity_like and v.market_value_base.is_positive
        ]
        if not equities:
            return []
        base_currency = snapshot.base_currency
        total = sum((v.market_value_base.amount for v in equities), Decimal(0))
        domestic = sum(
            (v.market_value_base.amount for v in equities if v.asset.country == "KR"),
            Decimal(0),
        )
        foreign = total - domestic

        def pct(amount: Decimal) -> str:
            return percent_value(amount / total) if total > 0 else "0.00"

        return [
            {
                "label": "주식전체",
                "value": format_money(Money(total, base_currency)),
                "percent": pct(total),
            },
            {
                "label": "국내주식",
                "value": format_money(Money(domestic, base_currency)),
                "percent": pct(domestic),
            },
            {
                "label": "해외주식",
                "value": format_money(Money(foreign, base_currency)),
                "percent": pct(foreign),
            },
        ]

    @staticmethod
    def _holdings(snapshot: PortfolioSnapshot) -> list[dict[str, Any]]:
        """종목별 상세: 수량·평단가·현재가·평가금액·평가손익·비중.

        예수금은 종목이 아니므로 제외한다. 주식/ETF 등 실보유 종목만 담는다.
        """
        total = snapshot.total_value.amount
        rows: list[dict[str, Any]] = []
        for v in snapshot.valuations:
            quantity = v.position.quantity.value
            cost_local = v.position.cost_basis
            avg_price = cost_local.amount / quantity if quantity != 0 else Decimal(0)
            pnl_ratio = (
                v.unrealized_pnl_local.amount / cost_local.amount
                if cost_local.amount != 0
                else Decimal(0)
            )
            weight = v.market_value_base.amount / total if total > 0 else Decimal(0)
            rows.append(
                {
                    "asset_id": v.asset.asset_id,
                    "name": v.asset.name,
                    "asset_class": asset_class_label(v.asset.asset_class.value),
                    "asset_class_key": v.asset.asset_class.value,
                    "quantity": format_number(quantity),
                    "avg_price": format_money(Money(avg_price, cost_local.currency)),
                    "current_price": format_money(v.price),
                    "market_value": format_money(v.market_value_base),
                    "unrealized_pnl": format_money(v.unrealized_pnl_base),
                    "unrealized_percent": format_percent(pnl_ratio),
                    "unrealized_positive": v.unrealized_pnl_base.amount >= 0,
                    "weight": percent_value(weight),
                }
            )
        rows.sort(key=lambda r: r["asset_class_key"])
        return rows

    def _stocks(self, snapshot: PortfolioSnapshot) -> list[dict[str, Any]]:
        """주식 종목 상세(주식만): 보유 정보 + 가격 트리거·신호를 한 표로.

        사용자가 '언제 사고 팔지'를 종목 단위로 보는 화면. 채권·금·현금 등은 제외.
        """
        equities = [v for v in snapshot.valuations if v.asset.asset_class.is_equity_like]
        if not equities:
            return []

        plan = None
        trigger_path = self.config_dir / "triggers" / "default.yaml"
        if trigger_path.exists():
            try:
                plan = YamlPriceTriggerLoader(trigger_path).load()
            except PriceTriggerConfigError:
                plan = None

        broker_holdings = self._broker_holdings_by_symbol()
        total = snapshot.total_value.amount
        sleeve_total = sum((v.market_value_base.amount for v in equities), Decimal(0))
        rows: list[dict[str, Any]] = []
        for v in equities:
            quantity = v.position.quantity.value
            cost = v.position.cost_basis
            avg_price = cost.amount / quantity if quantity != 0 else Decimal(0)
            pnl_ratio = (
                v.unrealized_pnl_local.amount / cost.amount if cost.amount != 0 else Decimal(0)
            )
            trigger = plan.trigger_for(v.asset.asset_id) if plan is not None else None

            def line(value: Money | None) -> str:
                return format_money(value) if value is not None else "-"

            if trigger is not None:
                hit = trigger.evaluate(v.price)
                signal = hit.signal.value if hit is not None else "hold"
                label = hit.label if hit is not None else "유지"
                buy_at = line(trigger.buy_at)
                take_profit = line(trigger.take_profit_at)
                stop_loss = line(trigger.stop_loss_at)
            else:
                signal = "none"
                label = "미설정"
                buy_at = take_profit = stop_loss = "-"
            row = {
                "asset_id": v.asset.asset_id,
                "name": v.asset.name,
                "asset_class": asset_class_label(v.asset.asset_class.value),
                "quantity": format_number(quantity),
                "avg_price": format_money(Money(avg_price, cost.currency)),
                "current_price": format_money(v.price),
                "market_value": format_money(v.market_value_base),
                "unrealized_pnl": format_money(v.unrealized_pnl_base),
                "unrealized_percent": format_percent(pnl_ratio),
                "unrealized_positive": v.unrealized_pnl_base.amount >= 0,
                "weight": percent_value(
                    v.market_value_base.amount / total if total > 0 else Decimal(0)
                ),
                "sleeve_weight": percent_value(
                    v.market_value_base.amount / sleeve_total if sleeve_total > 0 else Decimal(0)
                ),
                "buy_trigger": buy_at,
                "take_profit": take_profit,
                "stop_loss": stop_loss,
                "signal": signal,
                "signal_label": label,
            }
            ticker = v.asset.asset_id.rsplit(":", 1)[-1].upper()
            holding = broker_holdings.get(ticker)
            if holding is not None:
                try:
                    row.update(
                        _broker_override(
                            holding,
                            local_price=v.price,
                            local_quantity=quantity,
                            market_value_base=v.market_value_base,
                        )
                    )
                except Exception:
                    # 참고용 보강이므로 한 종목 계산이 실패해도 원장 값으로 표시하고 넘어간다.
                    pass
            rows.append(row)
        rows.sort(key=lambda r: r["name"])
        return rows

    def _broker_holdings_by_symbol(self) -> dict[str, BrokerHolding]:
        """증권사 API 실계좌 잔고를 심볼(대문자) 기준으로 조회.

        실패 시 빈 딕셔너리(표시 저하 없이 무시).
        """
        if self.holdings_provider is None:
            return {}
        try:
            return {h.symbol.upper(): h for h in self.holdings_provider.holdings()}
        except Exception:
            # 증권사 API 장애·타임아웃 등 어떤 실패도 대시보드 전체를 막지 않는다.
            # (참고용 보강 위젯이라 실패 시 원장 값으로 조용히 폴백한다.)
            return {}

    def _stock_allocation(
        self, snapshot: PortfolioSnapshot, base_currency: Currency
    ) -> dict[str, Any]:
        """Tier 2: 주식 슬리브(국내+미국) 내 종목별 목표비중·매수/매도 신호.

        config/stock_targets/default.yaml이 있으면 그 목표를, 없으면 현재 비중을
        목표로 자동 생성한다(프레임워크 우선 - 목표는 사용자가 나중에 조정).
        """
        holdings = {
            v.asset.asset_id: v.market_value_base
            for v in snapshot.valuations
            if v.asset.asset_class.is_equity_like and v.market_value_base.is_positive
        }
        names = {v.asset.asset_id: v.asset.name for v in snapshot.valuations}
        if not holdings:
            return {
                "configured": False,
                "sleeve_value": format_money(Money.zero(base_currency)),
                "rows": [],
            }

        plan, configured = self._load_stock_plan(holdings, base_currency)
        report = EvaluateStockAllocation(plan).execute(
            holdings=holdings, base_currency=base_currency
        )
        signal_label = {"buy": "매수", "sell": "매도", "hold": "유지"}
        rows = [
            {
                "asset_id": r.asset_id,
                "name": names.get(r.asset_id, r.asset_id),
                "current_weight": percent_value(r.current_weight),
                "target": percent_value(r.target.target) if r.target else "-",
                "buy_trigger": percent_value(r.target.buy_trigger) if r.target else "-",
                "sell_trigger": percent_value(r.target.sell_trigger) if r.target else "-",
                "signal": r.signal.value,
                "signal_label": signal_label[r.signal.value],
                "adjust_amount": format_money(r.adjust_amount),
                "adjust_positive": r.adjust_amount.amount >= 0,
            }
            for r in sorted(report.rows, key=lambda x: x.current_weight.ratio, reverse=True)
        ]
        return {
            "configured": configured,
            "sleeve_value": format_money(report.sleeve_value),
            "rows": rows,
        }

    def _load_stock_plan(
        self, holdings: dict[str, Money], base_currency: Currency
    ) -> tuple[StockTargetPlan, bool]:
        path = self.config_dir / "stock_targets" / "default.yaml"
        if path.exists():
            try:
                return YamlStockTargetLoader(path).load(), True
            except StockTargetConfigError:
                pass
        # 설정이 없으면 현재 비중을 목표로 자동 생성(밴드 ±5%p) - 모두 '유지'
        sleeve = sum((m.amount for m in holdings.values()), Decimal(0))
        band = Percentage.from_percent(5)
        targets = tuple(
            StockTarget(
                asset_id=asset_id,
                target=Percentage.from_ratio(value.amount / sleeve),
                buy_band=band,
                sell_band=band,
            )
            for asset_id, value in holdings.items()
        )
        return StockTargetPlan(targets=targets), False

    @staticmethod
    def _targets(snapshot: PortfolioSnapshot, policy: PolicyStatement) -> list[dict[str, Any]]:
        current = snapshot.weights_by_asset_class()
        rows = []
        for target in policy.targets:
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
