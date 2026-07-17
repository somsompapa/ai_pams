#!/usr/bin/env bash
#
# 종목분석(equity) 탭의 재무제표 자동조회(SEC EDGAR/DART)에 필요한 키를
# 서버의 .env.deploy에 추가/갱신한다.
#
# .env.deploy는 git에 커밋되지 않는 서버 전용 비밀값 파일이다(deploy/ci-deploy.sh
# 참고 — GitHub Secrets도 거치지 않는다). 그래서 이 스크립트는 CI가 아니라
# 서버에 SSH로 접속한 사람이 직접 실행해야 한다.
#
# 사용법 (서버에서):
#   cd ~/ai_pams
#   SEC_EDGAR_CONTACT_EMAIL='you@example.com' DART_API_KEY='발급받은키' \
#     bash deploy/set-equity-api-keys.sh
#
# 둘 중 하나만 갱신하려면 나머지 변수는 비워두면 된다. 이미 같은 키가 있으면
# 값을 덮어쓰고(직전 파일은 타임스탬프 붙여 백업), 없으면 새로 추가한다(멱등).
#
# DART_API_KEY 발급: https://opendart.fss.or.kr (무료 회원가입 후 발급)
# SEC_EDGAR_CONTACT_EMAIL: SEC 요구사항(연락처 포함 User-Agent, 없으면 403) — 본인 이메일이면 된다.
#
# 이 스크립트는 컨테이너를 재기동하지 않는다(운영 중 서비스를 스크립트가 임의로
# 중단시키지 않기 위함) — 다음 git push로 main이 갱신될 때 자동 반영되거나,
# 지금 바로 반영하려면 마지막에 안내되는 명령을 따로 실행하라.
set -euo pipefail

APP_DIR="$HOME/ai_pams"
ENV_FILE="$APP_DIR/.env.deploy"

if [ ! -f "$ENV_FILE" ]; then
  echo "실패: $ENV_FILE 이 없다. deploy/setup.sh로 먼저 설치했는지 확인하라." >&2
  exit 1
fi

if [ -z "${SEC_EDGAR_CONTACT_EMAIL:-}" ] && [ -z "${DART_API_KEY:-}" ]; then
  echo "실패: SEC_EDGAR_CONTACT_EMAIL 또는 DART_API_KEY 중 최소 하나는 환경변수로 전달해야 한다." >&2
  echo "예: SEC_EDGAR_CONTACT_EMAIL='you@example.com' DART_API_KEY='...' bash $0" >&2
  exit 1
fi

_backed_up=0

set_key() {
  local key="$1" value="$2"
  if [ -z "$value" ]; then
    return
  fi
  if grep -q "^${key}=" "$ENV_FILE"; then
    if [ "$_backed_up" -eq 0 ]; then
      cp "$ENV_FILE" "${ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"
      _backed_up=1
    fi
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    echo "갱신: $key"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    echo "추가: $key"
  fi
}

set_key "SEC_EDGAR_CONTACT_EMAIL" "${SEC_EDGAR_CONTACT_EMAIL:-}"
set_key "DART_API_KEY" "${DART_API_KEY:-}"

echo
echo "적용 완료: $ENV_FILE"
echo "지금 바로 반영하려면:  bash $APP_DIR/deploy/ci-deploy.sh"
echo "(아니면 다음 git push로 main이 갱신될 때 자동 반영된다)"
