"""config/triggers/*.yaml → PriceTriggerPlan 로더."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pams.equity.domain import PriceTrigger, PriceTriggerPlan
from pams.shared_kernel.domain import Currency, DomainError, Money

_TRIGGER_HEADER = (
    "# 종목별 절대가격 매수/매도 트리거 (대시보드에서 관리됨)\n"
    "# 현재가가 buy_at 이하면 매수, sell_at 이상이면 매도 신호가 '오늘의 액션'에 뜬다.\n"
)


class PriceTriggerConfigError(Exception):
    """가격 트리거 설정 파일을 PriceTriggerPlan으로 변환하는 데 실패했다."""


def save_price_trigger(path: Path, trigger: PriceTrigger) -> None:
    """가격 트리거 한 건을 upsert 한다(같은 asset_id는 교체). 파일이 없으면 만든다.

    도메인 PriceTrigger로 이미 검증된 값만 받으므로 여기서는 직렬화만 한다.
    숫자는 문자열로 저장해 float 오차를 만들지 않는다.
    """
    entries: list[dict[str, str]] = []
    if path.exists():
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = document.get("triggers", []) if isinstance(document, dict) else []
        entries = [e for e in raw if isinstance(e, dict) and e.get("asset_id") != trigger.asset_id]

    entry: dict[str, str] = {"asset_id": trigger.asset_id, "currency": str(trigger.currency)}
    if trigger.buy_at is not None:
        entry["buy_at"] = str(trigger.buy_at.amount)
    if trigger.take_profit_at is not None:
        entry["take_profit_at"] = str(trigger.take_profit_at.amount)
    if trigger.stop_loss_at is not None:
        entry["stop_loss_at"] = str(trigger.stop_loss_at.amount)
    entries.append(entry)

    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        {"triggers": entries}, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    path.write_text(_TRIGGER_HEADER + body, encoding="utf-8")


class YamlPriceTriggerLoader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> PriceTriggerPlan:
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise PriceTriggerConfigError(f"설정 파일을 읽을 수 없다: {self._path}") from error
        except yaml.YAMLError as error:
            raise PriceTriggerConfigError(f"YAML 문법 오류: {self._path}: {error}") from error
        if not isinstance(document, dict):
            raise PriceTriggerConfigError(f"{self._path}: 최상위는 매핑이어야 한다")

        raw = document.get("triggers", [])
        if not isinstance(raw, list) or not raw:
            raise PriceTriggerConfigError(f"{self._path}: triggers 목록이 비어 있다")

        try:
            triggers = tuple(
                self._trigger(entry, f"{self._path}.triggers[{index}]")
                for index, entry in enumerate(raw)
            )
            return PriceTriggerPlan(triggers=triggers)
        except DomainError as error:
            raise PriceTriggerConfigError(f"{self._path}: 잘못된 트리거: {error}") from error

    def _trigger(self, entry: Any, where: str) -> PriceTrigger:
        if not isinstance(entry, dict):
            raise PriceTriggerConfigError(f"{where}: 매핑이어야 한다")
        asset_id = str(entry.get("asset_id") or "").strip()
        if not asset_id:
            raise PriceTriggerConfigError(f"{where}: asset_id가 필요하다")
        currency_raw = entry.get("currency")
        if currency_raw is None:
            raise PriceTriggerConfigError(f"{where}: currency가 필요하다")
        try:
            currency = Currency(str(currency_raw))
        except ValueError:
            raise PriceTriggerConfigError(f"{where}: 알 수 없는 통화 {currency_raw!r}") from None

        def money(field: str) -> Money | None:
            value = entry.get(field)
            return Money.of(str(value), currency) if value is not None else None

        # sell_at은 구버전 별칭 → 익절선(take_profit_at)
        take_profit = money("take_profit_at")
        if take_profit is None:
            take_profit = money("sell_at")
        return PriceTrigger(
            asset_id=asset_id,
            buy_at=money("buy_at"),
            take_profit_at=take_profit,
            stop_loss_at=money("stop_loss_at"),
        )
