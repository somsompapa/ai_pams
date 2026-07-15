#!/usr/bin/env bash
#
# main 브랜치 push마다 GitHub Actions self-hosted runner(서버 자신)가 실행하는
# 배포 스크립트. CI(make check)를 통과한 커밋만 여기 도달한다.
#
# 전제:
#   - $APP_DIR 에 deploy/setup.sh로 만든 저장소가 이미 있다(git clone 완료).
#   - $APP_DIR/.env.deploy 에 비밀값(PAMS_PASSWORD 등)이 KEY=VALUE로 있다.
#     이 파일은 git에 커밋되지 않고, GitHub Secrets도 거치지 않는다 —
#     서버에만 존재한다.
set -euo pipefail

APP_DIR="$HOME/ai_pams"
ENV_FILE="$APP_DIR/.env.deploy"

if [ ! -f "$ENV_FILE" ]; then
  echo "실패: $ENV_FILE 이 없다. 배포 전 1회 만들어야 한다." >&2
  exit 1
fi

echo "==> [1/4] 최신 커밋으로 갱신"
cd "$APP_DIR"
git fetch origin main
git reset --hard origin/main   # skip-worktree 개인 설정 파일은 그대로 유지된다

echo "==> [2/4] 이미지 빌드"
docker build -t pams .

echo "==> [3/4] 컨테이너 재기동"
docker rm -f pams >/dev/null 2>&1 || true
docker run -d --name pams --restart unless-stopped \
  --env-file "$ENV_FILE" \
  -v "$APP_DIR/data:/app/data" \
  -v "$APP_DIR/config:/app/config" \
  -p 8000:8000 \
  pams

echo "==> [4/4] 헬스체크"
sleep 3
if [ "$(docker inspect -f '{{.State.Running}}' pams 2>/dev/null)" = "true" ]; then
  echo "배포 완료: pams 컨테이너 실행 중"
else
  echo "실패: 컨테이너가 실행 중이 아니다. 로그:" >&2
  docker logs --tail 50 pams >&2 || true
  exit 1
fi
