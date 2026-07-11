# PAMS 아키텍처

## 1. 목표

PAMS(Personal Asset Management System)는 투자 판단을 대신하는 AI가 아니라
**투자헌장(IPS)을 엄격하게 실행하는 자산운용 엔진**이다.

모든 의사결정은 다음 순서로만 이루어진다.

```
IPS → Rule → Data → 계산 → 결과
```

AI(Claude)는 이 파이프라인의 산출물을 사람이 이해하기 쉽게 설명/요약/보고서화하는 역할만 담당하며,
비중 조정이나 매매 여부를 스스로 판단하지 않는다.

## 2. 레이어: Clean Architecture

각 바운디드 컨텍스트(아래 3절)는 내부적으로 3개 계층을 가진다. 의존성은 항상 안쪽(domain)을 향한다.

```
infrastructure  ──depends on──▶  application  ──depends on──▶  domain
     (구현)                        (유스케이스)                  (규칙/모델, 순수)
```

- **domain**: 엔티티, 값객체, 도메인 규칙, 그리고 외부 의존을 위한 포트(인터페이스, 예: `MarketDataProvider` 프로토콜). 외부 라이브러리·DB·네트워크에 의존하지 않는다 → 어떤 프레임워크 없이도 Unit Test 가능.
- **application**: 유스케이스(예: "리밸런싱 제안 생성"). domain의 포트를 호출하지만 구체적인 구현은 모른다(DIP).
- **infrastructure**: domain이 정의한 포트의 실제 구현체(예: 특정 증권사 API, yfinance, 파일 기반 리포지토리). 언제든 교체 가능해야 한다.

`interfaces/`(cli, api)는 이 컨텍스트들을 조합해 사용자에게 노출하는 최외곽 진입점이다.

## 3. 모듈: DDD 바운디드 컨텍스트

`src/pams/` 아래 각 폴더는 하나의 책임만 갖는 독립 모듈이다.

| 모듈 | 책임 | 관련 Phase |
|---|---|---|
| `shared_kernel` | 모든 컨텍스트가 공유하는 값객체(Money, Currency, Percentage 등), 공통 예외 | 전체 |
| `asset` | 자산 종류(국내주식/미국주식/ETF/채권/현금/예수금/외화/금/연금/가상자산)의 표준 모델 | Phase 2 |
| `ips` | 투자헌장 + Rule Engine | Phase 3 |
| `portfolio` | 총자산/손익/비중 계산 | Phase 4 |
| `risk` | MDD/Sharpe/VaR 등 위험지표 | Phase 5 |
| `rebalancing` | 목표비중 대비 매수/매도 제안 | Phase 6 |
| `performance` | 기간별 성과/벤치마크 비교 | Phase 7 |
| `market_data` | 시세/환율/금리/지수/경제지표/뉴스 공급자 추상화 | Phase 2~ |
| `reporting` | Markdown/HTML/PDF 리포트 생성 | Phase 8 |
| `journal` | 투자일지 | Phase 8~10 |
| `ai_analysis` | Claude 기반 설명/요약(계산 없음) | Phase 10 |
| `audit` | 모든 행동의 주체/시각/내용/사유 기록 | 전체 |
| `interfaces` | CLI, REST API 진입점 (웹 대시보드는 Phase 9에서 별도 설계) | Phase 9 |

컨텍스트 간 통신은 원칙적으로 `application` 계층의 유스케이스 호출로만 이루어지며,
서로의 `domain`/`infrastructure` 내부를 직접 참조하지 않는다(모듈 경계 보호).

## 4. 왜 이 구조인가

- **DDD**: "포트폴리오 계산"과 "리스크 계산"과 "리밸런싱 제안"은 서로 다른 전문 지식 영역이다. 하나로 뭉치면 응집도가 깨지고 변경 파급이 커진다.
- **Clean Architecture / SOLID(DIP)**: 시세 공급자, DB, 리포트 출력 형식은 언제든 바뀔 수 있는 세부사항이다. domain은 이 세부사항의 "인터페이스"만 알고, 실제 구현은 infrastructure에 격리한다.
- **Test First**: domain/application은 외부 의존이 없으므로 순수 함수/객체로 테스트 가능. infrastructure는 통합 테스트, interfaces는 e2e 테스트로 검증한다(`tests/unit`, `tests/integration`, `tests/e2e`).
- **설정 파일 기반**: IPS와 Rule은 `config/`의 YAML로 관리되어, 코드 재배포 없이 투자 규칙을 조정할 수 있다.
- **확장성**: 새 자산군(예: 가상자산 확장) 또는 새 데이터 공급자를 추가할 때 기존 컨텍스트의 domain 계약을 유지한 채 infrastructure에 어댑터만 추가하면 된다.

## 5. 디렉터리 트리 요약

```
ai_fams/
├── config/                 # IPS/Rule/App 설정 (YAML)
├── docs/                   # 설계 문서, ADR
├── src/pams/
│   ├── shared_kernel/
│   ├── asset/ ips/ portfolio/ risk/ rebalancing/ performance/
│   ├── market_data/ reporting/ journal/ ai_analysis/ audit/
│   │   └── (각 컨텍스트: domain/ application/ infrastructure/)
│   └── interfaces/{cli,api}/
├── tests/{unit,integration,e2e}/
├── data/                   # 로컬 캐시 (git 비추적)
└── reports/                # 생성된 리포트 출력 (git 비추적)
```

## 6. 다음 단계

Phase 2(데이터 모델 설계)에서 `asset`, `portfolio` 등의 domain 엔티티/값객체를 pydantic으로 구체화한다.
