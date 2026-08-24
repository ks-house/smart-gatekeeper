---
title: smart-gatekeeper current project status
type: reference
project: smart-gatekeeper
status: active
updated: 2026-08-25
source_of_truth: true
applies_to:
  - firmware
  - android
  - backend
  - operations
---

# 현재 프로젝트 상태

> 관측 기준: exact main `db37bc2390efbf94bf1a9fca261834c3728606b5`, NAS/OTA Target `2.1.262+main.gdb37bc2`, 연결된 Samsung phone `1.0.0-gdb37bc2` (`versionCode=19001`), live NAS Backend/HA bridge와 2026-08-25 foreground manual GATT proof/result
>
> 이 문서는 **저장소 최신 구현**, **검증 증거**, **현장 배포 상태**를 분리해 보여 주는 시작점이다. 세부 계약은 링크된 문서와 코드를 따른다.

## 1. 한눈에 보기

| 축 | 저장소 최신 구현 | 검증/운영 경계 |
|---|---|---|
| Target | ESP32-C6, AJ-SR04T, GPIO3 relay, per-Target MQTTS, signed command/ACL, signed dual-slot OTA. 개인 설치 전용 `esp32c6_personal_production`은 valid door/ACL trust 뒤 Hardwareless를 compile/runtime ON하고, default/commercial profile은 OFF를 유지 | run `32777471683`의 exact-main image `2.1.262+main.gdb37bc2`가 NAS에 원자적으로 게시되고 HA signed OTA로 설치·재부팅됐다. Target은 `192.168.35.19`, MQTTS, ACL v30 이상과 connectable GATT를 복원했다. 같은 실행본이 Android proof/result를 정상 완료했고 관측 구간에서 reset하지 않았다. 별도 relay 전기·sensor·rollback Gate는 열려 있다 |
| Android | foreground scan, OS-managed BLE wake, native GATT credential worker, AndroidKeyStore public enrollment, native-authoritative consent/ownership, recovery/update UI, bounded NAS APK publisher | run `32777471718`의 production-signed `1.0.0-gdb37bc2` / 19001을 `adb install -r`로 설치해 기존 데이터와 Keystore enrollment를 보존했다. Hardwareless는 `local_keystore_authenticated`, BLE owner는 `native_gatt`이며 수동 요청은 4,599 ms에 성공했다. `NATIVE_GATT_DISABLED`와 이전 `MALFORMED_PROOF` blocker는 이 foreground run에서 해소됐다; Samsung screen-off/process-killed 반복은 별도 Gate다 |
| Backend | FastAPI/MariaDB, enrollment/ACL, personal public-key bootstrap, exact Target ACL apply correlation, signed HA command bridge, admin session/RBAC/CSRF/re-auth, operations APIs | live API는 `/live=200`이고 Target telemetry/HA bridge controls는 정상이다. `/ready=503`의 유일한 항목은 개인 fallback용 `legacy_prearm_retired=false`이며 HA availability 실패가 아니다. live `build_sha`는 아직 `7c2764a...`를 보고하므로 exact-main Backend rollout은 별도 운영 작업이다; legacy flag만 꺼서 200을 만들면 Android fallback을 끊으므로 하지 않는다 |
| Access | legacy iBeacon → pre-arm, personal native local GATT, signed Backend/MQTT remote command가 상호 구분됨 | Target와 Android Hardwareless 경로는 모두 ON이고 exact ACL이 적용됐다. 실기기 수동 요청은 GATT connect/service/CCCD, multi-frame proof와 authenticated result까지 완료됐으며 worker health는 `HEALTHY`, failure reason 없음, 4,599 ms였다. HA 활동 이력도 같은 세션의 `AUTH_PENDING` 06:27:33, `ARMED` 06:27:36, `IDLE` 06:28:35를 기록했다. sensor 감지와 GPIO3 relay 동작은 이 관측에서 별도로 확인하지 않았다 |
| OTA | Target periodic HTTPS pull, signed manifest/artifact, inactive slot, health mark/rollback, authenticated local recovery; mobile signed update/recovery 계약 | 최종 exact-main Target와 Android artifact가 각각 runs `32777471683`, `32777471718`에서 NAS primary/fallback에 게시·readback됐다. 1,845,920-byte Target image는 7,340,032-byte slot의 25.15%이며 5,494,112 bytes를 남긴다. Target install→reboot→exact version과 Android same-signature install은 확인했다; bootloader rollback/power-loss Gate는 계속 열어 둔다 |
| Home Assistant | 15개 read-only entity에 더해 Backend ingress→fresh boot/status→서명된 per-Target command bridge 기반 reboot/OTA/config control을 구현. `manual_remote`는 별도 opt-in | live bridge availability가 online이고 reboot/open/OTA 및 네 config slider가 enabled다. HA OTA 버튼으로 최종 `2.1.262+main.gdb37bc2` 설치·재부팅까지 완료했다. 원격 open은 안전상 호출하지 않았으므로 signed relay actuation은 별도 관측으로 남는다 |

## 2. 저장소 구현과 현장 배포를 혼동하지 않는다

2026-08-12의 구형 매립본은 더 이상 현재 상태가 아니다. 2026-08-24의 NVS-preserving USB bootstrap과 여러 signed inactive-slot OTA를 거쳐, 2026-08-25 HA의 signed OTA control이 run `32777471683`의 exact main `db37bc2390efbf94bf1a9fca261834c3728606b5`를 설치했다. Target은 `2.1.262+main.gdb37bc2`로 재부팅하고 저장된 Wi-Fi에서 `192.168.35.19`, exact per-Target MQTTS, production ACL과 connectable GATT service를 복원했다. 정기 OTA 확인도 해당 버전을 current로 판정했다.

연결된 Samsung phone에는 run `32777471718`의 production-signed `1.0.0-gdb37bc2` / 19001을 replacement install했고 앱 데이터와 native credential을 보존했다. 이 최종 APK와 Target에는 앞서 실기기에서 발견한 NimBLE callback-stack overflow와 Challenge read/indication 경합 수정이 함께 포함됐다. foreground 수동 요청에서 Android Bluetooth 로그는 connect, service discovery, 세 CCCD 설정, 다중 characteristic write와 clean disconnect를 기록했고 WorkManager는 성공 종료했다. 다시 연 health projection은 `HEALTHY`, failure/Target wire reason 없음, latency 4,599 ms였다. HA 활동 이력은 같은 시간대의 Target FSM을 `AUTH_PENDING → ARMED → IDLE`로 독립 관측했다. 관측 중 Target reset은 없었지만 sensor/relay 동작은 별도로 측정하지 않았다. 현재 lifecycle callback은 FSM의 bool 반환을 Result 생성에 다시 결합하지 않으므로, non-IDLE 거부를 positive Result로 오인하지 않게 만드는 fail-closed 하드닝은 후속 소스 Gate다.

Wi-Fi 자격 증명 자체는 Android가 동일 2.4 GHz SSID에 새로 인증해 검증했다. 그러나 Target이 본 현관 AP 신호는 약 `-80~-82 dBm`이었고 reason 2/4/201이 반복됐다. 같은 H11과 같은 저장 경로가 가까운 hotspot `-42 dBm`에서는 즉시 성공했으므로 현재 지배적 원인은 RF margin이다. 코드 호환 프로파일은 AP 선택과 association 안정성을 개선할 수 있지만 `-81 dBm` link budget을 만들 수는 없다. 최종 매립은 최소 `-75 dBm`, 가능하면 `-67 dBm` 이상을 확보하고 반복 부팅/장애 복구를 통과한 뒤 승인한다.

- 저장소 최신 구현: 이 문서와 [최신 코드 감사](current_code_audit.md)
- 개인 현장 배포: [개인 PROD 사건 기록](personal_prod_incident_2026_08_12.md)
- 상용 출시 Gate: [commercial_release_program.md](commercial_release_program.md)
- 개인 축소 Gate: [personal_production_profile.md](personal_production_profile.md)

## 3. 현재 기준 아키텍처

정상 원격 pre-arm은 다음 경로를 사용한다.

```text
Target iBeacon
  → Android foreground scanner
  → HTTPS /api/v1/door/prearm
  → approved tenant/device lookup
  → boot-bound signed command over per-Target MQTTS
  → Target command verification
  → TargetAccessFsm ARMED
  → AJ-SR04T valid distance
  → GPIO3 relay
```

Hardwareless RC는 AndroidKeyStore 자격과 connectable GATT proof를 사용해 Target-local FSM으로 연결되는 별도 경로다. 기본 개발 및 commercial production 빌드는 `ENABLE_HARDWARELESS_RC=0`을 유지한다. 단일 설치용 `esp32c6_personal_production`만 compile-ON이며, valid Target identity/ACL trust에 따른 일회성 NVS migration과 이후 `false` kill switch를 적용한다. 모바일은 명시적 enrollment가 exact Target ACL applied ACK까지 확인된 뒤에만 native ownership을 ON한다.

## 4. 현재 신뢰 경계

- MQTT 연결은 Root CA, non-1883 port, Target별 principal과 exact topic namespace가 모두 provisioned되지 않으면 command plane을 닫는다.
- Target command는 target/tenant/door/boot/session/nonce/time/key에 묶인 서명을 검증하고 replay를 거부한다.
- 관리자 경로는 구성된 mTLS trusted proxy 또는 개인 관리자 세션을 사용하며, unsafe 요청은 CSRF와 역할/tenant scope, 중요 작업은 fresh re-auth를 요구한다.
- force-open은 상용 경로에서 제안자와 다른 승인자를 요구하고 publication reconciliation 상태를 영속화한다.
- `mqtt_published=true` 또는 QoS 1 PUBACK은 broker 수락 증거이며 Target 실행 증거가 아니다.
- BLE 탐지, API 성공, MQTT 수락, Target command ACK, FSM 상태, sensor, relay 결과는 서로 다른 증거 단계다.

## 5. 열려 있는 주요 Gate

1. 현장 bootloader/OTA data가 새 OTA image를 `PENDING_VERIFY`로 표시하고 firmware가 30초 health window 뒤 valid mark하는지, 실패 시 이전 slot으로 rollback하는지 별도 확인한다. install/reboot/current-version만으로 이 Gate를 닫지 않는다.
2. 약신호 compatibility release를 동일 위치에서 홈 AP와 가까운 AP로 A/B하고, 홈 위치 RSSI를 최소 `-75 dBm` 이상으로 개선한 뒤 Wi-Fi/DHCP/MQTTS와 broker/WAN 장애 자동 복구를 실측한다.
3. GPIO3 Active-LOW relay, High-Z OFF, ECHO 5 V 보호, 전원 강하와 반복 구동을 물리 검증한다.
4. Samsung/OEM 화면 OFF, Activity 종료, OS background 제한을 release artifact로 반복 검증한다.
5. Personal Hardwareless RC의 compile/runtime enable, exact-main Target signed OTA, same-signature APK install, Backend enrollment/exact ACL, foreground challenge/proof/result 성공까지 관측했다. 남은 모바일 Gate는 Samsung/OEM screen-off, Activity/process-killed, reboot 후 자동 wake 반복과 latency 분포다. Commercial/default compile-OFF, local kill switch와 legacy recovery는 보존한다.
6. Target/Android production artifact의 NAS 게시와 readback은 완료됐다. live Backend의 exact-main image 갱신, reverse proxy, backup/restore와 operator acceptance는 소프트웨어 계약과 별개의 운영 증거로 남긴다.

## 6. 문서 읽기 순서

| 질문 | 먼저 읽을 문서 |
|---|---|
| 현재 코드가 무엇을 구현했는가 | [current_code_audit.md](current_code_audit.md) |
| 현재 시스템 흐름 | [architecture.md](architecture.md) |
| 실제 매립 Target 상태 | [personal_prod_incident_2026_08_12.md](personal_prod_incident_2026_08_12.md) |
| Target 연결/복구 | [embedded_target_connectivity_policy.md](embedded_target_connectivity_policy.md) |
| OTA 완료 기준 | [ota_reliability_contract.md](ota_reliability_contract.md) |
| 모바일 background 문제 | [mobile_app_background_audit.md](mobile_app_background_audit.md) |
| 핀과 전기 안전 | [pin_mapping.md](pin_mapping.md) |
| 검증 결과 | [hardware_test.md](hardware_test.md) |
