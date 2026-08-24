---
title: smart-gatekeeper current project status
type: reference
project: smart-gatekeeper
status: active
updated: 2026-08-24
source_of_truth: true
applies_to:
  - firmware
  - android
  - backend
  - operations
---

# 현재 프로젝트 상태

> 관측 기준: 변경 전 현장 Target `2.1.251+main.gaf779e1`, 연결된 phone `1.0.0-gaf779e1` (`versionCode=17501`), plus 아직 배포하지 않은 personal GATT/HA signed-bridge candidate
>
> 이 문서는 **저장소 최신 구현**, **검증 증거**, **현장 배포 상태**를 분리해 보여 주는 시작점이다. 세부 계약은 링크된 문서와 코드를 따른다.

## 1. 한눈에 보기

| 축 | 저장소 최신 구현 | 검증/운영 경계 |
|---|---|---|
| Target | ESP32-C6, AJ-SR04T, GPIO3 relay, per-Target MQTTS, signed command/ACL, signed dual-slot OTA. 개인 설치 전용 `esp32c6_personal_production`은 valid door/ACL trust 뒤 Hardwareless를 compile/runtime ON하고, default/commercial profile은 OFF를 유지 | 변경 전 현장 active는 `2.1.251+main.gaf779e1`이며 Wi-Fi/MQTTS/주기 OTA current 확인까지 존재한다. 새 personal image는 build/test만 완료됐고 아직 Target install/reboot/GATT/ACL lease/health가 확인되지 않았다 |
| Android | foreground scan, OS-managed BLE wake, native GATT credential worker, AndroidKeyStore public enrollment, native-authoritative consent/ownership, recovery/update UI, bounded NAS APK publisher | 새 소스는 analyze와 Flutter 35/35 및 native GATT Gradle suite를 통과했다. 연결된 phone에는 기존 production-signed `1.0.0-gaf779e1`가 남아 있으며 동일 서명 CI APK의 `install -r`, enrollment, Target GATT는 pending |
| Backend | FastAPI/MariaDB, enrollment/ACL, personal public-key bootstrap, exact Target ACL apply correlation, signed HA command bridge, admin session/RBAC/CSRF/re-auth, operations APIs | source/unit 계약과 backup-first migration 구성이 존재하지만 새 Backend의 live NAS rebuild/migration/readiness, ACL renewal 및 bridge operation은 아직 확인하지 않았다 |
| Access | legacy iBeacon → pre-arm, personal native local GATT, signed Backend/MQTT remote command가 상호 구분됨 | 개인 profile은 ON 후보지만 앱 public enrollment→exact Target ACL apply→native ON→GATT proof가 모두 성공해야 한다. Target FSM `IDLE → ARMED → RELAY_HOLD → COOLDOWN → IDLE`이 relay 권한의 최종 경계 |
| OTA | Target periodic HTTPS pull, signed manifest/artifact, inactive slot, health mark/rollback, authenticated local recovery; mobile signed update/recovery 계약 | H10 encrypted artifact는 H9에서 signed manifest 수락, 전체 download, inactive image 검증과 H10 reboot까지 PASS했고 H11 exact-main도 현재 실행 중이다. 다만 retained bootloader/OTA data에서 `PENDING_VERIFY` health-window/valid-mark 로그가 관측되지 않아 rollback Gate는 닫지 않는다 |
| Home Assistant | 15개 read-only entity에 더해 Backend ingress→fresh boot/status→서명된 per-Target command bridge 기반 reboot/OTA/config control을 구현. `manual_remote`는 별도 opt-in | 변경 전 live HA에서는 read-only 15/15만 가용했다. 새 discovery retained publish, Backend availability, 실제 제어 결과/ACK는 NAS와 HA에 아직 배포·확인하지 않았다 |

## 2. 저장소 구현과 현장 배포를 혼동하지 않는다

2026-08-12의 구형 매립본은 더 이상 현재 상태가 아니다. 2026-08-24에 GCM block carry를 포함한 exact-main H9를 app-only USB로 설치하면서 bootloader, partition table, NVS, OTA data와 fallback slot을 보존했다. H9는 가까운 2.4 GHz AP에서 verified MQTTS를 복구한 뒤 exact H10 signed manifest를 수락하고 1,796,116-byte encrypted artifact를 inactive slot에 기록·검증하여 H10으로 재부팅했다. 이후 H11을 거쳐 변경 직전 exact-main `2.1.251+main.gaf779e1`가 저장된 Fold7 hotspot에서 Wi-Fi, exact per-Target MQTTS, retained boot/config 및 periodic OTA `already current`를 기록했다. 이 실행본은 Hardwareless door/ACL signer가 없어서 GATT를 fail-closed한 이전 세대이며, 현재 personal GATT 후보의 배포 증거가 아니다.

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
5. Personal Hardwareless RC는 source/profile enable과 실제 활성 증거를 분리한다. exact-main Target install, same-signature APK install, Backend enrollment, exact ACL apply, reboot/lease refresh, screen-off GATT와 G0-HW/RELAY/OTA physical Gate를 별도로 닫는다. Commercial/default compile-OFF와 local kill switch를 보존한다.
6. production NAS 배포, reverse proxy, backup/restore와 operator acceptance는 소프트웨어 계약과 별개의 운영 증거로 남긴다.

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
