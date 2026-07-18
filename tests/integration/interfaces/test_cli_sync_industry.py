"""`pams sync-industry` CLI 통합 테스트.

DART/SEC 공급자는 CLI 레벨에서 주입할 수 없으므로(실제 데이터 동기화 도구이기
때문), 등록된 국내/미국 주식이 없는 프로젝트로 실행해 실네트워크 호출 없이
argparse→wiring 경로만 검증한다. 공급자 로직 자체는
tests/integration/equity/test_sync_industry_classifications.py에서 페이크 주입으로
따로 검증한다."""

from pathlib import Path


class TestSyncIndustryCli:
    def test_runs_without_network_when_no_stocks_registered(self, tmp_path: Path) -> None:
        from pams.interfaces.cli.__main__ import main

        (tmp_path / "config" / "assets").mkdir(parents=True)
        (tmp_path / "config" / "assets" / "default.yaml").write_text(
            "assets: []\n", encoding="utf-8"
        )

        exit_code = main(["sync-industry", "--root", str(tmp_path)])

        assert exit_code == 0
        assert (tmp_path / "data" / "industry_map.json").exists()
