"""자산 분류 체계."""

from enum import StrEnum, unique


@unique
class AssetClass(StrEnum):
    """지원 자산군. 새 자산군(예: 원자재)이 필요하면 멤버만 추가하면 된다."""

    DOMESTIC_STOCK = "domestic_stock"  # 국내주식
    US_STOCK = "us_stock"  # 미국주식
    ETF = "etf"
    BOND = "bond"  # 채권
    CASH = "cash"  # 현금
    DEPOSIT = "deposit"  # 예수금
    FOREIGN_CURRENCY = "foreign_currency"  # 외화
    GOLD = "gold"  # 금
    PENSION = "pension"  # 연금
    CRYPTO = "crypto"  # 가상자산

    @property
    def is_cash_like(self) -> bool:
        """IPS의 '현금 최소 비중' 규칙이 적용되는 현금성 자산 여부."""
        return self in _CASH_LIKE


_CASH_LIKE = frozenset({AssetClass.CASH, AssetClass.DEPOSIT, AssetClass.FOREIGN_CURRENCY})
