"""규칙 발동 알림.

Rule Engine의 판정(ComplianceReport)을 사람이 받아볼 채널로 전달한다.
알림 채널은 Notifier 포트로 추상화되어 텔레그램 외의 채널(이메일 등)도
어댑터 추가만으로 지원된다.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

from pams.ips.domain import ComplianceReport

# 가격 트리거·리밸런싱은 조건이 유지되는 동안 계속 '발동' 상태다.
# 매일 반복 알림하지 않도록, 이 신호원들은 '이전에 없던 것'만 새로 알린다.
# (다른 신호원이 추가되면 매일 반복 알림이 필요한지 여기서 판단한다.)
_PERSISTENT_SOURCES = frozenset({"price_trigger", "rebalancing"})


@runtime_checkable
class Notifier(Protocol):
    def send(self, text: str) -> None: ...


class NotificationError(Exception):
    """알림 전송에 실패했다."""


def format_alert(compliance: ComplianceReport) -> str:
    """발동 규칙을 사람이 읽을 알림 텍스트로 만든다."""
    lines = [
        f"[PAMS] {compliance.as_of.isoformat()} 규칙 알림",
        f"위반 {len(compliance.violations)}건 / 주의 {len(compliance.warnings)}건",
    ]
    for evaluation in (*compliance.violations, *compliance.warnings):
        severity = "위반" if evaluation in compliance.violations else "주의"
        observed = ", ".join(f"{name}={value}" for name, value in evaluation.observed.items())
        lines.append(
            f"- [{severity}] {evaluation.rule.rule_id}: {evaluation.rule.description} ({observed})"
        )
    return "\n".join(lines)


def run_alert(*, compliance: ComplianceReport, notifier: Notifier) -> bool:
    """발동한 규칙이 있으면 알림을 보낸다. 보냈으면 True."""
    if not compliance.violations and not compliance.warnings:
        return False
    notifier.send(format_alert(compliance))
    return True


def _action_key(action: dict[str, Any]) -> str:
    return f"{action['source']}:{action['asset_id']}:{action['direction']}"


def select_new_signals(
    actions: Sequence[dict[str, Any]], previous_keys: set[str]
) -> list[dict[str, Any]]:
    """알릴 신호를 고른다. persistent(트리거·리밸런싱)는 이전에 없던 것만,
    나머지(DCA)는 매일 포함한다.
    """
    selected = []
    for action in actions:
        if action["source"] in _PERSISTENT_SOURCES:
            if _action_key(action) not in previous_keys:
                selected.append(action)
        else:
            selected.append(action)
    return selected


def active_persistent_keys(actions: Sequence[dict[str, Any]]) -> set[str]:
    """현재 발동 중인 persistent 신호 키(다음 실행의 중복 판단 기준)."""
    return {_action_key(a) for a in actions if a["source"] in _PERSISTENT_SOURCES}


def format_signal_alert(as_of: str, actions: Sequence[dict[str, Any]]) -> str:
    lines = [f"[PAMS] {as_of} 오늘의 액션 — 언제 사고/팔지"]
    for action in actions:
        guide = f" ({action['guide']})" if action.get("guide") else ""
        lines.append(
            f"- [{action['source_label']}] {action['direction_label']} "
            f"{action['asset']}: {action['reason']}{guide}"
        )
    lines.append("\n※ 신호는 계산 결과다. 실제 매매는 직접 결정한다.")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class SignalStateStore:
    """마지막으로 알린 persistent 신호 상태를 파일에 보관한다(중복 알림 방지)."""

    path: Path

    def load(self) -> set[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        return set(data) if isinstance(data, list) else set()

    def save(self, keys: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(sorted(keys), ensure_ascii=False), encoding="utf-8")


def run_signal_alert(
    *,
    as_of: str,
    actions: Sequence[dict[str, Any]],
    store: SignalStateStore,
    notifier: Notifier,
) -> bool:
    """오늘의 액션 중 알릴 것을 골라 전송한다. 보냈으면 True.

    persistent 신호는 새로 발동한 것만, DCA는 매일 알린다. 발동 상태는
    store에 저장해 다음 실행에서 같은 신호를 반복 알리지 않는다.
    """
    to_send = select_new_signals(actions, store.load())
    store.save(active_persistent_keys(actions))
    if not to_send:
        return False
    notifier.send(format_signal_alert(as_of, to_send))
    return True


@dataclass(frozen=True, slots=True)
class TelegramNotifier:
    """텔레그램 봇 알림. 봇 생성: @BotFather, chat_id 확인: @userinfobot."""

    token: str
    chat_id: str
    timeout_seconds: float = 15.0
    transport: httpx.BaseTransport | None = None  # 테스트 주입용

    def send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = client.post(url, json={"chat_id": self.chat_id, "text": text})
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise NotificationError(f"텔레그램 전송 실패: {error}") from error
