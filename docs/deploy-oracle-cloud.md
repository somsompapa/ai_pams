# Oracle Cloud Always Free에 PAMS 배포하기

PC를 켜둘 필요 없이, 무료 클라우드 서버에 PAMS를 상시 띄워 폰·PC 어디서나 접속한다.
Oracle Cloud "Always Free"는 신용카드 등록만으로 **평생 무료** 자원을 제공한다
(ARM Ampere 4 vCPU / 24GB RAM 또는 AMD Micro 2대). PAMS에는 차고 넘친다.

> ⚠️ 개인 자산 데이터가 클라우드에 올라간다. 아래 **보안(4단계)**을 반드시 적용한다:
> `PAMS_PASSWORD` 설정 + (Tailscale 또는 HTTPS). 인증 없이 공개하지 않는다.

---

## 0. 준비물

- 이메일, 휴대폰, 신용/체크카드(본인확인용 — 무료 자원은 과금되지 않음)
- 로컬 터미널(SSH) 또는 Oracle 콘솔의 Cloud Shell

## 1. 무료 서버(VM) 생성

1. https://www.oracle.com/kr/cloud/free/ 에서 가입 → 홈 리전은 **가까운 곳(예: 남한 = Seoul/Chuncheon)** 선택(나중에 못 바꿈).
2. 콘솔 → **Compute → Instances → Create Instance**
3. 설정:
   - **Image**: Canonical **Ubuntu 22.04** (또는 24.04)
   - **Shape**: `VM.Standard.A1.Flex` (ARM, Always Free) — vCPU 1~2, RAM 6GB면 충분
     - ARM이 "out of capacity"로 안 잡히면 `VM.Standard.E2.1.Micro`(AMD, Always Free)로 대체
   - **SSH 키**: "Generate a key pair" → **개인키(.key) 다운로드 후 잘 보관**
4. **Create** → 몇 분 뒤 인스턴스의 **Public IP** 확인(예: `140.238.x.x`)

## 2. 방화벽 열기 (접속 방식에 따라 선택)

- **Tailscale로 접속할 것이면(권장)**: 8000 포트를 인터넷에 열지 **않는다**. 3단계로 건너뛴다.
- **공개 HTTPS로 접속할 것이면**: 콘솔 → 인스턴스의 **Subnet → Security List → Add Ingress Rules**
  에서 `443`(HTTPS) 허용. (Oracle 방화벽 + Ubuntu의 `iptables` 둘 다 열어야 하는 경우가 있다.)

## 3. 서버 접속 + Docker 설치

```bash
# 로컬에서 SSH 접속 (내려받은 키 사용)
chmod 600 ~/Downloads/ssh-key.key
ssh -i ~/Downloads/ssh-key.key ubuntu@<PUBLIC_IP>

# 서버에서: Docker + git 설치
sudo apt-get update && sudo apt-get install -y docker.io git
sudo usermod -aG docker $USER && newgrp docker   # sudo 없이 docker 쓰기
```

## 4. 보안 — 접속 방법 두 가지 중 하나

### 방법 A: Tailscale (권장 — 서버를 인터넷에 노출하지 않음)

```bash
# 서버에 Tailscale 설치
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up          # 출력된 URL을 브라우저에서 열어 로그인(무료 계정)
tailscale ip -4            # 이 서버의 Tailscale 주소 확인 (예: 100.x.y.z)
```
- 폰·PC에도 Tailscale 앱을 설치하고 같은 계정으로 로그인.
- 이후 대시보드는 `http://100.x.y.z:8000` 로만 접속된다(내 기기끼리 전용 통로).
- **개인 금융 데이터에 가장 안전**하다. `PAMS_PASSWORD`는 이중 안전장치로 함께 쓴다.

### 방법 B: 공개 HTTPS (어디서나 도메인으로, 인증 필수)

도메인이 있고 아무 브라우저에서나 접속하려면 Caddy로 자동 HTTPS를 붙인다.
(Tailscale이 더 쉽고 안전하므로, 확신이 없으면 방법 A를 쓴다.)

## 5. PAMS 실행

```bash
git clone https://github.com/somsompapa/ai_fams.git
cd ai_fams

docker build -t pams .

docker run -d --name pams --restart unless-stopped \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -e PAMS_MODE=real \
  -e PAMS_PASSWORD='길고-강한-비밀번호' \
  -e ANTHROPIC_API_KEY='sk-...(선택: AI 해설용)' \
  pams
```

- `--restart unless-stopped`: 서버 재부팅 시 자동으로 다시 뜬다.
- `-v $(pwd)/data:/app/data`: 자산 데이터는 컨테이너 밖 `data/`에 남아 컨테이너를 지워도 보존된다.
- 아직 `data/`가 비어 있어 `PAMS_MODE=real`은 "이력 부족" 에러를 낸다 → 6단계에서 채운다.

## 6. 내 데이터 넣고 매일 자동 갱신

```bash
# 자산 목록 등록: config/assets/default.yaml 을 내 보유 종목으로 편집
# 거래 내역: examples/transactions.csv 를 참고해 data/transactions.csv 작성
cp examples/transactions.csv data/transactions.csv   # 편집해서 내 거래로

# 심볼 매핑 확인/수정: config/market/symbols.yaml (Yahoo 심볼)

# 과거 3일치 백필(예시) — 시세를 받아 스냅샷 적재
docker exec pams python -m pams.interfaces.cli fetch
docker exec pams python -m pams.interfaces.cli snapshot

# 매일 자동화: 서버 crontab 등록 (평일 18시 시세수집→적재→규칙알림)
crontab -e
# 아래 한 줄 추가:
0 18 * * 1-5 docker exec pams sh -c 'python -m pams.interfaces.cli fetch && python -m pams.interfaces.cli snapshot && python -m pams.interfaces.cli alert'
```

이력이 3일 이상 쌓이면 대시보드가 완전히 동작한다.

## 7. 접속 확인

- 방법 A(Tailscale): 폰/PC 브라우저에서 `http://100.x.y.z:8000`
- 로그인 창이 뜨면 사용자명은 아무거나, 비밀번호는 `PAMS_PASSWORD` 값.
- 폰에서 "홈 화면에 추가"하면 앱처럼 설치된다(PWA).

## 업데이트 / 백업 / 문제 해결

```bash
# 코드 업데이트
cd ai_fams && git pull && docker build -t pams . \
  && docker rm -f pams && docker run -d --name pams --restart unless-stopped \
     -p 8000:8000 -v $(pwd)/data:/app/data -e PAMS_MODE=real -e PAMS_PASSWORD='...' pams

# 데이터 백업: data/ 폴더만 복사하면 끝 (다른 서버로 이사도 이 폴더만 옮기면 됨)
tar czf pams-data-$(date +%F).tgz data/

# 로그 확인
docker logs --tail 100 pams
```

## 비용

Always Free 자원 범위 내(ARM 4 vCPU·24GB 중 일부, 또는 AMD Micro)에서는 **과금되지 않는다**.
PAMS는 CPU·메모리를 거의 쓰지 않으므로 무료 한도로 수년간 운영 가능하다.
