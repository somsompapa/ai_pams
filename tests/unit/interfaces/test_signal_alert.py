"""오늘의 액션 알림(중복 방지 포함) 로직 테스트."""

from pathlib import Path

from pams.interfaces.notifications import (
    Notifier,
    SignalStateStore,
    active_persistent_keys,
    format_signal_alert,
    run_signal_alert,
    select_new_signals,
)


def action(source: str, asset_id: str, direction: str, **extra: str) -> dict:
    base = {
        "source": source,
        "source_label": source,
        "asset_id": asset_id,
        "asset": asset_id,
        "direction": direction,
        "direction_label": "매수" if direction == "buy" else "매도",
        "reason": "사유",
        "guide": "",
    }
    base.update(extra)
    return base


class Collector(Notifier):
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)


class TestSelectNewSignals:
    def test_dca_always_included(self) -> None:
        actions = [action("dca", "NASDAQ:AAPL", "buy")]
        assert select_new_signals(actions, previous_keys=set()) == actions
        # 이전에 있었어도 DCA는 매일 포함
        prev = active_persistent_keys(actions)  # DCA는 persistent 아님 → 빈 집합
        assert prev == set()

    def test_persistent_signal_only_when_new(self) -> None:
        actions = [action("price_trigger", "KRX:005930", "buy")]
        first = select_new_signals(actions, previous_keys=set())
        assert len(first) == 1  # 처음엔 새 신호
        prev = active_persistent_keys(actions)
        second = select_new_signals(actions, previous_keys=prev)
        assert second == []  # 이미 알린 신호는 반복 안 함

    def test_cleared_then_refires_alerts_again(self) -> None:
        fired = [action("price_trigger", "KRX:005930", "buy")]
        # 신호가 사라진 날: actions 비어 있음 → 저장될 키도 비어 있음
        assert active_persistent_keys([]) == set()
        # 다시 발동하면(이전 키가 비어 있으니) 새 신호로 취급
        assert len(select_new_signals(fired, previous_keys=set())) == 1


class TestRunSignalAlert:
    def test_sends_and_persists(self, tmp_path: Path) -> None:
        store = SignalStateStore(tmp_path / "state.json")
        notifier = Collector()
        actions = [
            action("price_trigger", "KRX:005930", "buy"),
            action("dca", "NASDAQ:AAPL", "buy"),
        ]
        sent = run_signal_alert(as_of="2026-07-13", actions=actions, store=store, notifier=notifier)
        assert sent is True
        assert len(notifier.sent) == 1
        # 두 번째 실행: 트리거는 이미 알림, DCA만 남음 → 여전히 전송(DCA는 매일)
        notifier2 = Collector()
        sent2 = run_signal_alert(
            as_of="2026-07-14", actions=actions, store=store, notifier=notifier2
        )
        assert sent2 is True
        assert "NASDAQ:AAPL" in notifier2.sent[0]
        assert "KRX:005930" not in notifier2.sent[0]  # 트리거는 반복 안 됨

    def test_no_actions_sends_nothing(self, tmp_path: Path) -> None:
        store = SignalStateStore(tmp_path / "state.json")
        notifier = Collector()
        assert (
            run_signal_alert(as_of="2026-07-18", actions=[], store=store, notifier=notifier)
            is False
        )
        assert notifier.sent == []

    def test_only_repeated_persistent_sends_nothing(self, tmp_path: Path) -> None:
        store = SignalStateStore(tmp_path / "state.json")
        actions = [action("rebalancing", "us_stock", "sell")]
        run_signal_alert(as_of="d1", actions=actions, store=store, notifier=Collector())
        n = Collector()
        assert run_signal_alert(as_of="d2", actions=actions, store=store, notifier=n) is False
        assert n.sent == []


class TestFormat:
    def test_message_lists_actions(self) -> None:
        text = format_signal_alert(
            "2026-07-13",
            [
                action(
                    "price_trigger",
                    "삼성전자",
                    "buy",
                    guide="",
                    reason="현재가 68,000 ≤ 매수선 70,000",
                )
            ],
        )
        assert "오늘의 액션" in text
        assert "삼성전자" in text
        assert "매수" in text
