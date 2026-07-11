# ADR 0001: 아키텍처 및 모듈 구조 선택

- 상태: 채택됨
- 일자: 2026-07-11

## 배경

PAMS는 수년간 운영 가능해야 하는 개인 자산운용 엔진이며, IPS→Rule→Data→계산→결과의
파이프라인을 절대 AI의 감(직관)이 아닌 규칙과 계산으로 수행해야 한다는 강한 제약을 가진다.
또한 자산관리/포트폴리오/리스크/리밸런싱/투자일지/성과분석/보고서라는 다수의 독립적 기능
영역을 장기간에 걸쳐 단계적으로(Phase 1~10) 구축한다.

## 결정

1. **DDD 바운디드 컨텍스트**를 최상위 모듈 경계로 사용한다 (`asset`, `ips`, `portfolio`,
   `risk`, `rebalancing`, `performance`, `market_data`, `reporting`, `journal`,
   `ai_analysis`, `audit`).
2. 각 컨텍스트 내부는 **Clean Architecture 3계층**(domain → application → infrastructure)으로
   구성하고, 의존성은 항상 domain 방향으로만 향하게 한다(SOLID의 DIP).
3. 자산 종류, 값객체 등 여러 컨텍스트가 공유해야 하는 개념은 `shared_kernel`(domain만 존재)에 둔다.
4. 투자 판단에 영향을 주는 모든 규칙(IPS, Rule)은 코드가 아닌 `config/`의 YAML로 관리한다.
5. 사용자 진입점(CLI, REST API)은 `interfaces/`에 격리하고, 웹 대시보드(Phase 9)는
   요구사항이 확정되는 시점에 별도로 설계한다(지금 만들면 미완성 껍데기만 생성되어 YAGNI 위반).

## 근거

- 모듈 기반 개발과 확장성을 동시에 만족하려면 컨텍스트 경계가 코드 레벨에서 강제되어야 한다.
- domain/application이 외부 의존성 없이 순수하게 유지되어야 "모든 로직은 Unit Test 가능해야 한다"는
  원칙을 지킬 수 있다.
- 데이터 공급자(시세, 환율, 금리 등)는 향후 반드시 교체/추가될 것이므로 포트-어댑터 패턴이 필수적이다.

## 대안 검토

- **단일 계층(레이어드) 아키텍처**: 초기 구현은 빠르지만 컨텍스트 간 결합이 빠르게 심화되어
  기각. Phase가 늘어날수록(10단계) 유지보수 비용이 기하급수적으로 증가할 위험.
- **마이크로서비스**: 개인용 시스템 규모에 비해 운영 복잡도가 과도하여 기각. 필요 시
  현재의 모듈 경계를 그대로 서비스 경계로 승격할 수 있도록 설계했다.

## 결과

Phase 1에서 `src/pams/<context>/{domain,application,infrastructure}` 골격과
`config/`, `docs/`, `tests/{unit,integration,e2e}` 구조를 생성한다.
