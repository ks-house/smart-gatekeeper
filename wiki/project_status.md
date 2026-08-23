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

> 관측 기준: H7 `main` commit `e00ebe8`, 현장 실행본 H6 `02090c3`, plus ESP32-C6 GCM block-alignment correction candidate
>
> 이 문서는 **저장소 최신 구현**, **검증 증거**, **현장 배포 상태**를 분리해 보여 주는 시작점이다. 세부 계약은 링크된 문서와 코드를 따른다.

## 1. 한눈에 보기

| 축 | 저장소 최신 구현 | 검증/운영 경계 |
|---|---|---|
| Target | ESP32-C6, AJ-SR04T, GPIO3 relay, per-Target MQTTS, signed command/ACL, signed dual-slot OTA; manifest Ed25519는 bundled libsodium, encrypted content stream은 16-byte GCM block carry를 사용 | 현장 active는 exact-main `2.1.237+main.g02090c3` H6. H7 manifest는 수락됐지만 pinned ESP-IDF GCM ALT의 비정렬 multipart 결함으로 inactive `app1` 검증이 fail-closed 중단됐으며 corrected merged-main USB bootstrap과 다음 OTA가 필요 |
| Android | foreground scan, OS-managed BLE wake PoC, native GATT credential worker, recovery/update UI | Hardwareless RC는 default-OFF; Samsung/OEM 및 force-stop 경계는 실기기 Gate |
| Backend | FastAPI/MariaDB, enrollment/ACL, admin session/RBAC/CSRF/re-auth, signed commands, operations APIs | production Compose와 migration 계약은 존재하지만 live NAS 운영 증거는 별도 관리 |
| Access | legacy iBeacon → pre-arm과 default-OFF local GATT 경로가 공존 | Target FSM `IDLE → ARMED → RELAY_HOLD → COOLDOWN → IDLE`이 relay 권한의 최종 경계 |
| OTA | Target periodic HTTPS pull, signed manifest/artifact, inactive slot, health mark/rollback, authenticated local recovery; mobile signed update/recovery 계약 | H7 CI/NAS/서명/복호화와 Target manifest 수락은 PASS. 세 번의 physical download는 모두 동일 GCM chunk boundary에서 inactive slot hash/tag 검증으로 중단됐고 active H6/NVS는 보존됨. corrected image의 USB bootstrap → strictly newer OTA → reboot/health-valid가 완료 조건 |

## 2. 저장소 구현과 현장 배포를 혼동하지 않는다

2026-08-12에 관측한 현관 매립 Target `2.1.0-g75b946a`는 이제 현재 상태가 아니다. 2026-08-24 연결된 Target에는 bundled-libsodium verifier를 포함한 exact-main H6 `2.1.237+main.g02090c3`를 app-only USB 방식으로 설치했다. NVS를 지우지 않았고 저장된 Wi-Fi로 `192.168.35.19`를 받은 뒤 verified MQTTS와 Home Assistant read-only telemetry를 복구했다.

Strictly newer H7 `2.1.238+main.ge00ebe8`은 run `32662983244`에서 production build, Ed25519, AES-256-GCM, NAS atomic publish/readback과 16 MB N16 image 검증을 통과했다. H6는 그 manifest를 수락하고 1,795,284-byte encrypted artifact를 세 번 모두 끝까지 처리했지만 `image write/hash`로 중단했다. 실패한 `app1`을 read-only 회수한 결과 두 번 모두 plaintext offset `0..3804`는 정확하고 `3805 (mod 16 = 13)`부터 결정적으로 달랐다. pinned ESP-IDF 5.5.4 GCM ALT가 비정렬 multipart update의 CTR/GHASH 상태를 보존하지 않는 결함과 정확히 일치하며, active H6와 NVS는 fail-closed 보존됐다. 현재 후보는 0..15-byte ciphertext carry로 모든 non-final GCM update를 16-byte aligned로 제한한다. 이 수정은 build/host contract와 다음 physical USB→OTA 연속 검증 전까지 완료로 간주하지 않는다.

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

Hardwareless RC는 Android Keystore 자격과 connectable GATT proof를 사용해 Target-local FSM으로 연결되는 별도 경로다. 소프트웨어 코어가 구현되어 있어도 기본 빌드는 `ENABLE_HARDWARELESS_RC=0`이며, production에서 자동 활성화되지 않는다.

## 4. 현재 신뢰 경계

- MQTT 연결은 Root CA, non-1883 port, Target별 principal과 exact topic namespace가 모두 provisioned되지 않으면 command plane을 닫는다.
- Target command는 target/tenant/door/boot/session/nonce/time/key에 묶인 서명을 검증하고 replay를 거부한다.
- 관리자 경로는 구성된 mTLS trusted proxy 또는 개인 관리자 세션을 사용하며, unsafe 요청은 CSRF와 역할/tenant scope, 중요 작업은 fresh re-auth를 요구한다.
- force-open은 상용 경로에서 제안자와 다른 승인자를 요구하고 publication reconciliation 상태를 영속화한다.
- `mqtt_published=true` 또는 QoS 1 PUBACK은 broker 수락 증거이며 Target 실행 증거가 아니다.
- BLE 탐지, API 성공, MQTT 수락, Target command ACK, FSM 상태, sensor, relay 결과는 서로 다른 증거 단계다.

## 5. 열려 있는 주요 Gate

1. GCM block-alignment correction이 포함된 exact merged-main을 NVS 보존 app-only USB로 설치한 뒤, strictly newer exact-main을 periodic HTTPS로 inactive slot에 설치하여 reboot/version/boot ID/health-valid를 확인한다. H7의 manifest 수락과 fail-closed active-slot 보존만으로 이 Gate는 닫히지 않는다.
2. Wi-Fi 부팅 실패, DHCP/IP 상실, broker/WAN 장애에서 자동 복구와 15초/90초/10분 관측 경계를 실측한다.
3. GPIO3 Active-LOW relay, High-Z OFF, ECHO 5 V 보호, 전원 강하와 반복 구동을 물리 검증한다.
4. Samsung/OEM 화면 OFF, Activity 종료, OS background 제한을 release artifact로 반복 검증한다.
5. Hardwareless RC를 유지하려면 default-OFF를 보존하고 G0-HW/RELAY/OTA physical Gate를 별도로 닫는다.
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
