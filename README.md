# PAMS — Personal Asset Management System

투자헌장(IPS)을 엄격하게 실행하는 개인 자산운용 엔진.

> 이 시스템은 투자 판단을 대신하는 AI가 아니다.
> 모든 의사결정은 **IPS → Rule → Data → 계산 → 결과** 순서로만 이루어진다.
> AI(Claude)는 계산하지 않으며, 결과의 분석·설명·요약·보고서 작성만 담당한다.
> 자동매매는 목표가 아니다 — 시스템은 제안까지만 하고, 최종 실행은 사용자가 한다.

## 기능 (Phase 로드맵)

| Phase | 내용 | 상태 |
|---|---|---|
| 1 | 프로젝트 구조 생성 | ✅ |
| 2 | 데이터 모델 설계 | ✅ |
| 3 | IPS 엔진 (투자헌장 + Rule Engine) | ✅ |
| 4 | 포트폴리오 엔진 (총자산/손익/비중) | ✅ |
| 5 | 리스크 엔진 (MDD, Sharpe, VaR, …) | ✅ |
| 6 | 리밸런싱 엔진 (매수/매도 제안, 세금/수수료) | ✅ |
| 7 | 성과분석 (기간별, 벤치마크 비교, 규칙 준수율) | ✅ |
| 8 | 보고서 생성 (Markdown/HTML/PDF) | ✅ |
| 9 | 웹 대시보드 (반응형, Dark/Light) | ✅ |
| 10 | AI 분석 기능 (Claude 해설, 투자일지) | ⬜ |

지원 자산: 국내주식 · 미국주식 · ETF · 채권 · 현금 · 예수금 · 외화 · 금 · 연금 · 가상자산(확장 가능)

## 시작하기

```bash
# Python 3.11+
python -m venv .venv && source .venv/bin/activate
make install
make check   # lint + typecheck + test
```

## 프로젝트 구조

```
config/          # IPS/Rule/App 설정 (YAML) — 투자 규칙은 코드가 아닌 여기서 관리
docs/            # 아키텍처 문서, ADR
src/pams/        # DDD 바운디드 컨텍스트 × Clean Architecture 3계층
tests/           # unit / integration / e2e
data/, reports/  # 로컬 캐시 및 생성된 리포트 (git 비추적)
```

상세 설계는 [`docs/architecture.md`](docs/architecture.md)를 참고.
