"""표시용 포맷팅 유틸 테스트."""

from decimal import Decimal

from pams.reporting.application.formatting import METRIC_LABELS, format_money, metric_description
from pams.shared_kernel.domain import Currency, Money


class TestMetricDescription:
    def test_every_known_metric_has_a_description(self) -> None:
        for name in METRIC_LABELS:
            assert metric_description(name), f"{name}에 설명이 없다"

    def test_unknown_metric_returns_empty_string(self) -> None:
        assert metric_description("nope") == ""


class TestFormatMoney:
    """소수점 통화(USD 등)를 정수로 반올림해 표시하던 버그 재발 방지.

    KRW/JPY처럼 최소단위가 정수인 통화만 소수점 없이 보여주고,
    나머지 통화는 센트 단위(소수 둘째 자리)까지 보여준다.
    """

    def test_krw_has_no_decimal_places(self) -> None:
        assert format_money(Money(Decimal("123456.789"), Currency.KRW)) == "123,457 KRW"

    def test_jpy_has_no_decimal_places(self) -> None:
        assert format_money(Money(Decimal("1000.5"), Currency.JPY)) == "1,001 JPY"

    def test_usd_keeps_two_decimal_places(self) -> None:
        assert format_money(Money(Decimal("656.265"), Currency.USD)) == "656.27 USD"

    def test_eur_keeps_two_decimal_places_even_when_whole(self) -> None:
        assert format_money(Money(Decimal("10"), Currency.EUR)) == "10.00 EUR"
