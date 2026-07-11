"""AssembleInvestmentReport: 각 엔진의 공개 출력 → 보고서 문서 조립.

다른 컨텍스트와의 통신 규약: 이 유스케이스가 받는 타입들은 각 컨텍스트
유스케이스의 반환 타입(공개 API, published language)이다. 각 컨텍스트의
내부 구현이나 infrastructure는 여기서 절대 참조하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from pams.ips.domain import ComplianceReport, RuleEvaluation
from pams.performance.domain import PerformanceReport
from pams.portfolio.domain import PortfolioSnapshot
from pams.rebalancing.domain import RebalancingProposal, TradeDirection
from pams.reporting.application.formatting import (
    asset_class_label,
    format_metric,
    format_money,
    format_percent,
    metric_label,
)
from pams.reporting.domain import (
    Block,
    KeyValueBlock,
    Paragraph,
    ReportDocument,
    Section,
    TableBlock,
)
from pams.risk.domain import RiskReport


@dataclass(frozen=True, slots=True)
class AssembleInvestmentReport:
    def execute(
        self,
        *,
        title: str,
        snapshot: PortfolioSnapshot,
        compliance: ComplianceReport | None = None,
        risk: RiskReport | None = None,
        proposal: RebalancingProposal | None = None,
        performance: PerformanceReport | None = None,
        ai_commentary: str | None = None,
    ) -> ReportDocument:
        sections = [
            self._summary(snapshot, compliance, performance),
            self._allocation(snapshot),
        ]
        if compliance is not None:
            sections.append(self._compliance(compliance))
        if risk is not None:
            sections.append(self._risk(risk))
        if proposal is not None:
            sections.append(self._rebalancing(proposal))
        if performance is not None:
            sections.append(self._performance(performance))
        if ai_commentary is not None:
            sections.append(self._ai_commentary(ai_commentary))
        return ReportDocument(title=title, as_of=snapshot.as_of, sections=tuple(sections))

    @staticmethod
    def _ai_commentary(commentary: str) -> Section:
        return Section(
            heading="AI 해설",
            blocks=(
                Paragraph(text=commentary),
                Paragraph(
                    text=(
                        "위 해설은 AI(Claude)가 작성했다. AI는 계산에 관여하지 않으며, "
                        "본 보고서의 모든 수치와 판정은 Rule/계산 엔진의 출력이다."
                    )
                ),
            ),
        )

    @staticmethod
    def _summary(
        snapshot: PortfolioSnapshot,
        compliance: ComplianceReport | None,
        performance: PerformanceReport | None,
    ) -> Section:
        items: list[tuple[str, str]] = [
            ("총자산", format_money(snapshot.total_value)),
            ("평가손익", format_money(snapshot.total_unrealized_pnl)),
            ("실현손익", format_money(snapshot.total_realized_pnl)),
        ]
        if performance is not None:
            items.append(("누적수익률(TWR)", format_percent(performance.cumulative_twr)))
        if compliance is not None:
            violations = len(compliance.violations)
            status = "준수" if compliance.is_compliant else f"위반 {violations}건"
            items.append(("IPS 준수", status))
        return Section(heading="요약", blocks=(KeyValueBlock(items=tuple(items)),))

    @staticmethod
    def _allocation(snapshot: PortfolioSnapshot) -> Section:
        rows = tuple(
            (asset_class_label(asset_class.value), format_percent(weight))
            for asset_class, weight in sorted(
                snapshot.weights_by_asset_class().items(),
                key=lambda item: item[1].ratio,
                reverse=True,
            )
        )
        return Section(
            heading="자산배분",
            blocks=(TableBlock(headers=("자산군", "비중"), rows=rows),),
        )

    @staticmethod
    def _compliance(compliance: ComplianceReport) -> Section:
        blocks: list[Block] = []
        triggered = compliance.violations + compliance.warnings
        if not triggered:
            blocks.append(Paragraph(text="발동한 규칙이 없다. 포트폴리오는 IPS를 준수하고 있다."))
        else:
            blocks.append(
                TableBlock(
                    headers=("규칙", "심각도", "내용", "관측값"),
                    rows=tuple(_rule_row(e) for e in triggered),
                )
            )
        return Section(heading="IPS 준수 현황", blocks=tuple(blocks))

    @staticmethod
    def _risk(risk: RiskReport) -> Section:
        items = [
            (metric_label(name), format_metric(name, value)) for name, value in risk.metrics.items()
        ]
        return Section(heading="리스크 지표", blocks=(KeyValueBlock(items=tuple(items)),))

    @staticmethod
    def _rebalancing(proposal: RebalancingProposal) -> Section:
        if not proposal.is_rebalancing_needed:
            return Section(
                heading="리밸런싱 제안",
                blocks=(
                    Paragraph(text="모든 자산군이 허용밴드 안에 있다. 리밸런싱이 불필요하다."),
                ),
            )
        rows = tuple(
            (
                asset_class_label(action.asset_class.value),
                "매도" if action.direction is TradeDirection.SELL else "매수",
                format_money(action.amount),
                format_percent(action.current_weight),
                format_percent(action.target_weight),
                format_money(action.estimated_cost),
            )
            for action in proposal.actions
        )
        summary = KeyValueBlock(
            items=(
                ("총 매도", format_money(proposal.total_sell_amount)),
                ("총 매수", format_money(proposal.total_buy_amount)),
                ("예상 총비용", format_money(proposal.total_estimated_cost)),
            )
        )
        table = TableBlock(
            headers=("자산군", "방향", "금액", "현재비중", "목표비중", "예상비용"), rows=rows
        )
        note = Paragraph(text="본 제안은 계산 결과이며, 실행 여부는 사용자가 결정한다.")
        return Section(heading="리밸런싱 제안", blocks=(summary, table, note))

    @staticmethod
    def _performance(performance: PerformanceReport) -> Section:
        items: list[tuple[str, str]] = [
            ("누적수익률(TWR)", format_percent(performance.cumulative_twr))
        ]
        if performance.cumulative_benchmark_twr is not None:
            items.append(("벤치마크 누적", format_percent(performance.cumulative_benchmark_twr)))
        if performance.cumulative_excess is not None:
            items.append(("누적 초과수익", format_percent(performance.cumulative_excess)))
        if performance.win_rate is not None:
            items.append(("승률", format_percent(performance.win_rate)))
        if performance.compliance_rate is not None:
            items.append(("규칙 준수율", format_percent(performance.compliance_rate)))

        blocks: list[Block] = [KeyValueBlock(items=tuple(items))]
        if performance.monthly:
            rows = tuple(
                (
                    period.label,
                    format_percent(period.twr),
                    format_percent(period.benchmark_twr)
                    if period.benchmark_twr is not None
                    else "-",
                    format_percent(period.excess) if period.excess is not None else "-",
                )
                for period in performance.monthly
            )
            blocks.append(TableBlock(headers=("월", "수익률", "벤치마크", "초과수익"), rows=rows))
        return Section(heading="성과 분석", blocks=tuple(blocks))


def _rule_row(evaluation: RuleEvaluation) -> tuple[str, str, str, str]:
    observed = ", ".join(f"{name}={value}" for name, value in evaluation.observed.items())
    return (
        evaluation.rule.rule_id,
        str(evaluation.rule.severity),
        evaluation.rule.description,
        observed,
    )
