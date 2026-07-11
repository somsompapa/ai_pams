// PAMS 서비스 워커: PWA 설치 요건 충족용 최소 구현.
// 자산 데이터는 캐시하지 않는다 - 항상 서버의 최신 값을 보여준다.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
