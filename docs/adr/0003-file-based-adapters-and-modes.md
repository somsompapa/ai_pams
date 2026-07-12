# ADR 0003: 파일 기반 어댑터와 데모/실데이터 모드 분리

- 상태: 채택됨
- 일자: 2026-07-11

## 배경

계산 엔진(Phase 1~10)은 전부 포트(Protocol)에 의존하도록 설계됐지만, 실제 사용을
위해서는 거래·시세·환율·가치이력을 어딘가에서 읽어야 한다. 증권사 API를 즉시
붙이기에는 (1) 사용자마다 사용하는 증권사·데이터 소스가 다르고 (2) API 키 발급과
계약이 선행되어야 하며 (3) 개발/데모 단계에서 실계좌 없이 전체 흐름을 검증할 수
있어야 한다.

## 결정

1. **1차 어댑터는 파일 기반**으로 구현한다.
   - 거래: `CsvTransactionRepository` (`data/transactions.csv`)
   - 자산 마스터: `YamlAssetCatalog` (`config/assets/default.yaml`)
   - 시세/환율: `CsvPriceLookup`, `CsvFxLookup` (`data/prices.csv`, `data/fx.csv`)
   - 가치 이력: `JsonlValueHistoryRepository` (`data/value_history.jsonl`)
   - 감사/일지: JSONL append-only
2. **시세/환율은 as_of 당일 데이터가 없으면 직전 데이터를 사용**하고, 미래 데이터는
   절대 반환하지 않는다(주말·휴장 대응, look-ahead 방지).
3. **데모 모드와 실데이터 모드를 환경변수로 분리**한다(`PAMS_MODE`). 기본은 데모라
   설치 직후 바로 화면을 볼 수 있고, `PAMS_MODE=real`이면 `interfaces/wiring.py`가
   파일 어댑터로 시스템을 조립한다.
4. **일별 총자산 적재를 별도 유스케이스**(`RecordDailyValuation`)로 두고 CLI로
   노출한다. 당일 입출금은 `net_flow`로 함께 기록해 TWR 왜곡을 막는다.
5. 실데이터 파일이 없거나 부족하면 **해결 방법이 담긴 `RealDataError`**로 실패한다.

## 근거

- 엔진이 포트에만 의존하므로, 파일 어댑터를 증권사 API 어댑터로 교체해도
  domain/application 코드는 바뀌지 않는다(개방-폐쇄 원칙의 실증).
- 파일 기반은 사용자가 내용을 직접 보고 수정할 수 있어 개인 도구에 적합하고,
  `data/` 폴더 복사만으로 다른 서버로 이사할 수 있다.
- 데모/실데이터 분리로 CI·개발은 실계좌 없이 전 기능을 통합 테스트한다.

## 결과

- `examples/`에 모든 데이터 파일의 형식 예시를 제공한다.
- 증권사/시세 API 연동은 이 포트에 어댑터를 추가하는 후속 작업으로 남는다.
- 경제지표·뉴스 자동수집(C1), 양도세 정밀화(C3)도 같은 포트 확장 패턴을 따른다.
