# PAMS (Personal Asset Management System)

투자헌장(IPS)을 엄격하게 실행하는 개인 자산운용 엔진.
AI는 판단하지 않는다 — 모든 의사결정은 `IPS → Rule → Data → 계산 → 결과` 순서로만 이루어진다.
AI(Claude)의 역할은 계산 결과의 분석/설명/요약/보고서 작성으로 한정된다.

## 절대 원칙

1. Rule Engine이 판단하고, AI는 해설만 한다. AI가 매매/비중을 "감"으로 결정하는 코드를 절대 작성하지 않는다.
2. 투자 규칙(IPS, Rule)은 코드에 하드코딩하지 않고 `config/`의 YAML로 관리한다.
3. domain/application 계층은 외부 라이브러리·DB·네트워크에 의존하지 않는다(순수 Unit Test 가능해야 함).
4. 데이터 공급자는 domain의 포트(인터페이스)로 추상화하고 infrastructure에서 구현한다 — 언제든 교체 가능.
5. Test First: 구현 전에 테스트를 먼저 작성한다. 테스트 없는 로직은 머지하지 않는다.
6. 자동매매는 목표가 아니다. 시스템은 제안까지만 하고, 최종 실행은 사용자가 한다.
7. 임시 코드, 하드코딩, 중복 코드를 허용하지 않는다.

## 구조

- `src/pams/<context>/{domain,application,infrastructure}` — DDD 바운디드 컨텍스트 × Clean Architecture 3계층. 의존성은 항상 domain 방향.
- 컨텍스트: `shared_kernel`(domain만), `asset`, `ips`, `portfolio`, `risk`, `rebalancing`, `performance`, `market_data`, `reporting`, `journal`, `ai_analysis`, `audit`, `interfaces`(cli/api)
- 컨텍스트끼리는 application 유스케이스로만 통신하고, 서로의 domain/infrastructure 내부를 직접 import하지 않는다.
- 상세: `docs/architecture.md`, 결정 기록: `docs/adr/`

## 개발 명령어

```bash
make install   # 개발 의존성 설치 (pip install -e ".[dev]")
make test      # pytest (tests/unit, tests/integration, tests/e2e)
make lint      # ruff check + format check
make typecheck # mypy (strict)
make check     # lint + typecheck + test 전부
make serve     # 대시보드 실행 (PAMS_MODE=real 이면 실데이터)
make snapshot  # 일별 총자산 적재 (매일 실행)
make report    # 투자 보고서 생성 (reports/, MD/HTML/PDF)
make alert     # 규칙 발동 시 텔레그램 알림
```

CI(GitHub Actions, `.github/workflows/ci.yml`)가 push/PR마다 `make check`를 실행한다.

## 개발 진행 방식

- Phase 1~10은 완료됐다(엔진 전부 + 실데이터 어댑터 + 인증/PWA/Docker + 보고서·알림 CLI). 후속 작업은 증권사/시세 API 연동(C1), 양도세 정밀화(C3) 등 포트 확장.
- 각 작업은 요구사항 분석 → 설계 → 인터페이스(포트) → 테스트 → 구현 → 리팩토링 순서를 지킨다(Test First).
- 금액 계산에는 float를 쓰지 않는다. `Decimal` 기반 값객체(shared_kernel)를 사용한다.
- 새 데이터 소스는 기존 포트(예: `PriceLookup`, `TransactionRepository`)에 어댑터를 추가하는 방식으로 붙인다 — domain/application은 건드리지 않는다.
