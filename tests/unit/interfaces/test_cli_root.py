"""CLI 진입점의 프로젝트 루트 결정 로직 테스트.

pip 설치 환경(예: Docker의 site-packages)에서는 소스 트리 기준 상대경로
계산(parents[N])이 더 이상 저장소 루트를 가리키지 않으므로, PAMS_ROOT
환경변수가 설정되어 있으면 그것을 우선해야 한다(api/app.py와 동일한 패턴).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _restore_cli_module():
    yield
    import pams.interfaces.cli.__main__ as cli_main

    importlib.reload(cli_main)


class TestProjectRoot:
    def test_uses_pams_root_env_when_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("PAMS_ROOT", str(tmp_path))
        import pams.interfaces.cli.__main__ as cli_main

        importlib.reload(cli_main)

        assert cli_main._PROJECT_ROOT == tmp_path

    def test_falls_back_to_source_tree_without_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PAMS_ROOT", raising=False)
        import pams.interfaces.cli.__main__ as cli_main

        importlib.reload(cli_main)

        assert (cli_main._PROJECT_ROOT / "pyproject.toml").exists()
