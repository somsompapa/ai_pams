"""분할매수 계획(buy_rules.md B-2) 파일 저장소. asset_id별 1개 활성 계획만 둔다."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from pams.equity.domain.tranche_plan import ScoreItemSnapshot, ScoreSnapshot, TranchePlan


class JsonTranchePlanRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load_all(self) -> dict[str, TranchePlan]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        plans: dict[str, TranchePlan] = {}
        for asset_id, entry in raw.items():
            try:
                plans[asset_id] = _from_dict(asset_id, entry)
            except (KeyError, TypeError, ValueError):
                continue
        return plans

    def get(self, asset_id: str) -> TranchePlan | None:
        return self.load_all().get(asset_id)

    def save(self, plan: TranchePlan) -> None:
        plans = self.load_all()
        plans[plan.asset_id] = plan
        self._write(plans)

    def delete(self, asset_id: str) -> None:
        plans = self.load_all()
        plans.pop(asset_id, None)
        self._write(plans)

    def _write(self, plans: dict[str, TranchePlan]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {asset_id: _to_dict(plan) for asset_id, plan in sorted(plans.items())}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def _to_dict(plan: TranchePlan) -> dict[str, object]:
    return {
        "first_tranche_price": str(plan.first_tranche_price),
        "target_quantity": str(plan.target_quantity),
        "baseline": {
            "total_score": str(plan.baseline.total_score),
            "items": [
                {"metric": item.metric, "score": str(item.score), "missing": item.missing}
                for item in plan.baseline.items
            ],
        },
        "tranches_bought": plan.tranches_bought,
        "created_at": plan.created_at.isoformat(),
    }


def _from_dict(asset_id: str, entry: dict[str, object]) -> TranchePlan:
    baseline_raw = entry["baseline"]
    assert isinstance(baseline_raw, dict)
    items = tuple(
        ScoreItemSnapshot(
            metric=str(item["metric"]),
            score=Decimal(str(item["score"])),
            missing=bool(item["missing"]),
        )
        for item in baseline_raw["items"]
    )
    baseline = ScoreSnapshot(total_score=Decimal(str(baseline_raw["total_score"])), items=items)
    return TranchePlan(
        asset_id=asset_id,
        first_tranche_price=Decimal(str(entry["first_tranche_price"])),
        target_quantity=Decimal(str(entry["target_quantity"])),
        baseline=baseline,
        tranches_bought=int(str(entry["tranches_bought"])),
        created_at=date.fromisoformat(str(entry["created_at"])),
    )
