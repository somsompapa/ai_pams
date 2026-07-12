"""통화 코드 (ISO 4217)."""

from enum import StrEnum, unique


@unique
class Currency(StrEnum):
    """시스템이 지원하는 통화. 새 통화가 필요하면 멤버만 추가하면 된다."""

    KRW = "KRW"
    USD = "USD"
    JPY = "JPY"
    EUR = "EUR"
    CNY = "CNY"
    GBP = "GBP"
    HKD = "HKD"
    CHF = "CHF"
