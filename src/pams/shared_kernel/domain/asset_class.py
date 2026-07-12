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
    SAVINGS = "savings"  # 청약·적립식 저축 (중도해지 페널티로 사실상 묶인 저축)
    CRYPTO = "crypto"  # 가상자산

    @property
    def is_cash_like(self) -> bool:
        """IPS의 '현금 최소 비중' 규칙이 적용되는 현금성 자산 여부."""
        return self in _CASH_LIKE

    @property
    def is_equity_like(self) -> bool:
        """IPS의 '최대 주식비중' 규칙(equity_weight 지표)이 적용되는 주식성 자산 여부."""
        return self in _EQUITY_LIKE

    @property
    def is_diversification_exempt(self) -> bool:
        """단일종목 집중도(max_position_weight) 지표에서 제외되는 자산군.

        현금성 자산은 시장위험이 없고, 연금은 계좌 하나로 등록해도 내부에
        여러 상품이 섞여 있어 '한 종목 쏠림'과 무관하다.
        """
        return self in _DIVERSIFICATION_EXEMPT


_CASH_LIKE = frozenset({AssetClass.CASH, AssetClass.DEPOSIT, AssetClass.FOREIGN_CURRENCY})
_EQUITY_LIKE = frozenset({AssetClass.DOMESTIC_STOCK, AssetClass.US_STOCK, AssetClass.ETF})
_DIVERSIFICATION_EXEMPT = _CASH_LIKE | frozenset({AssetClass.PENSION, AssetClass.SAVINGS})
