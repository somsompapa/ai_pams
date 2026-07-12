"""도메인 공통 예외 계층.

모든 도메인 예외는 DomainError를 상속하여, 진입점(interfaces)에서
도메인 오류와 시스템 오류를 구분해 처리할 수 있게 한다.
"""


class DomainError(Exception):
    """도메인 규칙 위반의 최상위 예외."""


class DomainValidationError(DomainError):
    """값객체/엔티티 생성 시 불변식(invariant) 위반."""


class CurrencyMismatchError(DomainError):
    """서로 다른 통화 간의 직접 연산 시도. 변환은 반드시 ExchangeRate를 거쳐야 한다."""
