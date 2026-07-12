#!/usr/bin/env bash
#
# PAMS 원커맨드 설치 스크립트 (Ubuntu 22.04/24.04 서버에서 실행)
#
# 사용법 (서버에 SSH 접속한 뒤):
#   curl -fsSL https://raw.githubusercontent.com/somsompapa/ai_pams/main/deploy/setup.sh -o setup.sh
#   PAMS_PASSWORD='길고-강한-비밀번호' bash setup.sh
#
# 선택 환경변수:
#   PAMS_PASSWORD      대시보드 로그인 비밀번호 (미지정 시 자동 생성해 출력)
#   ANTHROPIC_API_KEY  AI 해설용 (없으면 AI 해설만 비활성, 나머지는 정상)
#   PAMS_BRANCH        배포할 브랜치 (기본 main)
#
set -euo pipefail

REPO_URL="https://github.com/somsompapa/ai_pams.git"
BRANCH="${PAMS_BRANCH:-main}"
APP_DIR="$HOME/ai_pams"

echo "==> [1/5] 필수 패키지 설치 (docker, git)"
if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y docker.io git
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$USER" || true
fi

# usermod 반영 전이라 이 스크립트 안에서는 sudo로 docker를 호출한다.
DOCKER="sudo docker"

echo "==> [2/5] 저장소 준비 ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch origin "$BRANCH"
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> [3/5] 비밀번호 준비"
if [ -z "${PAMS_PASSWORD:-}" ]; then
  PAMS_PASSWORD="$(openssl rand -base64 18 2>/dev/null || head -c 24 /dev/urandom | base64)"
  GENERATED=1
fi

echo "==> [4/5] 이미지 빌드 (ARM에서는 수 분 걸릴 수 있음)"
$DOCKER build -t pams .

echo "==> [5/5] 컨테이너 실행"
$DOCKER rm -f pams >/dev/null 2>&1 || true
$DOCKER run -d --name pams --restart unless-stopped \
  -p 8000:8000 \
  -v "$APP_DIR/data:/app/data" \
  -e PAMS_MODE=real \
  -e PAMS_PASSWORD="$PAMS_PASSWORD" \
  ${ANTHROPIC_API_KEY:+-e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY"} \
  pams

cat <<INFO

============================================================
 PAMS 설치 완료
============================================================
 접속:      http://<이 서버의 접속 IP>:8000
 로그인:    사용자명 아무거나 / 비밀번호 아래 값
 비밀번호:  $PAMS_PASSWORD
INFO
if [ "${GENERATED:-0}" = "1" ]; then
  echo " (비밀번호를 자동 생성했습니다. 꼭 안전한 곳에 저장하세요.)"
fi
cat <<INFO

 지금은 data/ 가 비어 있어 대시보드가 "이력 부족"을 안내합니다.
 다음 순서로 내 데이터를 채우세요:

   cd $APP_DIR
   cp examples/transactions.csv data/     # 편집: 내 거래 내역
   nano config/assets/default.yaml        # 내 보유 종목 등록
   sudo docker exec pams python -m pams.interfaces.cli fetch
   sudo docker exec pams python -m pams.interfaces.cli snapshot

 매일 자동화(평일 18시) — crontab -e 에 추가:
   0 18 * * 1-5 sudo docker exec pams sh -c 'python -m pams.interfaces.cli fetch && python -m pams.interfaces.cli snapshot && python -m pams.interfaces.cli alert'

 외부에서 안전하게 접속하려면 Tailscale 권장:
   docs/deploy-oracle-cloud.md 의 4단계 참고
============================================================
INFO
