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
| `interfaces` | CLI, REST API, 웹 대시보드 진입점 + 조립 지점(wiring) | Phase 9 |

컨텍스트 간 통신은 원칙적으로 `application` 계층의 유스케이스 호출로만 이루어지며,
서로의 `domain`/`infrastructure` 내부를 직접 참조하지 않는다(모듈 경계 보호).
여러 컨텍스트가 공유하는 어휘(`Asset`, `AssetClass`, `AllocationTarget`)는
`shared_kernel`에 두어 순환 의존을 피한다.

### 3.1 데이터 흐름 (IPS → Rule → Data → 계산 → 결과)

`interfaces`의 조립 지점(`DashboardService.compute()`, `wiring.py`)이 유스케이스를 오케스트레이션한다.

```
거래기록(CSV) ─▶ portfolio: BuildPortfolioSnapshot ─▶ 스냅샷(총자산/손익/비중/지표)
                                                          │
시세·환율(CSV) ────────────────────────────────────────┘
                                                          ▼
가치이력(JSONL) ─▶ risk: ComputeRiskReport ─────▶ 위험지표 ─┐
                    performance: ComputePerformance ─▶ 성과   │
                                                              ▼
시장지표(YAML) ──▶ ips: EvaluateCompliance(Rule Engine) ─▶ ComplianceReport(판정)
                                                              │
투자헌장(YAML) ──▶ rebalancing: ProposeRebalancing ────▶ 리밸런싱 제안
                                                              ▼
                    reporting: AssembleInvestmentReport ─▶ 보고서(MD/HTML/PDF)
                    interfaces/api: 대시보드 JSON / 텔레그램 알림
                    ai_analysis: 위 결과의 사실을 받아 해설(계산·판단 없음)
```

- **판단은 오직 `ips`의 Rule Engine**이 내린다. 지표가 누락되면 조용히 넘어가지 않고 `MissingMetricError`로 실패한다.
- 리스크 지표 중 수학적으로 정의되지 않는 값(하락 없는 시계열의 Sortino 등)은 **0을 지어내지 않고 생략**한다.
- AI는 계산된 사실(facts)만 입력받으며, 프롬프트 제약으로 숫자 생성·매매 판단이 금지된다.

## 4. 왜 이 구조인가

- **DDD**: "포트폴리오 계산"과 "리스크 계산"과 "리밸런싱 제안"은 서로 다른 전문 지식 영역이다. 하나로 뭉치면 응집도가 깨지고 변경 파급이 커진다.
- **Clean Architecture / SOLID(DIP)**: 시세 공급자, DB, 리포트 출력 형식은 언제든 바뀔 수 있는 세부사항이다. domain은 이 세부사항의 "인터페이스"만 알고, 실제 구현은 infrastructure에 격리한다.
- **Test First**: domain/application은 외부 의존이 없으므로 순수 함수/객체로 테스트 가능. infrastructure와 interfaces는 통합 테스트로 전체 파이프라인(거래→대시보드)까지 검증한다(`tests/unit`, `tests/integration`).
- **설정 파일 기반**: IPS와 Rule은 `config/`의 YAML로 관리되어, 코드 재배포 없이 투자 규칙을 조정할 수 있다.
- **확장성**: 새 자산군(예: 가상자산 확장) 또는 새 데이터 공급자를 추가할 때 기존 컨텍스트의 domain 계약을 유지한 채 infrastructure에 어댑터만 추가하면 된다.

## 5. 디렉터리 트리 요약

```
ai_fams/
├── config/                 # IPS/Rule/App/자산/리스크/거래비용 설정 (YAML)
│   ├── ips/ rules/ risk/ costs/ assets/ app/
├── docs/                   # 설계 문서, ADR
├── examples/               # data/ 파일 형식 예시 (CSV/YAML)
├── src/pams/
│   ├── shared_kernel/      # 공유 값객체·엔티티 (domain만)
│   ├── asset/ ips/ portfolio/ risk/ rebalancing/ performance/
│   ├── market_data/ reporting/ journal/ ai_analysis/ audit/
│   │   └── (각 컨텍스트: domain/ application/ infrastructure/)
│   └── interfaces/
│       ├── api/            # FastAPI 앱 + 대시보드(정적 HTML/PWA)
│       ├── cli/            # snapshot / report / alert 명령
│       ├── wiring.py       # 실데이터 조립 지점
│       └── notifications.py
├── tests/{unit,integration}/
├── Dockerfile              # 홈서버/VPS 배포
├── data/                   # 거래·시세·이력 등 (git 비추적)
└── reports/                # 생성된 리포트 출력 (git 비추적)
```

## 6. 실행 형태

- **로컬/데모**: `make serve` → `http://127.0.0.1:8000` (데모 데이터)
- **실데이터**: `data/`를 채우고 `make snapshot`(일별 적재) 후 `PAMS_MODE=real make serve`
- **CLI**: `snapshot`(가치 적재), `report`(MD/HTML/PDF 보고서), `alert`(규칙 발동 시 텔레그램)
- **배포**: `Dockerfile`로 홈서버/VPS에 상주. `PAMS_PASSWORD`로 인증, Tailscale 권장
- 상세 사용법은 [`README.md`](../README.md), 설정 예시는 [`examples/`](../examples) 참고

## 7. 핵심 설계 결정 (ADR)

- [0001](adr/0001-architecture-and-module-structure.md): DDD 바운디드 컨텍스트 × Clean Architecture
- [0002](adr/0002-domain-models-stdlib-dataclass.md): 도메인 모델은 stdlib dataclass (pydantic은 경계에서만)
- [0003](adr/0003-file-based-adapters-and-modes.md): 파일 기반 어댑터와 데모/실데이터 모드 분리
