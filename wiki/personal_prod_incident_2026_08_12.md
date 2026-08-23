# 개인 PROD 모바일 등록 및 Target OTA 장애 리포트

## 1. 범위와 결론

- 조사 일시: 2026-08-12 KST
- 범위: 개인 휴대폰, 현관 매립 Target, NAS backend/admin, Mosquitto, 모바일 APK 배포 경로
- 모바일 등록·승인·문 열기 UI 수정과 NAS/APK 배포는 완료했다.
- Target은 BLE iBeacon을 송신하므로 MCU와 BLE 루프는 살아 있다.
- Target OTA는 완료되지 않았다. 최종 확인 펌웨어는 `2.1.0-g75b946a`이고 새로운 OTA 명령은 Target 온라인 증거가 없어 발행하지 않았다.
- 관측 증거는 Wi-Fi/MQTT 유지 또는 재접속 문제를 가리킨다. Target을 최신 펌웨어로 갱신했다는 주장은 금지한다.
- 본문의 `SmartGatekeeper-Setup`은 조사 당시 구형 firmware의 역사적 SSID다.
  최신 `main`의 인증 recovery AP는 `SmartGatekeeper-Recovery`를 사용한다.

## 2. 모바일·backend 문제와 수정

### 2.1 관리자 기기 ID 공란

관리자 tenant 목록 API가 `ble_device_mac`을 SELECT하지 않으면서 화면은 해당 필드를 렌더링하고 있었다. 조회 필드를 복구하고 NAS backend를 재빌드했다. 실환경 관리자 목록에서 기존 모바일 ID가 반환되는 것을 확인했다.

### 2.2 권한 신청 버튼 무응답

기존 WebView 페이지의 신청 함수는 안내만 표시하고 backend 등록 API를 호출하지 않았다. 다음과 같이 복구했다.

- Flutter native bridge가 휴대폰의 영구 Device ID를 읽는다.
- 앱에 주입된 API key로 `/api/v1/user/me` 및 `/api/v1/user/request`를 호출한다.
- backend는 인증된 개인 PROD 등록 요청만 수락한다.
- 이미 활성화된 기기의 반복 요청은 권한을 비활성화하지 않는다.
- DB 저장 실패를 성공으로 위장하지 않고 HTTP 503으로 반환한다.

기존 모바일 ID의 실환경 상태는 `approved`로 확인했다. 이전 `미등록 기기` 표시는 DB 권한 소실이 아니라 기존 앱의 인증 상태 조회 경로 부재였다.

### 2.3 승인 후 문 열기 비활성

승인 응답을 받은 뒤에도 웹 코드가 `btnOpen.disabled = true`로 고정했고, 버튼 함수도 실제 출입 요청을 수행하지 않았다. 승인 상태에서만 버튼을 켜고 다음 경로로 연결했다.

1. native code가 현재 Device ID의 승인 상태를 backend에서 다시 확인한다.
2. 신뢰한 `https://tworimpa.synology.me:4442/app` origin만 native bridge를 사용할 수 있다.
3. 승인된 요청은 Android native Local GATT retry 경로로 전달한다.
4. Target FSM과 보유 증명 검증은 우회하지 않는다.

주의: 구형 `2.1.0-g75b946a`에는 현재 Local GATT 인증 서버가 없다. 따라서 버튼 활성화 수정과 별개로 실제 Local GATT 출입은 Target 최신화 이후 검증해야 한다.

## 3. 배포 및 검증 증거

| 항목 | 결과 |
|---|---|
| 등록 복구 커밋 | `647df63ce29e10f45ba263f8f316239312da64e5` |
| 문 열기 활성화 커밋 | `d4f88327bc5fba35d4cde80d0fddc8db4ec6ffe9` |
| 모바일 등록 복구 빌드 | `1.0.0-g647df63`, build 140 |
| 최종 모바일 빌드 | `1.0.0-gd4f8832`, build 141 |
| build 141 CI | GitHub Actions run `31588627694`, 성공 |
| Flutter 분석·테스트 | CI 성공 |
| APK 서명·manifest 검증 | CI 성공 |
| NAS APK 게시 | 성공 |
| 외부 APK read-back | 55,729,022 bytes, manifest SHA-256 일치 |
| backend health | 정상 |
| PROD `/app` read-back | 승인 활성화 및 `open_door` native action 포함 확인 |

NAS 웹 파일 교체 전 백업을 남겼으며, 비밀값은 로그·문서·커밋에 출력하지 않았다.

## 4. Target·MQTT 조사 결과

### 4.1 구형 연결 계약

`2.1.0-g75b946a`는 `tworimpa.synology.me:4883` MQTTS에 접속한다. 외부 4883 포트, NAS Mosquitto TLS listener와 동일 자격 증명의 진단 접속은 정상이다. 구형 코드는 부팅 시 HTTPS OTA를 확인하지 않고 MQTT `ota_update` 명령만 처리한다.

### 4.2 실제 Target 브로커 증거

- 실제 Target client ID `smart-gatekeeper-c0fefe6ebac`가 2026-08-12 17:02 KST에 TLS/MQTT 인증 접속에 성공했다.
- 약 90초 뒤 broker keepalive timeout으로 연결이 종료됐다.
- retained boot는 firmware `2.1.0-g75b946a`, boot count 34, reset `BROWNOUT`, planned restart `none`이다.
- 이후 전원 재인가에도 새로운 boot count, boot ID 또는 `online` 신호가 관측되지 않았다.
- 휴대폰에서는 Target iBeacon이 감지됐다. 따라서 MCU 전원과 BLE 송신은 살아 있다.
- Target MAC 후보 `0C-0F-EF-E6-EB-AC`는 조사 시점 `192.168.55.0/24` 이웃 목록에 없었고, LAN port 80 탐색에서도 공유기와 NAS 외 Target HTTP 서버는 발견되지 않았다.
- `SmartGatekeeper-Setup` SSID는 휴대폰 Wi-Fi 목록에서 발견되지 않았다.

이 증거는 서버의 MQTT 주소·TLS·계정 불일치보다 Target의 Wi-Fi 연결 또는 MQTT 연결 유지/재접속 문제를 우선 가리킨다. BLE 비콘만으로 Wi-Fi 연결 성공을 의미하지 않는다.

### 4.3 진단 client ID 충돌

20:02 KST Mosquitto 로그의 반복 `sgk-personal-prod-audit`와 `session taken over`는 Target이 아니다. 동일 client ID를 사용한 로컬 진단 프로세스 두 개가 서로 연결을 인계한 운영 도구 오류다.

- TLS 연결은 성공했다.
- 비밀번호·키는 로그에 출력되지 않았다.
- Target 세션과 다른 client ID이므로 Target 권한이나 상태를 변경하지 않았다.
- 충돌 원인을 확인한 뒤 진단 client ID에 프로세스 ID를 포함하도록 임시 도구를 수정했다.
- 종료 시 진단 프로세스 잔여 수 `0`을 확인했다.

## 5. OTA 안전 경계

- MQTT QoS 1 PUBACK는 broker 수신만 증명하며 Target 실행을 증명하지 않는다.
- Target이 offline인 상태에서 비보존 명령을 반복 발행하지 않는다.
- retained OTA 명령은 사용하지 않는다.
- 이번 조사에서는 새로운 `online`을 보지 못했으므로 OTA 명령을 발행하지 않았다.
- 최종 성공 조건은 새 firmware boot, planned restart `ota_update`, software reset, health 확인까지다.
- health 실패 시 승인된 이전 버전 rollback 계약을 따른다.

## 6. 다음 재개 절차

1. NAS MQTT 인증서의 당시 만료일 `2026-08-14T00:03:10Z`를 확인하고 먼저 갱신한다.
2. 공유기 DHCP lease에서 Target MAC과 2.4 GHz SSID 연결 이력을 확인한다.
3. 휴대폰에서 `SmartGatekeeper-Setup`을 보안 없음 네트워크로 수동 추가하고 `http://192.168.4.1` 연결을 시험한다.
4. 고유 client ID의 read-only 감시를 먼저 시작한다.
5. Target `online`과 현재 firmware를 확인한 뒤 `smart-gatekeeper/cmd`에 `{"command":"ota_update"}`를 QoS 1, retain false로 한 번만 발행한다.
6. 새 boot의 firmware, reset, planned restart, boot count와 backend health를 확인한다.
7. 최신 firmware에서는 부팅 후 및 주기적 HTTPS OTA pull이 동작하는지 별도 확인한다.

## 7. 최종 상태

| 영역 | 상태 |
|---|---|
| NAS backend/admin | 배포·health 확인 완료 |
| 모바일 승인/신청 | 수정·PROD 배포 완료 |
| 모바일 문 열기 버튼 | 수정·build 141 배포 완료 |
| 실제 Local GATT 개방 | 구형 Target 때문에 미검증 |
| Target 전원/BLE | iBeacon 관측 |
| Target Wi-Fi | 미확인/연결 증거 없음 |
| Target MQTT | 마지막 실제 접속 후 timeout, 현재 offline |
| Target OTA | 미완료, 명령 미발행 |
