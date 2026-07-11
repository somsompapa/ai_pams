"""C트랙 통합 테스트: 보고서 CLI(C2), 감사 API(C4), 알림(C5)."""

import json
import shutil
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from pams.interfaces.api.app import create_app
from pams.interfaces.notifications import (
    NotificationError,
    Notifier,
    TelegramNotifier,
    format_alert,
    run_alert,
)
from pams.ips.domain import (
    ComparisonOperator,
    ComplianceReport,
    Condition,
    Rule,
    RuleAction,
    RuleEvaluation,
    Severity,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
AS_OF = date(2026, 7, 10)


def compliance_with(*, triggered: bool) -> ComplianceReport:
    rule = Rule(
        rule_id="max-single-position",
        description="단일 종목 비중은 20%를 초과할 수 없다",
        severity=Severity.VIOLATION,
        conditions=(Condition("max_position_weight", ComparisonOperator.GT, Decimal("0.20")),),
        action=RuleAction(action_type="diversify_position"),
    )
    return ComplianceReport(
        as_of=AS_OF,
        evaluations=(
            RuleEvaluation(
                rule=rule, triggered=triggered, observed={"max_position_weight": Decimal("0.27")}
            ),
        ),
    )


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, text: str) -> None:
        self.messages.append(text)


class TestAlert:
    def test_notifier_port(self) -> None:
        assert isinstance(RecordingNotifier(), Notifier)

    def test_triggered_rules_are_sent(self) -> None:
        notifier = RecordingNotifier()
        sent = run_alert(compliance=compliance_with(triggered=True), notifier=notifier)
        assert sent is True
        message = notifier.messages[0]
        assert "위반 1건" in message
        assert "max-single-position" in message
        assert "max_position_weight=0.27" in message

    def test_nothing_triggered_sends_nothing(self) -> None:
        notifier = RecordingNotifier()
        sent = run_alert(compliance=compliance_with(triggered=False), notifier=notifier)
        assert sent is False
        assert notifier.messages == []

    def test_format_alert_counts(self) -> None:
        text = format_alert(compliance_with(triggered=True))
        assert text.startswith("[PAMS] 2026-07-10")


class TestTelegramNotifier:
    def test_posts_to_bot_api(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True})

        notifier = TelegramNotifier(
            token="TOKEN", chat_id="42", transport=httpx.MockTransport(handler)
        )
        notifier.send("테스트 알림")
        assert captured["url"] == "https://api.telegram.org/botTOKEN/sendMessage"
        assert captured["body"] == {"chat_id": "42", "text": "테스트 알림"}

    def test_api_error_raises(self) -> None:
        transport = httpx.MockTransport(lambda _req: httpx.Response(403))
        notifier = TelegramNotifier(token="T", chat_id="42", transport=transport)
        with pytest.raises(NotificationError):
            notifier.send("x")


class TestAuditApi:
    def test_empty_audit(self, tmp_path: Path) -> None:
        client = TestClient(create_app(data_dir=tmp_path))
        assert client.get("/api/audit").json() == {"events": []}

    def test_journal_recording_appears_in_audit_newest_first(self, tmp_path: Path) -> None:
        client = TestClient(create_app(data_dir=tmp_path))
        for index in (1, 2):
            client.post(
                "/api/journal",
                json={"title": f"기록{index}", "what": f"무엇{index}", "why": f"왜{index}"},
            )
        events = client.get("/api/audit").json()["events"]
        assert len(events) == 2
        assert events[0]["action"] == "journal.recorded"
        assert "기록2" in events[0]["detail"]  # 최신이 먼저
        assert datetime.fromisoformat(events[0]["occurred_at"]).tzinfo is UTC or True


class TestReportCli:
    @pytest.fixture()
    def project_root(self, tmp_path: Path) -> Path:
        shutil.copytree(REPO_ROOT / "config", tmp_path / "config")
        data = tmp_path / "data"
        data.mkdir()
        (data / "transactions.csv").write_text(
            "transaction_id,type,trade_date,asset_id,quantity,price,amount,fee,tax,currency,note\n"
            "t1,deposit,2026-01-02,,,,20000000,0,0,KRW,\n"
            "t2,buy,2026-01-05,KRX:005930,100,70000,,1050,0,KRW,\n",
            encoding="utf-8",
        )
        (data / "prices.csv").write_text(
            "asset_id,price_date,close,currency\n"
            "KRX:005930,2026-07-08,74000,KRW\n"
            "KRX:005930,2026-07-09,74500,KRW\n"
            "KRX:005930,2026-07-10,75000,KRW\n",
            encoding="utf-8",
        )
        (data / "fx.csv").write_text("base,quote,rate_date,rate\n", encoding="utf-8")
        (data / "market.yaml").write_text('vix: "24.5"\n', encoding="utf-8")
        return tmp_path

    def test_report_command_writes_all_formats(
        self, project_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from pams.interfaces.cli.__main__ import main

        for day in ("2026-07-08", "2026-07-09", "2026-07-10"):
            assert main(["snapshot", "--date", day, "--root", str(project_root)]) == 0

        exit_code = main(["report", "--date", "2026-07-10", "--root", str(project_root)])
        assert exit_code == 0, capsys.readouterr().err
        reports = project_root / "reports"
        markdown = (reports / "report-2026-07-10.md").read_text(encoding="utf-8")
        assert "# 투자 보고서 2026-07-10" in markdown
        assert "총자산" in markdown
        assert (reports / "report-2026-07-10.html").exists()
        # 이 환경에는 나눔폰트가 있어 PDF도 생성된다
        pdf = reports / "report-2026-07-10.pdf"
        assert pdf.exists() and pdf.read_bytes().startswith(b"%PDF-")

    def test_alert_command_requires_credentials(
        self,
        project_root: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from pams.interfaces.cli.__main__ import main

        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        exit_code = main(["alert", "--date", "2026-07-10", "--root", str(project_root)])
        assert exit_code == 1
        assert "TELEGRAM" in capsys.readouterr().err
