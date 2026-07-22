"""토스증권 Open API 어댑터 (HoldingsProvider 구현).

OAuth2 Client Credentials로 인증하고 계좌의 보유 종목(수량·평단가·현재가)을
조회한다. 이 값은 대시보드 표시를 보강하는 참고자료일 뿐, 거래이력(원장) 기반
포트폴리오 계산(BuildPortfolioSnapshot)이나 세금/실현손익 계산에는 쓰이지 않는다.

주의: 여기서는 조회(GET /api/v1/holdings)만 다룬다 - 주문 연동은 범위 밖이다
(CLAUDE.md 절대원칙: "자동매매는 목표가 아니다").
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

from pams.portfolio.domain.broker_holding import BrokerHolding, BrokerProviderError
from pams.shared_kernel.domain import Currency

_REAL_BASE_URL = "https://openapi.tossinvest.com"
_TOKEN_PATH = "/oauth2/token"
_ACCOUNTS_PATH = "/api/v1/accounts"
_HOLDINGS_PATH = "/api/v1/holdings"
_ACCOUNT_HEADER = "X-Tossinvest-Account"

_TOKEN_EXPIRY_SAFETY_MARGIN = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class TossHoldingsProvider:
    client_id: str
    client_secret: str
    base_url: str = _REAL_BASE_URL
    timeout_seconds: float = 15.0
    transport: httpx.BaseTransport | None = None  # 테스트 주입용
    token_cache_path: Path | None = None  # None이면 매 호출마다 새 토큰 발급
    account_cache_path: Path | None = None  # None이면 매 호출마다 계좌 목록 재조회
    min_request_interval_seconds: float = 0.2  # 토스 초당 요청 제한 회피용 최소 간격
    _last_request_at: list[float] = field(default_factory=lambda: [0.0], compare=False)

    def holdings(self) -> list[BrokerHolding]:
        token = self._access_token()
        account_seq = self._account_seq(token)
        body = self._get(_HOLDINGS_PATH, token=token, account_seq=account_seq)
        result = body.get("result")
        if not isinstance(result, dict):
            raise BrokerProviderError("holdings 응답에 result가 없다")
        items = result.get("items")
        if not isinstance(items, list):
            raise BrokerProviderError("holdings 응답에 items가 없다")
        return [self._to_holding(item) for item in items]

    def _to_holding(self, item: dict[str, Any]) -> BrokerHolding:
        try:
            return BrokerHolding(
                symbol=str(item["symbol"]),
                quantity=Decimal(str(item["quantity"])),
                avg_price=Decimal(str(item["averagePurchasePrice"])),
                current_price=Decimal(str(item["lastPrice"])),
                currency=Currency(str(item["currency"])),
            )
        except (KeyError, InvalidOperation, ValueError) as error:
            raise BrokerProviderError(f"holdings 항목 파싱 실패: {item!r}") from error

    def _account_seq(self, token: str) -> int:
        cached = self._read_cached_account_seq()
        if cached is not None:
            return cached
        body = self._get(_ACCOUNTS_PATH, token=token, account_seq=None)
        accounts = body.get("result")
        if not isinstance(accounts, list) or not accounts:
            raise BrokerProviderError("연결된 계좌가 없다 (GET /api/v1/accounts 응답이 비어있다)")
        seq = accounts[0].get("accountSeq")
        if not isinstance(seq, int):
            raise BrokerProviderError("계좌 응답에 accountSeq가 없다")
        self._write_cached_account_seq(seq)
        return seq

    def _read_cached_account_seq(self) -> int | None:
        if self.account_cache_path is None or not self.account_cache_path.exists():
            return None
        try:
            document = json.loads(self.account_cache_path.read_text(encoding="utf-8"))
            return int(document["account_seq"])
        except (OSError, ValueError, KeyError):
            return None

    def _write_cached_account_seq(self, seq: int) -> None:
        if self.account_cache_path is None:
            return
        self.account_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.account_cache_path.write_text(json.dumps({"account_seq": seq}), encoding="utf-8")

    def _get(self, path: str, *, token: str, account_seq: int | None) -> dict[str, Any]:
        headers = {"authorization": f"Bearer {token}"}
        if account_seq is not None:
            headers[_ACCOUNT_HEADER] = str(account_seq)
        try:
            self._throttle()
            with self._client() as client:
                response = client.get(path, headers=headers)
        except httpx.HTTPError as error:
            raise BrokerProviderError(f"{path}: 요청 실패: {error}") from error

        if response.status_code >= 400:
            raise BrokerProviderError(f"{path}: HTTP {response.status_code}: {response.text[:200]}")
        try:
            document: dict[str, Any] = response.json()
        except ValueError as error:
            raise BrokerProviderError(f"{path}: 예상 밖 응답 형식") from error
        return document

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url, transport=self.transport, timeout=self.timeout_seconds
        )

    def _throttle(self) -> None:
        if self.min_request_interval_seconds <= 0:
            return
        wait = self.min_request_interval_seconds - (time.monotonic() - self._last_request_at[0])
        if wait > 0:
            time.sleep(wait)
        self._last_request_at[0] = time.monotonic()

    def _access_token(self) -> str:
        cached = self._read_cached_token()
        if cached is not None:
            return cached
        token, expires_in = self._request_token()
        self._write_cached_token(token, expires_in)
        return token

    def _read_cached_token(self) -> str | None:
        if self.token_cache_path is None or not self.token_cache_path.exists():
            return None
        try:
            document = json.loads(self.token_cache_path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(document["expires_at"])
            if expires_at - _TOKEN_EXPIRY_SAFETY_MARGIN <= datetime.now(UTC):
                return None
            return str(document["access_token"])
        except (OSError, ValueError, KeyError):
            return None

    def _write_cached_token(self, token: str, expires_in: int) -> None:
        if self.token_cache_path is None:
            return
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        self.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_cache_path.write_text(
            json.dumps({"access_token": token, "expires_at": expires_at.isoformat()}),
            encoding="utf-8",
        )

    def _request_token(self) -> tuple[str, int]:
        try:
            self._throttle()
            with self._client() as client:
                response = client.post(
                    _TOKEN_PATH,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                )
        except httpx.HTTPError as error:
            raise BrokerProviderError(f"토큰 발급 요청 실패: {error}") from error

        if response.status_code >= 400:
            raise BrokerProviderError(
                f"토큰 발급 실패: HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            body = response.json()
            return str(body["access_token"]), int(body.get("expires_in", 86400))
        except (ValueError, KeyError, TypeError) as error:
            raise BrokerProviderError("토큰 발급 응답 형식이 예상과 다르다") from error
