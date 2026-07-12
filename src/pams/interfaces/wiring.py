"""실데이터 조립(composition root): config/ + data/ 파일 어댑터로 시스템을 구성한다.

필요한 파일:
- config/assets/default.yaml     자산 마스터 (자산군/통화/국가/섹터)
- data/transactions.csv          거래 기록 (원천 데이터)
- data/prices.csv                시세 (asset_id,price_date,close,currency)
- data/fx.csv                    환율 (base,quote,rate_date,rate) - 외화 자산이 있을 때
- data/market.yaml               시장 지표 (예: vix) - 규칙이 참조하는 지표
- data/value_history.jsonl       일별 총자산 이력 - `make snapshot`이 적재
- data/benchmark.csv (선택)      벤치마크 (bench_date,value) - 있으면 비교 지표 생성
- config/market/symbols.yaml      시세 자동수집 심볼 매핑 (`make fetch`가 사용)

파일 형식 예시는 examples/ 디렉토리 참고.
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from pams.asset.infrastructure import YamlAssetCatalog
from pams.interfaces.api.service import DashboardService
from pams.ips.infrastructure import YamlPolicyRepository
from pams.market_data.application import FetchMarketData, FetchResult
from pams.market_data.domain import QuoteProvider, SymbolMap
from pams.market_data.infrastructure import (
    CsvFxLookup,
    CsvPriceLookup,
    MarketDataFileWriter,
    YahooQuoteProvider,
)
from pams.performance.domain import PerformanceHistory, ValuationPoint
from pams.performance.infrastructure import JsonlValueHistoryRepository
from pams.portfolio.application import BuildPortfolioSnapshot, RecordDailyValuation
from pams.portfolio.infrastructure import CsvTransactionRepository
from pams.risk.domain import ValueSeries
from pams.shared_kernel.domain import Currency

_MIN_HISTORY_POINTS = 3  # 리스크/성과 계산에 필요한 최소 적재 일수


class RealDataError(Exception):
    """실데이터 파일이 없거나 부족하다. 메시지에 해결 방법이 담긴다."""


def real_base_currency(project_root: Path) -> Currency:
    policy = YamlPolicyRepository(
        ips_path=project_root / "config" / "ips" / "default.yaml",
        rules_path=project_root / "config" / "rules" / "default.yaml",
    ).load()
    return policy.base_currency


def real_snapshot_builder(project_root: Path) -> BuildPortfolioSnapshot:
    data = project_root / "data"
    return BuildPortfolioSnapshot(
        transactions=CsvTransactionRepository(data / "transactions.csv"),
        assets=YamlAssetCatalog(project_root / "config" / "assets" / "default.yaml"),
        prices=CsvPriceLookup(data / "prices.csv"),
        fx=CsvFxLookup(data / "fx.csv"),
    )


def real_valuation_recorder(project_root: Path) -> RecordDailyValuation:
    return RecordDailyValuation(
        snapshot_builder=real_snapshot_builder(project_root),
        history=JsonlValueHistoryRepository(project_root / "data" / "value_history.jsonl"),
    )


def _market_metrics(path: Path) -> dict[str, Decimal]:
    if not path.exists():
        raise RealDataError(
            f"시장 지표 파일이 없다: {path} - 규칙이 참조하는 지표(vix 등)를 채워라. "
            "예시: examples/market.yaml"
        )
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RealDataError(f"{path}: 최상위는 매핑(지표: 값)이어야 한다")
    metrics = {}
    for name, value in document.items():
        try:
            metrics[str(name)] = Decimal(str(value))
        except InvalidOperation:
            raise RealDataError(f"{path}: 지표 '{name}' 값이 숫자가 아니다: {value!r}") from None
    return metrics


def _benchmark(path: Path) -> tuple[ValueSeries, PerformanceHistory] | None:
    if not path.exists():
        return None
    pairs: list[tuple[date, Decimal]] = []
    for row_number, row in enumerate(
        csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()), start=2
    ):
        where = f"{path} {row_number}행"
        try:
            pairs.append(
                (
                    date.fromisoformat((row.get("bench_date") or "").strip()),
                    Decimal((row.get("value") or "").strip()),
                )
            )
        except (ValueError, InvalidOperation):
            raise RealDataError(f"{where}: 잘못된 벤치마크 행 {row!r}") from None
    if len(pairs) < _MIN_HISTORY_POINTS:
        return None
    series = ValueSeries.from_pairs(pairs)
    history = PerformanceHistory.from_points(
        [ValuationPoint(point_date=d, value=v, net_flow=Decimal(0)) for d, v in pairs]
    )
    return series, history


def load_symbol_map(project_root: Path) -> SymbolMap:
    path = project_root / "config" / "market" / "symbols.yaml"
    if not path.exists():
        raise RealDataError(f"심볼 매핑 파일이 없다: {path} - 예시: examples/symbols.yaml")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        raise RealDataError(f"{path}: 최상위는 매핑이어야 한다")
    return SymbolMap.from_dict(document)


def fetch_market_data(project_root: Path, provider: QuoteProvider | None = None) -> FetchResult:
    """외부 시세를 수집해 data/의 prices.csv/fx.csv/market.yaml에 기록한다.

    provider 미지정 시 Yahoo Finance를 사용한다 (테스트는 페이크 주입).
    """
    symbols = load_symbol_map(project_root)
    quote_provider = provider if provider is not None else YahooQuoteProvider()
    result = FetchMarketData(provider=quote_provider).execute(symbols=symbols)
    MarketDataFileWriter(data_dir=project_root / "data").write(result)
    return result


def real_dashboard_service(project_root: Path) -> DashboardService:
    data = project_root / "data"
    history = JsonlValueHistoryRepository(data / "value_history.jsonl").load()
    if history is None or len(history.points) < _MIN_HISTORY_POINTS:
        recorded = 0 if history is None else len(history.points)
        raise RealDataError(
            f"가치 이력이 부족하다 (현재 {recorded}점, 최소 {_MIN_HISTORY_POINTS}점). "
            "`make snapshot`을 매일 실행하거나, 과거 시세를 data/prices.csv에 넣고 "
            "`python -m pams.interfaces.cli snapshot --date YYYY-MM-DD`로 백필하라."
        )
    portfolio_values = ValueSeries.from_pairs([(p.point_date, p.value) for p in history.points])
    benchmark = _benchmark(data / "benchmark.csv")
    return DashboardService(
        config_dir=project_root / "config",
        transactions=CsvTransactionRepository(data / "transactions.csv"),
        assets=YamlAssetCatalog(project_root / "config" / "assets" / "default.yaml"),
        prices=CsvPriceLookup(data / "prices.csv"),
        fx=CsvFxLookup(data / "fx.csv"),
        portfolio_values=portfolio_values,
        performance_history=history,
        market_metrics=_market_metrics(data / "market.yaml"),
        benchmark_values=benchmark[0] if benchmark is not None else None,
        benchmark_history=benchmark[1] if benchmark is not None else None,
    )
