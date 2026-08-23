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

> 관측 기준: H11 `main` commit `7a55a66`, 현장 실행본 H11 `2.1.242+main.g7a55a66`, plus weak-link STA compatibility candidate
>
> 이 문서는 **저장소 최신 구현**, **검증 증거**, **현장 배포 상태**를 분리해 보여 주는 시작점이다. 세부 계약은 링크된 문서와 코드를 따른다.

## 1. 한눈에 보기

| 축 | 저장소 최신 구현 | 검증/운영 경계 |
|---|---|---|
| Target | ESP32-C6, AJ-SR04T, GPIO3 relay, per-Target MQTTS, signed command/ACL, signed dual-slot OTA; manifest Ed25519는 bundled libsodium, encrypted content stream은 16-byte GCM block carry를 사용 | 현장 active는 exact-main H11 `2.1.242+main.g7a55a66`. 가까운 2.4 GHz AP에서는 Wi-Fi, MQTTS, signed OTA가 동작하지만 현관 AP는 Target scan 기준 약 `-80~-82 dBm`으로 association이 불안정하다. 본 변경은 all-channel/signal sort, no-sleep, STA-only 11b/g/n compatibility profile을 추가하지만 RF 매립 Gate는 실측 전까지 열려 있다 |
| Android | foreground scan, OS-managed BLE wake PoC, native GATT credential worker, recovery/update UI, bounded NAS APK publisher | H7 APK는 연결된 Samsung Android 16 기기에 exact-byte 설치/실행 확인. H11부터 NAS publisher의 object bound, prefetch, idle/job timeout이 적용되며 최신 NAS/설치 증거는 별도 기록 |
| Backend | FastAPI/MariaDB, enrollment/ACL, admin session/RBAC/CSRF/re-auth, signed commands, operations APIs | production Compose와 migration 계약은 존재하지만 live NAS 운영 증거는 별도 관리 |
| Access | legacy iBeacon → pre-arm과 default-OFF local GATT 경로가 공존 | Target FSM `IDLE → ARMED → RELAY_HOLD → COOLDOWN → IDLE`이 relay 권한의 최종 경계 |
| OTA | Target periodic HTTPS pull, signed manifest/artifact, inactive slot, health mark/rollback, authenticated local recovery; mobile signed update/recovery 계약 | H10 encrypted artifact는 H9에서 signed manifest 수락, 전체 download, inactive image 검증과 H10 reboot까지 PASS했고 H11 exact-main도 현재 실행 중이다. 다만 retained bootloader/OTA data에서 `PENDING_VERIFY` health-window/valid-mark 로그가 관측되지 않아 rollback Gate는 닫지 않는다 |
| Home Assistant | 15개 read-only MQTT discovery entity와 fail-closed legacy command tombstone migration | broker retained config 15개를 검증했고 H11 hotspot online 때 firmware/IP/RSSI/state/config가 live로 갱신됐다. 과거 control registry 항목은 `restored/unavailable`로 남으며 signed command bridge 없이 재활성화하지 않는다 |

## 2. 저장소 구현과 현장 배포를 혼동하지 않는다

2026-08-12의 구형 매립본은 더 이상 현재 상태가 아니다. 2026-08-24에 GCM block carry를 포함한 exact-main H9를 app-only USB로 설치하면서 bootloader, partition table, NVS, OTA data와 fallback slot을 보존했다. H9는 가까운 2.4 GHz AP에서 verified MQTTS를 복구한 뒤 exact H10 signed manifest를 수락하고 1,796,116-byte encrypted artifact를 inactive slot에 기록·검증하여 H10으로 재부팅했다. 이후 exact H11 `7a55a667b9d30f7929176997010d7ab71abaf833`, version `2.1.242+main.g7a55a66`가 현장 active로 확인됐고 같은 AP에서 IP `10.71.25.196`, exact per-Target MQTTS subscriptions와 OTA `already current`를 기록했다.

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

Hardwareless RC는 Android Keystore 자격과 connectable GATT proof를 사용해 Target-local FSM으로 연결되는 별도 경로다. 소프트웨어 코어가 구현되어 있어도 기본 빌드는 `ENABLE_HARDWARELESS_RC=0`이며, production에서 자동 활성화되지 않는다.

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
