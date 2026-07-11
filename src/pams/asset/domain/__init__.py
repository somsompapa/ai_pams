"""asset.domain 공개 API.

AssetClass는 여러 컨텍스트(ips, portfolio, rebalancing)가 공유하는 어휘이므로
shared_kernel로 이동했고, 여기서는 호환을 위해 re-export한다.
"""

from pams.asset.domain.asset import Asset
from pams.shared_kernel.domain import AssetClass

__all__ = ["Asset", "AssetClass"]
