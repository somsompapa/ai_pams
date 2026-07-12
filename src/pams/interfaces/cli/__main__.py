"""PAMS CLI: python -m pams.interfaces.cli <command>

명령:
  fetch [--root DIR]
      config/market/symbols.yaml의 심볼로 외부 시세/환율/VIX를 수집해
      data/의 prices.csv, fx.csv, market.yaml에 기록한다. snapshot 전에 실행한다.

  snapshot [--date YYYY-MM-DD] [--root DIR]
      해당 일자(기본: 오늘)의 총자산을 data/value_history.jsonl에 적재한다.
      매일 실행(cron 권장)하면 리스크/성과 시계열이 쌓인다.
      과거 시세가 data/prices.csv에 있으면 --date로 과거일 백필도 가능하다.

  report [--date YYYY-MM-DD] [--root DIR]
      전체 투자 보고서(요약/자산배분/IPS 준수/리스크/리밸런싱/성과)를
      reports/ 에 Markdown·HTML로 생성한다. 한글 폰트가 있으면 PDF도 생성.

  alert [--date YYYY-MM-DD] [--root DIR]
      규칙을 평가해 발동(위반/주의)이 있으면 텔레그램으로 알림을 보낸다.
      환경변수 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 필요.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from pams.interfaces.wiring import real_base_currency, real_valuation_recorder

_PROJECT_ROOT = Path(os.environ.get("PAMS_ROOT") or Path(__file__).resolve().parents[4])


def _run_fetch(root: Path, as_of: date) -> int:
    from pams.interfaces.wiring import fetch_market_data

    result = fetch_market_data(root)
    print(f"시세 수집 완료: {result.fetched_count}건")
    for error in result.errors:
        print(f"  경고: {error}", file=sys.stderr)
    return 0 if result.fetched_count > 0 else 1


def _run_snapshot(root: Path, as_of: date) -> int:
    base_currency = real_base_currency(root)
    point = real_valuation_recorder(root).execute(as_of=as_of, base_currency=base_currency)
    print(f"{point.point_date} 총자산 {point.value:,.0f} {base_currency} 적재 완료", end="")
    if point.net_flow != 0:
        print(f" (당일 입출금 {point.net_flow:+,.0f})", end="")
    print()
    return 0


def _run_report(root: Path, as_of: date) -> int:
    from pams.interfaces.wiring import real_dashboard_service
    from pams.reporting.application import AssembleInvestmentReport, GenerateReport
    from pams.reporting.infrastructure import (
        FileSystemReportSink,
        HtmlRenderer,
        MarkdownRenderer,
        PdfRenderer,
        find_korean_font,
    )

    outputs = real_dashboard_service(root).compute(
        as_of=as_of, base_currency=real_base_currency(root)
    )
    document = AssembleInvestmentReport().execute(
        title=f"투자 보고서 {as_of.isoformat()}",
        snapshot=outputs.snapshot,
        compliance=outputs.compliance,
        risk=outputs.risk,
        proposal=outputs.proposal,
        performance=outputs.performance,
    )
    sink = FileSystemReportSink(base_dir=root / "reports")
    stem = f"report-{as_of.isoformat()}"
    for renderer, extension in ((MarkdownRenderer(), "md"), (HtmlRenderer(), "html")):
        saved = GenerateReport(renderer=renderer, sink=sink).execute(
            document=document, filename=f"{stem}.{extension}"
        )
        print(f"생성: {saved}")
    font = find_korean_font()
    if font is None:
        print("PDF 생략: 한글 TTF 폰트가 없다 (예: apt-get install fonts-nanum)")
        return 0
    pdf_bytes = PdfRenderer(font_path=font).render(document).encode("latin-1")
    pdf_path = root / "reports" / f"{stem}.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(pdf_bytes)
    print(f"생성: {pdf_path}")
    return 0


def _run_alert(root: Path, as_of: date) -> int:
    import os

    from pams.interfaces.notifications import TelegramNotifier, format_alert, run_alert
    from pams.interfaces.wiring import real_dashboard_service

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("실패: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 필요하다", file=sys.stderr)
        return 1
    outputs = real_dashboard_service(root).compute(
        as_of=as_of, base_currency=real_base_currency(root)
    )
    sent = run_alert(
        compliance=outputs.compliance, notifier=TelegramNotifier(token=token, chat_id=chat_id)
    )
    if sent:
        print("알림 전송 완료:")
        print(format_alert(outputs.compliance))
    else:
        print("발동한 규칙이 없어 알림을 보내지 않았다")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pams")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name, description in (
        ("fetch", "외부 시세/환율/VIX 수집"),
        ("snapshot", "총자산을 가치 이력에 적재"),
        ("report", "투자 보고서 생성 (reports/)"),
        ("alert", "규칙 발동 시 텔레그램 알림"),
    ):
        sub = subcommands.add_parser(name, help=description)
        sub.add_argument("--date", dest="as_of", default=None, help="YYYY-MM-DD (기본: 오늘)")
        sub.add_argument("--root", default=None, help="프로젝트 루트 (기본: 저장소 루트)")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else _PROJECT_ROOT
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    runners = {
        "fetch": _run_fetch,
        "snapshot": _run_snapshot,
        "report": _run_report,
        "alert": _run_alert,
    }

    try:
        return runners[args.command](root, as_of)
    except Exception as error:  # CLI 최상위 - 원인 메시지를 그대로 보여준다
        print(f"실패: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
