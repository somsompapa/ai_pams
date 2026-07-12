"""AssembleInvestmentReport(엔진 출력 → 보고서 문서 조립) 테스트."""

from datetime import date
from decimal import Decimal

from pams.ips.domain import (
    ComparisonOperator,
    ComplianceReport,
    Condition,
    Rule,
    RuleAction,
    RuleEvaluation,
    Severity,
)
from pams.performance.domain import PerformanceReport, PeriodPerformance
from pams.portfolio.domain import PortfolioSnapshot, PortfolioValuator, Position
from pams.rebalancing.domain import (
    RebalancingAction,
    RebalancingProposal,
    TradeDirection,
)
from pams.reporting.application import AssembleInvestmentReport
from pams.reporting.domain import KeyValueBlock, TableBlock
from pams.risk.domain import RiskReport
from pams.shared_kernel.domain import (
    Asset,
    AssetClass,
    Currency,
    Money,
    Percentage,
    Quantity,
)

AS_OF = date(2026, 7, 10)
KRW = Currency.KRW

SAMSUNG = Asset(
    asset_id="KRX:005930",
    name="삼성전자",
    asset_class=AssetClass.DOMESTIC_STOCK,
    currency=KRW,
    country="KR",
    sector="Information Technology",
)


def snapshot() -> PortfolioSnapshot:
    return PortfolioValuator().valuate(
        as_of=AS_OF,
        base_currency=KRW,
        positions={
            SAMSUNG.asset_id: Position(
                asset_id=SAMSUNG.asset_id,
                quantity=Quantity.of(10),
                cost_basis=Money.of("700000", KRW),
                realized_pnl=Money.zero(KRW),
            )
        },
        assets={SAMSUNG.asset_id: SAMSUNG},
        prices={SAMSUNG.asset_id: Money.of("75000", KRW)},
        fx_rates={},
        cash_balances={KRW: Money.of("250000", KRW)},
    )


def compliance() -> ComplianceReport:
    rule = Rule(
        rule_id="min-cash-weight",
        description="현금성 자산 비중은 10% 이상이어야 한다",
        severity=Severity.VIOLATION,
        conditions=(Condition("cash_weight", ComparisonOperator.LT, Decimal("0.10")),),
        action=RuleAction(action_type="block_new_buys"),
    )
    return ComplianceReport(
        as_of=AS_OF,
        evaluations=(
            RuleEvaluation(rule=rule, triggered=True, observed={"cash_weight": Decimal("0.05")}),
        ),
    )


def proposal() -> RebalancingProposal:
    return RebalancingProposal(
        as_of=AS_OF,
        base_currency=KRW,
        actions=(
            RebalancingAction(
                asset_class=AssetClass.DOMESTIC_STOCK,
                direction=TradeDirection.SELL,
                amount=Money.of("150000", KRW),
                estimated_fee=Money.of("23", KRW),
                estimated_tax=Money.of("270", KRW),
                current_weight=Percentage.from_percent(75),
                target_weight=Percentage.from_percent(60),
            ),
        ),
    )


def risk() -> RiskReport:
    return RiskReport(as_of=AS_OF, metrics={"mdd": Decimal("0.1"), "sharpe": Decimal("1.6")})


def performance() -> PerformanceReport:
    return PerformanceReport(
        as_of=AS_OF,
        cumulative_twr=Decimal("0.21"),
        cumulative_benchmark_twr=Decimal("0.1"),
        monthly=(PeriodPerformance(label="2026-01", twr=Decimal("0.21"), benchmark_twr=None),),
        quarterly=(),
        yearly=(),
        win_rate=Decimal("0.5"),
        compliance_rate=Decimal("0.75"),
    )


class TestAssembler:
    def assemble_full(self):  # type: ignore[no-untyped-def]
        return AssembleInvestmentReport().execute(
            title="월간 투자 보고서",
            snapshot=snapshot(),
            compliance=compliance(),
            risk=risk(),
            proposal=proposal(),
            performance=performance(),
        )

    def test_full_report_has_all_sections(self) -> None:
        document = self.assemble_full()
        headings = [s.heading for s in document.sections]
        assert headings == [
            "요약",
            "자산배분",
            "IPS 준수 현황",
            "리스크 지표",
            "리밸런싱 제안",
            "성과 분석",
        ]
        assert document.as_of == AS_OF

    def test_summary_contains_total_value_and_compliance(self) -> None:
        document = self.assemble_full()
        summary = document.sections[0]
        kv = next(b for b in summary.blocks if isinstance(b, KeyValueBlock))
        items = dict(kv.items)
        assert items["총자산"] == "1,000,000 KRW"
        assert items["평가손익"] == "50,000 KRW"
        assert items["IPS 준수"] == "위반 1건"

    def test_violation_row_present(self) -> None:
        document = self.assemble_full()
        compliance_section = document.sections[2]
        table = next(b for b in compliance_section.blocks if isinstance(b, TableBlock))
        assert any("min-cash-weight" in row for row in table.rows)

    def test_rebalancing_actions_table(self) -> None:
        document = self.assemble_full()
        rebalancing_section = document.sections[4]
        table = next(b for b in rebalancing_section.blocks if isinstance(b, TableBlock))
        row = table.rows[0]
        assert "매도" in row
        assert "150,000 KRW" in row

    def test_optional_parts_can_be_omitted(self) -> None:
        document = AssembleInvestmentReport().execute(title="요약 보고서", snapshot=snapshot())
        headings = [s.heading for s in document.sections]
        assert headings == ["요약", "자산배분"]

    def test_no_rebalancing_needed_message(self) -> None:
        empty = RebalancingProposal(as_of=AS_OF, base_currency=KRW, actions=())
        document = AssembleInvestmentReport().execute(
            title="보고서", snapshot=snapshot(), proposal=empty
        )
        rebalancing_section = next(s for s in document.sections if s.heading == "리밸런싱 제안")
        texts = [b.text for b in rebalancing_section.blocks if hasattr(b, "text")]
        assert any("불필요" in t for t in texts)

    def test_ai_commentary_section_with_disclaimer(self) -> None:
        """AI 해설은 마지막 섹션이며, 'AI는 계산에 관여하지 않는다' 고지를 반드시 포함한다."""
        document = AssembleInvestmentReport().execute(
            title="보고서",
            snapshot=snapshot(),
            ai_commentary="포트폴리오는 IT 섹터 집중도가 높은 상태다.",
        )
        ai_section = document.sections[-1]
        assert ai_section.heading == "AI 해설"
        texts = [b.text for b in ai_section.blocks if hasattr(b, "text")]
        assert any("IT 섹터" in t for t in texts)
        assert any("계산" in t and "관여하지 않" in t for t in texts)

    def test_without_ai_commentary_no_section(self) -> None:
        document = AssembleInvestmentReport().execute(title="보고서", snapshot=snapshot())
        assert all(s.heading != "AI 해설" for s in document.sections)
