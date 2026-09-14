# BLE 발견 실패 분석 및 개선안 — 2026-09-14

## 결론과 범위

이번 문앞 실패는 인증 후 초음파 판정이 아니라 **GATT 연결 전의 Target 발견 경로**에서 막혔다. 앱 단독 원인으로 확정할 수 없다. Target에는 사용자 지정 광고 데이터의 실패/재동기화 복구 공백이 있고, Android에는 동일 필터 재등록 이외의 판별 경로가 없다. 두 공백을 함께 고쳐야 한다.

본 문서는 읽기 전용 API/MQTT 관측 및 소스 분석 결과와 이후 승인된 구현 기록이다. 최초 분석은 Target500/main c74a557, Android44801/g5ca450a를 기준으로 하며 아래 소스 결함 설명도 이 설치 버전 기준이다. 분석 단계에는 런타임 변경이나 제어 명령을 수행하지 않았다. 이후 구현·배포 상태는 하단에서 별도로 구분한다. 물리적 RF 송출이나 문 개폐를 직접 측정하지 않았다.

## 이번 현장 증거 (KST)

| 시각 | 관측 | 의미와 한계 |
|---|---|---|
| 22:35:41 | 현장 관측 시작, boot905 | 과거 MQTT 재접속 증가를 이번 테스트 탓으로 돌리지 않는다 |
| 22:36:54 | health16421: 센서344mm, IDLE, GATTaccepted/proof/ARMED=0 | 센서에 유효 근거리 응답이 있으나 인증 시작 없음 |
| 22:37:24 | health16422: 센서302mm, valid_samples388, invalid_streak0 | 가까이 머무르지 않았다는 가정은 증거와 맞지 않는다 |
| 22:37:50 | mobile1626: APP_FOREGROUND 복구30초 후 NO_MATCHING_PACKET | 등록 요청 수락과 실제 수신은 다름 |
| 22:39:27 | health16426: 센서331mm, 광고active, GATT0 | MCU/MQTT 응답은 있으나 실제 광고 내용은 미검증 |
| 22:40:30 | verified access9782: ACCESS_SIGNED_MANUAL_COMPLETED | MQTT 수동 경로의 Target 완료 증거이며 문 물리 개폐 증거는 아님 |
| 22:42:50 | mobile1632: 다시 APP_FOREGROUND 복구 후 NO_MATCHING_PACKET | callback_count21, 마지막 패킷08:46:28로 그대로 |

모바일 업로드는 수신되고 pending0/ACCEPTED다. 보고서의 과거 SUCCEEDED를 현재 인증 성공으로 해석하면 안 된다. Bluetooth OFF/ON 실험을 사용자가 실제 수행했다는 증거는 없으므로 그 실험의 성공/실패도 단정하지 않는다.

## 소스에서 확인한 복구 공백

### 1. Target: 광고 active와 식별 데이터 정상 여부가 분리되어 있지 않음

- `src/main.cpp::setTxPower`는 사용자 지정 iBeacon primary 광고를 넣으면서 setAdvertisementData/setScanResponseData/start의 반환값을 확인하지 않는다.
- `src/GattServer.cpp`의 광고 복구는 isAdvertising()이 참이면 생략한다. PresenceAdvertisementPolicy가 복구하는 데이터는 주로 scan response의 readiness 정보이고 primary iBeacon을 재구성하지 않는다.
- 로컬 빌드 프레임워크 Arduino-ESP32 3.3.9의 BLEAdvertising은 사용자 지정 primary 데이터를 자동 재적용할 사본을 이 경로에 보관하지 않는다. onHostSync가 일반 데이터 플래그를 초기화해도 start의 재작성 분기는 custom 광고를 제외한다. set-data 실패 때도 custom 플래그가 설정된다. [동일 버전 상위 소스](https://raw.githubusercontent.com/espressif/arduino-esp32/3.3.9/libraries/BLE/src/BLEAdvertising.cpp)

따라서 Bluetooth host 재동기화로 controller 데이터가 사라지거나 최초 설정이 실패하면, **active지만 앱 필터에 필요한 primary 데이터가 복구되지 않는 경로**가 있다. 이는 코드상 미처리 경로다. 이번 기기에서 host reset이 실제 발생했는지는 기록이 없어 아직 가설이다. MCU boot 번호가 같아도 Bluetooth host reset까지 배제되지는 않는다.

### 2. Android: 복구도 기존 발견 방식에 의존

- `blewake/BleWakeRegistrar.kt`: Apple manufacturer ID와 고정 iBeacon UUID 필터, LOW_POWER 스캔. FIRST_MATCH/MATCH_LOST 및 ALL_MATCHES 두 PendingIntent 등록을 사용한다.
- 앱 전면 복구도 같은 필터·등록 경로를 재시작한다. `BleScanRecoveryObserver.kt`는 그 등록에서 패킷이 오는지30초 관찰할 뿐 별도의 수신 실험을 하지 않는다.
- OS 필터 뒤의 콜백만 기록하므로 무선 패킷 자체가 없는지, 다른 내용인지, OS 필터/전달 문제인지 구분할 수 없다.
- `BleGattCredentialWorker.kt`의 healthy는 이전 세션 결과 기반이며 handsFreeReady는 기능/환경/등록 조건이다. 둘 다 최신 RF 수신을 보증하지 않는다. 현재 코드에는 위치 권한과 별개인 위치 서비스 스위치 상태의 진단 공백도 있다.

현재 Manifest는 neverForLocation을 사용하지 않는다. 따라서 그 옵션이 특정 beacon을 제외하는 현상을 이번 원인으로 지목할 근거는 없다. [Android 권한 문서](https://developer.android.com/develop/connectivity/bluetooth/bt-permissions)

## 후보별 판별 방법

| 후보 | 현재 판단 | 추가 판별 / 자동 수집 |
|---|---|---|
| Target 광고 payload 소실/설정 실패 | 우선 수정할 실제 복구 공백, 사건 인과는 미확정 | host sync/reset 세대·원인, set/start 결과, primary 길이·digest·적용 세대 |
| Android PendingIntent/필터 전달 정체 | 두 번 전면 복구 후에도 수신 없음 | 같은 BLE owner 안에서 유한 foreground ScanCallback 비교 |
| Target 식별 UUID/바이트 구성 불일치 | 과거 성공 때문에 상수의 영구 불일치 가능성은 낮음 | primary golden bytes와 실제 수신 target payload 비교 |
| OS 위치 서비스/권한/OEM 제한 | 일부 정상 상태만 확인됨 | 위치 서비스, 권한, 스캐너 오류, 화면·프로세스·서비스 상태 스냅샷 |
| 무선 간섭/출력/안테나/공존 | 배제 못 함 | 독립 수신기의 Target 패킷/RSSI/누락률, Wi-Fi 이벤트와 시간 상관 |
| MCU 전원 리셋/전체 정지 | 관측 중 동일 boot와 API 응답, 근거리 센서 응답 | 전기 안정성을 장기 보증하지는 않음; reset/uptime 계속 분리 |
| ACL·서명·MTU·GATT discovery | 이번 사건의 직접 실패 단계 아님 | GATT 연결이 시작된 뒤 별도로 분류 |
| 초음파 ARM_TIMEOUT | 이번 관측에서는 ARMED 자체가 없음 | 발견/인증 해결 뒤 센서 qualification 별도 검증 |

ESP32-C6는 Wi-Fi/BLE가 RF를 공유하므로 공존 영향은 후보이나, 둘을 함께 쓴다는 이유만으로 MQTT가 원인이라고 결론 내리거나 MQTT를 끄지 않는다. [Espressif 공존 문서](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32c6/api-guides/coexist.html)

## 권장 구현 순서

### P0 — 기존 기능의 실패 복구와 원인 판별부터

1. **Target 광고 상태 소유자를 하나로 통합.** primary와 scan response의 검증된 원본을 보관하고 모든 설정 반환값을 확인한다. host 재동기화 세대가 바뀌거나 설정 실패하면 두 데이터를 재적용하고 성공한 세대에서만 정상으로 표시한다. BLE 연결/OTA 중에는 안전하게 지연하고 main-loop 소유권, bounded retry/backoff를 유지한다. 라이브러리 캐시·콜백 경계가 필요한 경우 버전 고정된 어댑터/패치와 테스트를 함께 둔다.
2. **앱에 다른 판별 경로 추가.** 앱 전면/명시된 근접 실험에서 패킷이 없으면 기존 스캔과 소유권을 정리하고10–15초 LOW_LATENCY ScanCallback을 수행한다. 무필터 진단은 화면 ON·짧은 창으로 제한하며 다른 기기 MAC/이름/원문을 저장하지 않는다. 결과 후 background 등록을 복원한다. 상시 무필터 스캔이나 다중 소유자 경쟁으로 바꾸지 않는다.
3. **이미 알려진 Target 주소로 연결만 확인하는 진단.** 기존 AuthenticatedTargetLocatorStore/transport를 활용할 수 있다. 이 검사는 인증 proof/ARM/개방을 보내지 않으며 제한 시간과 사용자 근접 의도 조건을 갖춘다. 연결 성공+필터 수신 실패면 발견 경로로 범위를 좁힐 수 있다. 캐시 주소 자체는 상대의 암호학적 신원 증명이 아니다.
4. **오래된 정상 표시 제거.** 기능 사용 가능, 등록 요청 수락, 최근 패킷 관측, 인증 완료를 별도로 표시한다. 집 밖에서 패킷이 없는 정상 상황과 문앞 복구 실패를 구분한다. 실패 상태에서도 업로드 큐는 작동하고 최신 서버 receipt를 노출한다.
5. **자동 사건 묶음.** Target host/advertising 세대와 모바일 스캔 단계, GATT 진행 여부, Backend 수신 공백, 수동 개방 전후 증거를 동일 시간창으로 조회한다. NO_MATCHING_PACKET만 반복 저장하지 말고 어느 판별 단계까지 실행했는지와 결과를 남긴다. 원격 진단은 읽기 전용 조회와 비개방 검사 권한을 분리한다.

### P1 — 발견 프로토콜을 단순화

primary 광고에 **SGK 전용128-bit Service Data**로 버전/식별 힌트/readiness를 넣는 전환안을 권장한다. 현재 iBeacon manufacturer 필터와 별도 scan response 의존을 줄이는 설계다. GATT 인증 V2와 ACL 검증은 그대로 유지한다.

- legacy31-byte 예산을 실제 인코더로 검증한다. 예: flags3 + Service Data 헤더/UUID18 + payload8 =29bytes. 완전한128-bit UUID 목록까지 동시에 넣을 공간이 있다고 가정하지 않는다.
- Android 필터는 UUID 목록용 setServiceUuid가 아니라 실제 Service Data를 대상으로 구성한다.
- APK가 구/신 광고를 먼저 이해하도록 배포한 뒤 Target을 전환한다. 이는 발견 형식의 설치 순서이며 인증 V1 복귀가 아니다.
- 이 변경만으로 host 데이터 소실이나 OS 제한이 해결된다고 주장하지 않는다. P0 복구와 함께 검증한다.

### P2 — 기존 방식으로 장기 합격 못 하면 OS 연동/독립 관측 추가

Android 공식 선택지인 **CompanionDeviceManager + CompanionDeviceService**를 별도 실험으로 평가한다. OS가 연관 기기의 존재를 통해 앱 실행을 지원하는 경로이며 사용자 최초 연관 승인, 주소 정책, 대상 Android/OEM 호환성 확인이 필요하다. 기존 PendingIntent와 비교해 채택하고, 주기적 전체 스캔을 무한 재시작하는 대안으로 삼지 않는다. [Android background BLE 지침](https://developer.android.com/develop/connectivity/bluetooth/ble/background)

**문앞 독립 BLE 관측기**는 무선 송출과 휴대폰 문제를 원격으로 분리하는 가장 직접적인 추가 장치다. Target과 별도 수신기에서 SGK 패킷만 시간·식별 형식·RSSI·digest로 기록한다. Target이 정상이라고 보고해도 관측기가 못 받으면 송출/무선 쪽, 관측기는 받는데 폰이 못 받으면 폰 수신/필터 쪽으로 좁힐 수 있다. 관측기 자신이 offline인 경우와 거리에 따른 수신 차이는 별도 표시한다. 구매·설치는 이번 분석 범위가 아니다.

전용 키태그는 휴대폰 OS 의존을 줄일 수 있으나 추가 하드웨어와 별도 인증 설계가 필요하다. NFC 탭은 수동 대체 수단이지 hands-free 성공이 아니다. 휴대폰 광고/Target 스캔 역할 반전도 휴대폰의 background 광고 제한을 없애지는 않는다. GPS/Wi-Fi/FCM만으로 출입 권한이나 실제 문앞 존재를 판정하여 개방하지 않는다.

## 검증 및 완료 기준 (제안, 아직 합격 아님)

- 개발 검증: 광고 설정 실패, host reset/re-sync, active지만 데이터 미적용, OTA/연결 중 복구 지연을 fault injection으로 재현. primary golden bytes·31-byte 제한·실패 때 정상 표시 금지를 테스트한다.
- Android: 정확 필터/진단 callback 비교, 단일 BLE owner, 화면 OFF/ON, 프로세스 재생성, BT OFF/ON, 앱 업데이트, 위치 서비스 OFF의 명시적 원인 분류. 강제중지까지 무조건 자동 복구한다고 약속하지 않는다.
- 동일 사건에서 수신 없음→연결 없음→인증 미시작을 서버만으로 설명할 수 있어야 한다. 업로드 안 됨은 정상으로 덮지 않고 증거 신선도/연결 공백으로 표시한다.
- 실기기 잠정 목표: 등록된 가족 휴대폰 각각 정상 접근30회 중 인증 미시작0회, 접근 수신 후 ARMED p95 3초 이내; 장시간 화면 OFF 포함24시간 후72시간 관측. 이 표본이 영구 무고장을 증명하지는 않는다.
- 센서/릴레이 완료와 실제 문 개폐를 분리한다. 현재 독립 문접점이 없으므로 물리 개폐 자동 증명이 필요하면 센서 추가를 별도 결정한다.
- 소스 테스트, CI, Backend 배포, APK 설치, OTA VALID, 실제 hands-free 성공을 각각 기록한다. 관측 실패를 숨기거나 보안 검증을 약화하여 성공률을 높이지 않는다.

## 구현 진행 — 2026-09-14

- 사용자 승인으로 P0 구현과 배포를 진행한다. Target과 Android를 병렬 구현하며 Backend는 새 optional 진단을 먼저 수용하도록 확장한다. 이 절의 검증 상태는 배포 완료 기록 전까지 로컬 후보다.
- Target 후보는 primary/response 양쪽을 명시적 wire bytes로 재구성하고 checked apply를 수행한다. 별도 host reset callback을 임의로 덮어쓰지 않고30초 주기의 재적용으로 active-but-data-lost 경로를 보완한다. 연결/OTA 때문에 지연될 수 있으므로30초를 무조건 복구 SLA로 부르지 않는다.
- Android 후보는 전면에서12초 유한 대체 스캔을 수행하고 화면/Activity/BT/update/GATT 경계에서 종료·복원한다. 기존 iBeacon과 인증 V2는 유지한다. 알려진 주소에 대한 connect-only 진단과 primary Service Data 전환은 이번 배포에 포함하지 않는다. OS 연관 승인·추가 관측기는 후속 검증 선택지다.
- Backend는 `native.scan.alternative_*`, `native.location_services_enabled`, Target의 별도 `ble_advertisement` optional projection을 저장·조회한다. 구버전 immutable 보고서에는 새 NULL 필드를 주입하지 않는다. 이전 성공보다 최근의 명시적 NO_MATCHING_PACKET을 우선 분류하며, 단순 침묵을 사용자 도착 실패로 추론하지 않는다.
- 23:00KST 현장 관측 창을 종료하고 임시 heartbeat `sgk-2`만 PAUSED로 변경했다. 원래 전원 관측 `sgk`는 변경하지 않았다. 종료 기준 health16469/boot905/500/IDLE/relayOFF, 새 인증0; mobile1639는23:00:12 저장됨. 배포·개방·재부팅은 아직 수행하지 않았다.

## 관련 문서

- [MQTT 안정성 및 오늘 현장 관측](mqtt_stability_analysis_2026_09_14.md)
- [Android BLE wake ADR](android_ble_wake_adr.md)
- [모바일 스캔 생명주기](mobile_app_scan_lifecycle.md)
- [Android GATT worker](android_gatt_worker.md)
