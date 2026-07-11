"""PAMS CLI: python -m pams.interfaces.cli <command>

명령:
  snapshot [--date YYYY-MM-DD] [--root DIR]
      해당 일자(기본: 오늘)의 총자산을 data/value_history.jsonl에 적재한다.
      매일 실행(cron 권장)하면 리스크/성과 시계열이 쌓인다.
      과거 시세가 data/prices.csv에 있으면 --date로 과거일 백필도 가능하다.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from pams.interfaces.wiring import real_base_currency, real_valuation_recorder

_PROJECT_ROOT = Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pams")
    subcommands = parser.add_subparsers(dest="command", required=True)
    snapshot = subcommands.add_parser("snapshot", help="총자산을 가치 이력에 적재")
    snapshot.add_argument("--date", dest="as_of", default=None, help="YYYY-MM-DD (기본: 오늘)")
    snapshot.add_argument("--root", default=None, help="프로젝트 루트 (기본: 저장소 루트)")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else _PROJECT_ROOT
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    try:
        base_currency = real_base_currency(root)
        point = real_valuation_recorder(root).execute(as_of=as_of, base_currency=base_currency)
    except Exception as error:  # CLI 최상위 - 원인 메시지를 그대로 보여준다
        print(f"실패: {error}", file=sys.stderr)
        return 1

    print(f"{point.point_date} 총자산 {point.value:,.0f} {base_currency} 적재 완료", end="")
    if point.net_flow != 0:
        print(f" (당일 입출금 {point.net_flow:+,.0f})", end="")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
