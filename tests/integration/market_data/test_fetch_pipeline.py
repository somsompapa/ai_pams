"""시세 수집 → 파일 기록 전체 파이프라인 통합 테스트 (HTTP 목킹)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx

from pams.market_data.application import FetchMarketData
from pams.market_data.domain import Quote, SymbolMap
from pams.market_data.infrastructure import MarketDataFileWriter, YahooQuoteProvider
from pams.shared_kernel.domain import Currency

SYMBOLS = SymbolMap.from_dict(
    {
        "prices": {"KRX:005930": "005930.KS", "NASDAQ:AAPL": "AAPL"},
        "fx": {"USD/KRW": "KRW=X"},
        "indicators": {"vix": "^VIX"},
    }
)

# 심볼별 응답 (regularMarketTime: 2026-07-10 12:00 UTC = 1783684800)
RESPONSES = {
    "005930.KS": (75000.0, "KRW"),
    "AAPL": (220.0, "USD"),
    "KRW=X": (1380.0, "KRW"),
    "^VIX": (24.5, "USD"),
}


def handler(request: httpx.Request) -> httpx.Response:
    symbol = request.url.path.rsplit("/", 1)[-1]
    if symbol not in RESPONSES:
        return httpx.Response(404, json={"chart": {"result": None}})
    price, currency = RESPONSES[symbol]
    return httpx.Response(
        200,
        json={
            "chart": {
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": price,
                            "currency": currency,
                            "regularMarketTime": 1783684800,
                        }
                    }
                ]
            }
        },
    )


def make_result():  # type: ignore[no-untyped-def]
    provider = YahooQuoteProvider(transport=httpx.MockTransport(handler))
    return FetchMarketData(provider=provider).execute(symbols=SYMBOLS)


class TestFetchPipeline:
    def test_fetch_all(self) -> None:
        result = make_result()
        assert result.errors == []
        assert result.prices["KRX:005930"].close == Decimal("75000.0")
        assert result.fx[(Currency.USD, Currency.KRW)] == Decimal("1380.0")
        assert result.indicators["vix"] == Decimal("24.5")

    def test_writer_creates_files(self, tmp_path: Path) -> None:
        MarketDataFileWriter(data_dir=tmp_path).write(make_result())

        prices = (tmp_path / "prices.csv").read_text(encoding="utf-8")
        assert "asset_id,price_date,close,currency" in prices
        assert "KRX:005930,2026-07-10,75000.0,KRW" in prices
        assert "NASDAQ:AAPL,2026-07-10,220.0,USD" in prices

        fx = (tmp_path / "fx.csv").read_text(encoding="utf-8")
        assert "USD,KRW,2026-07-10,1380.0" in fx

        market = (tmp_path / "market.yaml").read_text(encoding="utf-8")
        assert "vix: '24.5'" in market or "vix: 24.5" in market

    def test_writer_is_idempotent_same_day(self, tmp_path: Path) -> None:
        writer = MarketDataFileWriter(data_dir=tmp_path)
        writer.write(make_result())
        writer.write(make_result())
        prices = (tmp_path / "prices.csv").read_text(encoding="utf-8").strip().splitlines()
        # 헤더 1 + 종목 2 = 3줄 (중복 적재 없음)
        assert len(prices) == 3

    def test_writer_preserves_other_dates(self, tmp_path: Path) -> None:
        (tmp_path / "prices.csv").write_text(
            "asset_id,price_date,close,currency\nKRX:005930,2026-07-09,74000,KRW\n",
            encoding="utf-8",
        )
        MarketDataFileWriter(data_dir=tmp_path).write(make_result())
        prices = (tmp_path / "prices.csv").read_text(encoding="utf-8")
        assert "KRX:005930,2026-07-09,74000,KRW" in prices  # 과거 행 보존
        assert "KRX:005930,2026-07-10,75000.0,KRW" in prices  # 새 행 추가

    def test_written_files_readable_by_lookups(self, tmp_path: Path) -> None:
        from pams.market_data.infrastructure import CsvFxLookup, CsvPriceLookup

        MarketDataFileWriter(data_dir=tmp_path).write(make_result())
        price = CsvPriceLookup(tmp_path / "prices.csv").price_of("KRX:005930", date(2026, 7, 10))
        assert price is not None and price.amount == Decimal("75000.0")
        rate = CsvFxLookup(tmp_path / "fx.csv").rate_to(
            Currency.USD, Currency.KRW, date(2026, 7, 10)
        )
        assert rate == Decimal("1380.0")


def test_symbol_map_provider_port() -> None:
    """Quote는 값객체로 직접 생성 가능해야 한다 (writer 단위 검증용)."""
    q = Quote(symbol="X", quote_date=date(2026, 7, 10), close=Decimal("1"), currency=Currency.KRW)
    assert q.symbol == "X"


class TestFetchCli:
    def test_fetch_command_populates_data_files(self, tmp_path: Path) -> None:
        import shutil

        from pams.interfaces.wiring import fetch_market_data

        repo_root = Path(__file__).resolve().parents[3]
        shutil.copytree(repo_root / "config", tmp_path / "config")
        (tmp_path / "data").mkdir()

        # provider를 주입해 실제 네트워크 없이 검증
        provider = YahooQuoteProvider(transport=httpx.MockTransport(handler))
        result = fetch_market_data(tmp_path, provider=provider)
        assert result.fetched_count > 0
        assert (tmp_path / "data" / "prices.csv").exists()
        assert (tmp_path / "data" / "market.yaml").exists()

    def test_fetch_cli_reports_missing_symbol_config(
        self, tmp_path: Path, capsys: "object"
    ) -> None:
        from pams.interfaces.cli.__main__ import main

        exit_code = main(["fetch", "--root", str(tmp_path)])
        assert exit_code == 1  # config 없음
