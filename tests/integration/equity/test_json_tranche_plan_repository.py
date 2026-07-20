"""JsonTranchePlanRepository 통합 테스트 (실제 파일시스템 왕복)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from pams.equity.domain.tranche_plan import ScoreItemSnapshot, ScoreSnapshot, TranchePlan
from pams.equity.infrastructure import JsonTranchePlanRepository


def _plan(asset_id: str = "TEST", tranches_bought: int = 1) -> TranchePlan:
    return TranchePlan(
        asset_id=asset_id,
        first_tranche_price=Decimal("100.50"),
        target_quantity=Decimal(100),
        baseline=ScoreSnapshot(
            total_score=Decimal(85),
            items=(
                ScoreItemSnapshot(metric="ROE", score=Decimal(10), missing=False),
                ScoreItemSnapshot(metric="EPS 3Y CAGR", score=Decimal(0), missing=True),
            ),
        ),
        tranches_bought=tranches_bought,
        created_at=date(2026, 1, 15),
    )


class TestJsonTranchePlanRepository:
    def test_get_returns_none_when_no_plan_exists(self, tmp_path: Path) -> None:
        repo = JsonTranchePlanRepository(tmp_path / "tranche_plans.json")
        assert repo.get("TEST") is None

    def test_save_then_get_round_trips(self, tmp_path: Path) -> None:
        repo = JsonTranchePlanRepository(tmp_path / "tranche_plans.json")
        plan = _plan()
        repo.save(plan)
        loaded = repo.get("TEST")
        assert loaded == plan

    def test_save_preserves_other_assets(self, tmp_path: Path) -> None:
        repo = JsonTranchePlanRepository(tmp_path / "tranche_plans.json")
        repo.save(_plan("A"))
        repo.save(_plan("B"))
        assert repo.get("A") is not None
        assert repo.get("B") is not None

    def test_save_overwrites_same_asset(self, tmp_path: Path) -> None:
        repo = JsonTranchePlanRepository(tmp_path / "tranche_plans.json")
        repo.save(_plan("TEST", tranches_bought=1))
        repo.save(_plan("TEST", tranches_bought=2))
        loaded = repo.get("TEST")
        assert loaded is not None
        assert loaded.tranches_bought == 2

    def test_delete_removes_plan(self, tmp_path: Path) -> None:
        repo = JsonTranchePlanRepository(tmp_path / "tranche_plans.json")
        repo.save(_plan())
        repo.delete("TEST")
        assert repo.get("TEST") is None

    def test_delete_missing_asset_is_a_no_op(self, tmp_path: Path) -> None:
        repo = JsonTranchePlanRepository(tmp_path / "tranche_plans.json")
        repo.delete("NOPE")  # 예외 없이 조용히 무시

    def test_load_all_ignores_malformed_entries(self, tmp_path: Path) -> None:
        path = tmp_path / "tranche_plans.json"
        path.write_text('{"BAD": {"first_tranche_price": "100"}}', encoding="utf-8")
        repo = JsonTranchePlanRepository(path)
        assert repo.load_all() == {}
