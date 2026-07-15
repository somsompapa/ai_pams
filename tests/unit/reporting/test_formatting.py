"""표시용 포맷팅 유틸 테스트."""

from pams.reporting.application.formatting import METRIC_LABELS, metric_description


class TestMetricDescription:
    def test_every_known_metric_has_a_description(self) -> None:
        for name in METRIC_LABELS:
            assert metric_description(name), f"{name}에 설명이 없다"

    def test_unknown_metric_returns_empty_string(self) -> None:
        assert metric_description("nope") == ""
