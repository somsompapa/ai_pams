"""Asset 엔티티: 시스템이 다루는 모든 자산의 표준 모델."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pams.asset.domain.asset_class import AssetClass
from pams.shared_kernel.domain import Currency, DomainValidationError

_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")


@dataclass(frozen=True, slots=True)
class Asset:
    """자산 마스터 정보.

    asset_id는 "<시장|유형>:<심볼>" 관례를 따른다.
    예: "KRX:005930", "NASDAQ:AAPL", "CASH:KRW", "GOLD:XAU"
    """

    asset_id: str
    name: str
    asset_class: AssetClass
    currency: Currency
    country: str  # ISO 3166-1 alpha-2 (예: KR, US)
    sector: str | None = None  # 현금/금 등 섹터가 없는 자산은 None

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise DomainValidationError("asset_id는 비어 있을 수 없다")
        if not self.name.strip():
            raise DomainValidationError("자산 이름은 비어 있을 수 없다")
        if not _COUNTRY_CODE.match(self.country):
            raise DomainValidationError(
                f"국가 코드는 ISO 3166-1 alpha-2 형식이어야 한다 (예: KR, US): {self.country!r}"
            )

    @property
    def is_cash_like(self) -> bool:
        return self.asset_class.is_cash_like
