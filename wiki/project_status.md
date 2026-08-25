---
title: smart-gatekeeper current project status
type: reference
project: smart-gatekeeper
status: active
updated: 2026-08-26
source_of_truth: true
applies_to:
  - firmware
  - android
  - backend
  - operations
---

# 현재 프로젝트 상태

> 관측 기준: 저장소/Target exact main `493591bb482756c6713240387d7c68d319bba439` / `2.1.273+main.g493591b`, Android `1.0.0-g848bbf1` (`versionCode=20201`), durable NVS/HA reboot/OTA/remote-open 실기기 성공, 수동 action-2 반복 성공, 그리고 issue #156 screen-off action-1 결과 분류 대기
>
> 이 문서는 **저장소 최신 구현**, **검증 증거**, **현장 배포 상태**를 분리해 보여 주는 시작점이다. 세부 계약은 링크된 문서와 코드를 따른다.

## 2026-08-26 final-main 493 durable-NVS and connected control validation

- Final push run `32895175240` built and published exact main `493591bb` as
  `2.1.273+main.g493591b`. Before recovery installation, the live NAS manifest,
  immutable encrypted artifact and authenticated plaintext were checked at
  `1,849,044` bytes / SHA-256 `31480801...684e4d8a` and `1,849,008` bytes /
  SHA-256 `b734ee43...1228a9a8`, respectively.
- The old 848 command ledger was already full, so even the signed HA OTA
  request failed before reaching the OTA effect. COM5 was therefore used as a
  bounded recovery path: bootloader, the reviewed 16 MiB partition table,
  `boot_app0` and the exact authenticated CI application were written at their
  standard offsets without erasing the Wi-Fi/config NVS.
- The recovered Target booted exact 493, restored Wi-Fi `192.168.35.19`, MQTTS
  and GATT, and initialized `sgkstate` with `used=0 free=60480 total=60480`.
  Signed retained ACLs v169--v171 then wrote successfully with no further
  `NOT_ENOUGH_SPACE` error.
- Two signed HA reboots succeeded. Durable usage survived the first reboot and
  advanced from 179 to 195 entries by the second, proving that signed-command
  replay writes now persist instead of failing at `ledger_b`. A signed HA OTA
  request also reached `[OTA] forced update check started` and returned
  `already current: 2.1.273+main.g493591b`. HA remote open produced one
  relay-command ON/OFF sequence without reset.
- Three Samsung screen-off first-match trials were delivered with
  `screen_interactive=false`, RSSI -50/-52. Native WorkManager connected,
  discovered services, enabled the three indication characteristics and wrote
  all framed proof chunks, then disconnected. Target accepted all three BLE links,
  but no action-1 `ARMED` trace followed. No NVS/ACL/replay error accompanied
  these attempts. The third trial completed before the later periodic OTA check,
  excluding OTA-busy collision. Issue #149 storage acceptance is complete and
  closed; issue #156 separately tracks the missing terminal action-1 result.
  The app's durable result/reason still requires an unlocked health-screen read
  before selecting the smallest responsible runtime layer.
- There is no AJ-SR04T/contact fixture in the current board-only setup.
  Ultrasonic threshold-to-relay, electrical contact, pending-image valid mark,
  rollback and wall-install acceptance remain open evidence Gates.

## 2026-08-26 exact-main 848 connected acceptance and issue #149

- Target run `32888032443` built, signed, encrypted and NAS-published exact
  main `848bbf16`; periodic signed HTTPS OTA installed
  `2.1.270+main.g848bbf1`. Wi-Fi `192.168.35.19`, per-Target MQTTS,
  connectable GATT and ACL delivery returned after reboot. The retained OTA
  path did not expose a `PENDING_VERIFY`/valid-mark trace, so rollback health
  remains a separate open Gate.
- Android run `32888032174` published the production-signed exact-main APK.
  SHA-256 was `016e62c5d0fe834f42a06e6651442860a62e06f3798fcaaff4781a8a92c379d4`;
  `adb install -r` installed `1.0.0-g848bbf1` / 20201 while preserving app
  data, first-install identity and AndroidKeyStore state.
- The main mobile open button completed action 2 four times across the prior
  and exact 848 APKs. Each Target trace reached authenticated GATT acceptance,
  relay-command ON, timer-bound OFF and terminal mobile success without reset;
  observed UI completion was about 4.5--5.2 seconds. This is a board/GPIO
  command result, not relay contact voltage or door mechanics evidence.
- A true screen-off first-match attempt reached the Android background worker
  and Target GATT connection, but no action-1 `ARMED` result followed. Target
  serial emitted `ledger_b NOT_ENOUGH_SPACE`; earlier ACL writes had also
  emitted `slot_0 NOT_ENOUGH_SPACE`. Issue #149 therefore blocks the pocket
  acceptance test until durable ACL/replay writes are restored and the exact
  merged image is redeployed.
- The issue #149 candidate leaves both 7 MiB OTA slots and offsets unchanged,
  keeps Wi-Fi/config in the original 20 KiB NVS, and moves ACL snapshots,
  command replay ledgers and the offline event queue to the unused 1.875 MiB
  data region. Existing application-only OTA installations discover the legacy
  `spiffs` label; new full flashes declare the same region as `sgkstate` NVS.
  Reads fall back to legacy NVS and no automatic erase is allowed.

## 2026-08-26 connected b6 acceptance와 issue #143

- runs `32881540989` / `32881541103`의 exact b6 Target/APK를 각각 signed
  periodic HTTPS OTA와 same-signature `adb install -r`로 설치했다. Target은
  Wi-Fi `192.168.35.19`, MQTTS, GATT와 ACL v159를 복원했고 Android 앱 데이터와
  AndroidKeyStore credential은 보존됐다.
- 메인 `문 열기` action 2는 GATT 연결·service discovery·indication enable까지 진행했지만
  proof 처리 중 Target이 `abort()`로 재부팅했다. `RELAY_HOLD`, relay ON/OFF와 terminal
  Result OK는 발생하지 않았고 앱은 `PROOF_OUTCOME_UNCERTAIN`을 표시했다. 요구사항 1은
  현재 FAIL이며 issue #143이 release blocker다.
- production-equivalent ELF는 `GattServer::update()`가 `core_mux` critical section 안에서
  `ProtocolCore::processProof()`를 실행하고, 동기 Result-to-FSM commit이
  `TargetAccessFsm::handleLocalManualOpen()` → relay callback → `LOGF`에 도달하면서
  newlib stdout recursive-lock assert를 일으킨 경로를 가리켰다.
- issue #143 후보는 adapter/core 직렬화를 recursive task mutex로 바꿔 GPIO, failsafe timer,
  diagnostics와 logging을 critical section 밖 task context에서 실행한다. focused 16/16과
  personal-production ESP32-C6 build(1,781,874/7,340,032 bytes)는 통과했다. 아직 merge,
  exact CI/NAS 재게시, Target OTA와 action-2 재시험 전이므로 수정 완료로 판정하지 않는다.

## 2026-08-26 PR #132 증거 복구와 현재 경계

- PR #132에만 남아 있던 2026-08-25 실기기 증거를 issue #141에서 역사적 사실로 복구했다.
  exact main `db37bc2`의 Target `2.1.262+main.gdb37bc2`와 Android
  `1.0.0-gdb37bc2` / 19001은 각각 runs `32777471683`, `32777471718`에서
  빌드·게시·설치됐다. 한 foreground local GATT 세션은 `HEALTHY`, failure/Target denial 없음,
  4,599 ms를 기록했고 HA는 `AUTH_PENDING` 06:27:33 → `ARMED` 06:27:36 →
  `IDLE` 06:28:35를 독립 관측했다. Target reset은 없었다.
- 이 세션은 당시 action 1의 authenticated proof/result와 FSM ARM 증거다. 이후 issue #133에서
  수동 버튼을 action 2 즉시 relay 경로로 분리하고 Result를 실제 FSM 전이에 결합했으므로,
  과거 성공을 현재 수동 버튼-to-relay 성공으로 해석하지 않는다.
- 현재 exact main `a9b68222`의 firmware는 signed OTA로 Target에 설치되어 Wi-Fi
  `192.168.35.19`, MQTTS, ACL v147과 GATT를 복원했고 이후 OTA 확인에서 current로 판정됐다.
  같은 main의 APK는 NAS에 게시됐지만 phone이 연결되지 않아 설치하지 않았다. 따라서 현재
  action 2 버튼, screen-off/pocket action 1, AJ-SR04T와 GPIO3 접점 결과는 여전히 미검증이다.

## 2026-08-26 issue #134 pocket-approach 후보

- 개인 native GATT enable은 같은 native 호출에서 exact `PendingIntent` wake 등록을 시도하고,
  disable은 등록을 중지한다. live 권한/Bluetooth 상태와 `handsFreeReady`를 별도로 노출한다.
- Android 12+의 첫 presence WorkManager 작업은 expedited이고 quota 부족 시 일반 작업으로 안전하게 강등된다.
  Android 8~11은 새 foreground-service 계약을 요구하지 않도록 기존 일반 작업을 유지한다.
  retry는 설정된 지연을 지키며, 45초를 넘긴 stale presence는 proof 전에
  `PRESENCE_EXPIRED`로 종료한다.
- action 1 성공은 실제 Target `ARMED` 전이 뒤에만 반환되므로 presence→dispatch와
  presence→ARMED 시간을 분리 기록한다. Target은 ARMED 동안 100 ms 간격으로만 초음파를 읽고
  유효 설정 거리 안에서만 relay를 켠다.
- source/native-host 집중 테스트 36개가 통과했다. 현재 phone, AJ-SR04T와 physical relay가
  연결되지 않았으므로 screen-off/pocket 성공률, 실제 sensor-to-contact latency는 미검증이다.

## 2026-08-26 issue #133 merged software path

- 수동 앱 버튼과 background presence가 더 이상 같은 의미를 공유하지 않는다. 수동 버튼은 signed
  local GATT action 2를 foreground에서 즉시 실행하고 Target terminal result를 기다리며, presence
  worker는 action 1을 명시적으로 사용해 `ARMED`까지만 전환한다.
- Target protocol은 `AuthControlGate`로 proof와 FSM을 결합한다. action 1은
  `AUTH_PENDING → ARMED`, action 2는 `AUTH_PENDING → RELAY_HOLD`이며 실제 전이가 성공한 뒤에만
  `RESULT OK`를 생성한다.
- native C++/source suite 11/11과 `esp32c6_personal_production` build가 통과했다. firmware는
  1,780,836/7,340,032 bytes(24.3%), RAM 67,088/327,680 bytes(20.5%)다.
- PR #135는 Android, Target, OTA, protocol과 Trusted CI 통과 후 main `737d3243`으로
  merge됐고, 최종 정책 회전 PR #139도 main `6cad8baa`에 병합됐다. 현재 phone은 연결되어 있지 않고
  sensor/relay가 배선되지 않았으므로 버튼-to-GPIO latency, 실제 접점, 초음파 hands-free 결과를
  주장하지 않는다.

## 1. 한눈에 보기

| 축 | 저장소 최신 구현 | 검증/운영 경계 |
|---|---|---|
| Target | ESP32-C6, AJ-SR04T, GPIO3 relay, per-Target MQTTS, signed command/ACL, signed dual-slot OTA. 개인 설치 전용 `esp32c6_personal_production`은 valid door/ACL trust 뒤 Hardwareless를 compile/runtime ON하고, default/commercial profile은 OFF를 유지 | run `32872303874`의 exact-main `2.1.266+main.ga9b6822`가 NAS immutable/pointer readback 뒤 signed OTA로 설치·재부팅됐다. Wi-Fi `192.168.35.19`, MQTTS, ACL v147과 connectable GATT가 정상이고 이후 확인에서 current였다. sensor/relay/rollback은 별도 Gate다 |
| Android | foreground scan, OS-managed BLE wake, native GATT credential worker, AndroidKeyStore public enrollment, native-authoritative consent/ownership, recovery/update UI, bounded NAS APK publisher | run `32872303799`가 production-signed `1.0.0-ga9b6822` / 19801을 NAS primary/fallback에 게시·readback했다. phone 미연결로 설치하지 않았다. 마지막 연결 증거는 `db37bc2` action-1 foreground GATT 성공이며, 현재 action-2 수동 개방과 pocket action-1은 실기기 미검증이다 |
| Backend | FastAPI/MariaDB, enrollment/ACL, personal public-key bootstrap, exact Target ACL apply correlation, signed HA command bridge, admin session/RBAC/CSRF/re-auth, operations APIs | paho-mqtt 1.6.1 MQTTv5 `ReasonCodes` callback correction은 exact main `bc9bb5d`에 포함됐다. NAS live Backend를 rebuild/recreate했고 readiness, Target status, subscriber/discovery와 bridge availability가 정상이다 |
| Access | legacy iBeacon → pre-arm, personal native local GATT, signed Backend/MQTT remote command가 상호 구분됨 | 과거 `db37bc2`에서 action-1 foreground proof/result와 `ARMED`를 실기기로 확인했다. 현재 소스는 action 1 sensor ARM과 action 2 immediate relay를 분리하고 Target FSM 전이 성공에 Result를 결합한다. a9 APK/phone 및 실제 sensor/relay E2E는 미검증이다 |
| OTA | Target periodic HTTPS pull, signed manifest/artifact, inactive slot, health mark/rollback, authenticated local recovery; mobile signed update/recovery 계약 | run `32872303874`의 1,846,624-byte plaintext와 1,846,660-byte encrypted Target artifact가 게시되고 Target에 설치됐다. 7,340,032-byte OTA slot의 25.16%로 5,493,408 bytes가 남는다. run `32872303799`의 55,786,649-byte APK도 NAS에 게시됐으나 미설치다. rollback/power-loss Gate는 열려 있다 |
| Home Assistant | 15개 read-only entity에 더해 Backend ingress→fresh boot/status→서명된 per-Target command bridge 기반 reboot/OTA/config control을 구현. `manual_remote`는 별도 opt-in | live bridge availability와 controls는 enabled다. 과거 `db37bc2`에서 HA OTA와 GATT FSM 상태를 관측했고, 현재 a9 Target OTA도 완료했다. remote/manual relay와 sensor actuation은 수행하지 않았다 |

## 2. 저장소 구현과 현장 배포를 혼동하지 않는다

2026-08-12의 구형 매립본은 더 이상 현재 상태가 아니다. 2026-08-24에 GCM block carry를 포함한 exact-main H9를 app-only USB로 설치하면서 bootloader, partition table, NVS, OTA data와 fallback slot을 보존했다. 이후 signed inactive-slot OTA를 반복해 `db37bc2` 실기기 GATT 증거를 얻었고, 현재는 exact main `a9b68222`의 `2.1.266+main.ga9b6822`가 Target에서 실행 중이다. 저장된 Wi-Fi로 `192.168.35.19`를 얻고 exact per-Target MQTTS, production ACL signer/ACL과 connectable GATT service를 복원했다.

연결된 Samsung phone에는 production signer가 일치하는 `1.0.0-gdb37bc2` / 19001을 replacement install해 앱 데이터와 native credential을 보존했다. 이 APK와 matching Target은 callback-stack 및 Challenge stream 수정 뒤 foreground action-1 proof/result와 `ARMED` 전이를 한 번 완료했다. 이후 issue #133/#134가 action 2 즉시 개방과 bounded pocket dispatch를 추가했고 exact a9 APK까지 게시했지만, phone 미연결로 그 APK를 설치·실행하지 않았다. 따라서 과거 action-1 성공은 현재 수동 action-2 relay 또는 pocket/background 성공의 대체 증거가 아니다.

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
5. Personal Hardwareless RC의 compile/runtime enable, `db37bc2` exact-main Target/APK install과 foreground action-1 proof/result까지는 관측했다. 현재 a9 APK를 phone에 설치한 뒤 action-2 버튼, Samsung/OEM screen-off·process-killed pocket action-1과 latency 분포를 다시 검증한다. Commercial/default compile-OFF와 local kill switch는 보존한다.
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
