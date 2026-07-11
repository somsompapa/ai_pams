"""규칙 발동 알림.

Rule Engine의 판정(ComplianceReport)을 사람이 받아볼 채널로 전달한다.
알림 채널은 Notifier 포트로 추상화되어 텔레그램 외의 채널(이메일 등)도
어댑터 추가만으로 지원된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from pams.ips.domain import ComplianceReport


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
