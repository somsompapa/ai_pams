# ADR 0002: 도메인 모델은 표준 라이브러리 dataclass로 구현

- 상태: 채택됨
- 일자: 2026-07-11

## 배경

Phase 2에서 도메인 모델(Money, Percentage, Asset, Transaction 등)을 구현하면서
pydantic 사용 여부를 결정해야 했다. pydantic은 편리하지만, ADR 0001과 CLAUDE.md의
"domain/application 계층은 외부 라이브러리에 의존하지 않는다" 원칙과 충돌한다.

## 결정

1. **domain 계층의 모든 값객체/엔티티는 표준 라이브러리 `dataclass(frozen=True, slots=True)`
   + `__post_init__` 자체 검증**으로 구현한다.
2. pydantic은 **경계(boundary)에서만** 사용한다: 설정 파일(YAML) 파싱(Phase 3),
   REST API 요청/응답 스키마(Phase 9) 등 infrastructure/interfaces 계층.
3. 금액·수량·비율에는 float를 절대 사용하지 않는다. 모든 수치 값객체는 `Decimal` 기반이며
   float 입력은 생성 시점에 `DomainValidationError`로 거부한다.

## 근거

- 도메인 순수성: 도메인이 pydantic 버전 업그레이드(v1→v2 같은 대규모 변경)에 흔들리지 않는다.
- 불변식 표현력: `Money + Money`의 통화 검증, `Quantity` 차감 하한 등 도메인 규칙은
  검증 라이브러리가 아닌 도메인 코드 자체에 있어야 한다.
- float 금지: pydantic은 기본적으로 float→Decimal 강제 변환을 허용하는 반면,
  자체 검증은 float 유입을 원천 차단할 수 있다 (0.1+0.2≠0.3 오차가 자산 계산에 누적되는 것을 방지).

## 결과

- `shared_kernel.domain`: `Money`, `Percentage`, `Quantity`, `Currency`, 공통 예외
- `asset.domain`: `Asset`, `AssetClass`(10개 자산군, `is_cash_like` 분류)
- `portfolio.domain`: `Transaction`, `TransactionType`(트레이드/현금성 이원 검증, `signed_cash_flow`)
- `market_data.domain`: `PricePoint`, `ExchangeRate`, 공급자 포트(`PriceProvider`, `ExchangeRateProvider`)
