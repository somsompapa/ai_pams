"""Phase 1 스모크 테스트: 바운디드 컨텍스트 골격이 규약대로 존재하는지 검증한다.

이 테스트는 이후 Phase에서 누군가 실수로 모듈 경계를 삭제/변형하는 것을 조기에 잡아낸다.
"""

import importlib
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "pams"

# 3계층(domain/application/infrastructure)을 모두 갖는 바운디드 컨텍스트
LAYERED_CONTEXTS = [
    "asset",
    "ips",
    "portfolio",
    "risk",
    "rebalancing",
    "performance",
    "market_data",
    "reporting",
    "journal",
    "ai_analysis",
    "audit",
]

LAYERS = ["domain", "application", "infrastructure"]


def test_package_importable() -> None:
    pams = importlib.import_module("pams")
    assert pams.__version__


@pytest.mark.parametrize("context", LAYERED_CONTEXTS)
@pytest.mark.parametrize("layer", LAYERS)
def test_context_has_clean_architecture_layers(context: str, layer: str) -> None:
    importlib.import_module(f"pams.{context}.{layer}")


def test_shared_kernel_is_domain_only() -> None:
    """shared_kernel은 공유 값객체만 담는다 - 유스케이스/어댑터 계층이 있으면 안 된다."""
    importlib.import_module("pams.shared_kernel.domain")
    assert not (SRC_ROOT / "shared_kernel" / "application").exists()
    assert not (SRC_ROOT / "shared_kernel" / "infrastructure").exists()


def test_interfaces_entrypoints_exist() -> None:
    importlib.import_module("pams.interfaces.cli")
    importlib.import_module("pams.interfaces.api")


def test_config_files_exist() -> None:
    config_root = SRC_ROOT.parents[1] / "config"
    assert (config_root / "app" / "app.yaml").is_file()
    assert (config_root / "ips").is_dir()
    assert (config_root / "rules").is_dir()
