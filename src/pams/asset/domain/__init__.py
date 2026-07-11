"""asset.domain 공개 API.

Asset/AssetClass는 여러 컨텍스트(portfolio, ips, rebalancing, reporting)가
공유하는 마스터 데이터 어휘이므로 shared_kernel에 있고, 여기서 re-export한다.
이 컨텍스트는 이후 자산 카탈로그 관리(등록/조회 유스케이스)를 담당한다.
"""

from pams.shared_kernel.domain import Asset, AssetClass

__all__ = ["Asset", "AssetClass"]
