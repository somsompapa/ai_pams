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
| 10 | AI 분석 기능 (Claude 해설, 투자일지) | ✅ |
| + | 감사 로그(audit), PDF 보고서, 대시보드 일지/AI 해설 화면 | ✅ |

지원 자산: 국내주식 · 미국주식 · ETF · 채권 · 현금 · 예수금 · 외화 · 금 · 연금 · 가상자산(확장 가능)

AI 해설을 사용하려면 `ANTHROPIC_API_KEY`를 설정한다 (`.env.example` 참고).
PDF 보고서는 한글 TTF 폰트가 필요하다 (예: `apt-get install fonts-nanum`).

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

## 실데이터로 사용하기

기본은 데모 데이터로 동작한다. 내 자산으로 전환하려면:

```bash
# 1. 데이터 파일 준비 (형식은 examples/ 참고)
cp examples/transactions.csv data/   # 내 거래 내역으로 수정
cp examples/prices.csv data/         # 시세 (매일 갱신)
cp examples/fx.csv data/             # 환율 (외화 자산이 있을 때)
cp examples/market.yaml data/        # 시장 지표 (vix 등)
#    자산 목록은 config/assets/default.yaml 에 등록

# 2. 일별 총자산 적재 (매일 실행 - cron 등록 권장. 과거일 백필도 가능)
make snapshot
python -m pams.interfaces.cli snapshot --date 2026-07-08   # 백필 예시

# 3. 실데이터 모드로 대시보드 실행 (이력 3일 이상 필요)
PAMS_MODE=real make serve

# 같은 와이파이의 폰에서 보려면
PAMS_MODE=real PAMS_HOST=0.0.0.0 make serve   # 폰에서 http://<PC 내부IP>:8000
```

## 서버에 항상 켜두기 (홈서버/VPS)

PC를 켜두기 싫다면 라즈베리파이·미니PC 또는 VPS에 Docker로 올린다:

```bash
docker build -t pams .
docker run -d --name pams --restart unless-stopped -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -e PAMS_MODE=real -e PAMS_PASSWORD=강한비밀번호 pams
```

- `PAMS_PASSWORD`를 설정하면 모든 화면/API에 로그인이 필요하다.
- 외부 접속은 서버를 인터넷에 공개하는 대신 **Tailscale**(서버·폰에 설치)을 권장한다.
- 폰 브라우저에서 접속 후 "홈 화면에 추가"하면 앱처럼 설치된다(PWA).
- 일별 적재는 서버 crontab에 등록한다: `0 18 * * 1-5 docker exec pams python -m pams.interfaces.cli snapshot`

상세 설계는 [`docs/architecture.md`](docs/architecture.md)를 참고.
