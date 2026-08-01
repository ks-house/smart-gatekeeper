# 모바일 앱·Target OTA 신뢰성 최상위 계약

> 작성일: 2026-08-01
> 우선순위: **P0 — 모든 기능·아키텍처 변경보다 우선하는 불변조건**
> 적용 대상: Android 모바일 앱, ESP32-C6 Target, Backend 배포 API, GitHub Actions/NAS 배포
> GitHub 추적: [#23](https://github.com/ks-house/smart-gatekeeper/issues/23)

## 1. 절대 원칙

모바일 앱과 ESP32-C6 Target은 BLE 인증, local ACL, FSM, Backend, UI가 어떤 상태로
변경되더라도 **업데이트 가능한 복구 경로를 항상 유지해야 한다.**

이 프로젝트에서 OTA 안정성의 우선순위는 다음과 같다.

```text
1. relay·출입 안전
2. 기존 bootable/installable 버전 보존
3. OTA 복구 가능성 보존
4. 새 출입 기능
```

새 기능이 OTA 경로와 충돌하면 새 기능을 연기하거나 rollback한다. OTA를 약화시키는
변경은 기능이 정상 동작해도 완료나 production 배포로 판정하지 않는다.

## 2. “어떤 경우에도 OTA 가능”의 운영 정의

소프트웨어가 통제할 수 없는 다음 상태에서는 즉시 OTA를 실행할 수 없다.

- 전원 없음
- 모든 네트워크 단절
- Android 사용자의 force-stop/설치 거부
- 저장 공간 부족 또는 물리 flash 손상
- 인증된 배포 서버와 local recovery 경로가 모두 접근 불가

따라서 “항상 OTA 가능”은 다음을 의미한다.

1. 외부 조건이 복구되면 운영 기능과 독립된 update control plane이 자동 또는 사용자
   동작으로 다시 OTA를 시도할 수 있다.
2. 한 트리거·서버·프로세스가 고장 나도 다른 승인된 경로가 존재한다.
3. 다운로드·검증·설치·부팅 중 실패해도 마지막 정상 버전을 잃지 않는다.
4. 모바일과 Target을 서로 다른 시점에 업데이트해도 N/N-1 조합이 동작한다.
5. OTA 성공은 파일 업로드나 broker PUBACK가 아니라 새 버전의 설치·부팅·health
   확인까지 추적한다.

## 3. 현재 기준선과 공백

### 3.1 Target 현재 기준선

- 16 MB flash의 `app0`/`app1` dual OTA partition 사용
- GitHub Actions가 firmware와 `version.json`을 NAS로 배포
- MQTT `ota_update` 명령으로 `OtaManager::checkAndUpdate(true)` 실행
- HTTPS Root CA 검증과 `HTTPUpdate` 사용
- 성공 재부팅 전 `planned_restart=ota_update` 기록
- OTA 설치와 새 boot/version 관측 실적 존재

남은 공백:

- `OtaManager::init()`은 주기 확인을 시작하지 않아 MQTT 명령이 유일한 실제 trigger다.
- Target이 MQTT에서 이미 offline이면 원격 OTA 명령을 받을 수 없다.
- dual partition은 있으나 새 image health 확인 뒤 valid mark와 자동 rollback 계약이 없다.
- manifest/artifact의 hash·서명 검증 계약이 없다.
- OTA 중 power loss, 잘못된 image, reset loop, NVS migration rollback 시험이 없다.
- provisioning AP의 인증된 local wireless recovery 경로가 없다.

### 3.2 모바일 현재 기준선

- NAS/Backend의 `version.json`과 APK endpoint 사용
- 앱 시작·복귀·15분 UI timer와 scanner 초기화 경로에서 update 확인
- 앱 내부 다운로드와 Android package installer 호출
- `REQUEST_INSTALL_PACKAGES` 선언
- GitHub Actions가 APK와 version metadata를 NAS에 배포

남은 공백:

- update discovery가 UI/WebView/scanner 생애주기와 결합돼 있다.
- primary endpoint가 내려가면 승인된 fallback distribution path가 없다.
- APK hash와 예상 signing certificate continuity를 앱이 사전 검증하지 않는다.
- 중단 다운로드 resume, 저장 공간, 손상 파일, 설치 거부/실패 상태 계약이 약하다.
- native/Flutter/SharedPreferences/protocol migration의 N/N-1·rollback 시험이 없다.
- Android 정책상 sideload APK 설치는 사용자 확인이 필요하므로 완전 무인 설치는 보장할
  수 없다.

## 4. Target OTA 필수 경로

### 4.1 독립 trigger

최소 세 경로를 제공한다.

1. **Periodic HTTPS pull:** boot 안정화 뒤와 Wi-Fi 재연결 뒤, 이후 bounded interval로
   manifest 확인
2. **MQTT on-demand:** 운영자가 즉시 요청하는 기존 command 경로
3. **Provisioning AP local recovery:** Backend/MQTT/DNS 장애 시 인증된 local Web OTA

세 경로는 같은 manifest 검증·inactive slot 설치·health/rollback engine을 호출해야
하며 별도 구현으로 보안 규칙이 달라지면 안 된다.

### 4.2 Target OTA 상태 머신

```text
IDLE
→ UPDATE_REQUESTED
→ WAIT_SAFE_STATE
→ CHECK_MANIFEST
→ VERIFY_MANIFEST
→ DOWNLOAD_INACTIVE_SLOT
→ VERIFY_IMAGE
→ SET_PENDING_BOOT
→ REBOOT
→ BOOT_HEALTH_WINDOW
   ├─ self-test + network/control-plane health 통과 → MARK_VALID
   └─ crash/reset/timeout/health 실패 → ROLLBACK_PREVIOUS_SLOT
```

### 4.3 안전 규칙

- relay ON, RELAY_HOLD, active flash write와 개방 command를 겹치지 않는다.
- OTA request가 오면 현재 물리 session을 안전하게 끝낸 뒤 bounded timeout 안에
  `WAIT_SAFE_STATE`로 진입한다.
- OTA 대기·다운로드 중에도 별도 relay one-shot cutoff와 boot default OFF를 유지한다.
- 새 command는 `OTA_BUSY`로 거부하거나 queue 정책에 따라 명확히 처리한다.
- download/verify 실패는 active slot과 기존 NVS를 변경하지 않는다.
- ACL/credential/NVS migration은 copy-on-write와 schema version을 사용하며 이전
  firmware가 읽을 수 없는 irreversible migration을 OTA valid mark 전에 commit하지 않는다.

### 4.4 artifact 신뢰

Target manifest는 최소 다음 필드를 가진다.

```text
schema_version
firmware_version
protocol_min / protocol_max
board / flash_layout
artifact_url
artifact_size
sha256
signature / signing_key_id
mandatory_after
published_at
```

TLS 성공만으로 artifact를 신뢰하지 않는다. manifest signature와 firmware digest를
검증하고 board/partition/protocol 범위가 맞지 않으면 flash하지 않는다.

### 4.5 완료 판정

다음 전체가 확인돼야 Target OTA 성공이다.

```text
artifact published
→ Target update request/periodic discovery
→ manifest/image verified
→ inactive slot written
→ planned OTA reboot
→ expected version + new boot_id
→ health window pass
→ image marked valid
→ availability/status/event 정상
```

NAS upload, MQTT PUBACK, download 100%만으로 성공 처리하지 않는다.

## 5. 모바일 앱 업데이트 필수 경로

### 5.1 update discovery 독립성

모바일 update manager는 다음에 의존하지 않는다.

- foreground BLE scanner 생존
- AltBeacon/native GATT worker 성공
- WebView page load 성공
- tenant 승인 또는 local ACL 상태
- Target online 여부

다음 진입점을 제공한다.

1. app cold start와 resume 확인
2. Android system이 허용하는 bounded periodic check
3. 설정 화면의 수동 update 확인
4. 앱이 crash/구버전 protocol로 동작하지 않을 때 사용할 stable HTTPS landing/download URL
5. primary NAS 장애 시 승인된 secondary distribution endpoint

### 5.2 모바일 update 상태 머신

```text
IDLE
→ CHECK_METADATA
→ VERIFY_METADATA
→ COMPARE_VERSION/COMPATIBILITY
→ CHECK_STORAGE
→ DOWNLOAD_TEMP
→ VERIFY_SHA256_AND_SIGNING_IDENTITY
→ REQUEST_PACKAGE_INSTALL
   ├─ user approved + install success → NEW_APP_FIRST_RUN_HEALTH
   ├─ user denied → OLD_APP_REMAINS + REMIND
   └─ failure → OLD_APP_REMAINS + RETRY/FALLBACK
```

Android package installer의 사용자 확인은 보안 경계이므로 우회하지 않는다. “OTA 가능”은
항상 무인 설치가 아니라 사용자가 update를 발견하고 안전하게 설치할 수 있는 경로를
의미한다.

### 5.3 모바일 artifact 계약

모바일 metadata는 최소 다음을 포함한다.

```text
schema_version
version_name / version_code
protocol_min / protocol_max
min_android_sdk
apk_url + fallback_url
apk_size
sha256
signing_certificate_digest
mandatory_after
release_notes_url
published_at
```

- APK 설치 전 hash와 expected signing identity를 검사한다.
- 다운로드는 임시 파일에 저장하고 검증 뒤에만 installer로 넘긴다.
- 중단·손상·공간 부족 때 기존 APK와 credential을 훼손하지 않는다.
- update UI는 legacy/new BLE feature flag 상태와 무관하게 접근 가능해야 한다.

## 6. 모바일·Target 독립 배포와 호환성

모바일과 Target은 동시에 업데이트된다고 가정하지 않는다. production release는 최소
다음 조합을 통과해야 한다.

| Mobile | Target | Backend | 필수 결과 |
|---|---|---|---|
| N | N | N | 전체 기능 정상 |
| N | N-1 | N | protocol negotiation 또는 legacy fallback 정상 |
| N-1 | N | N | Target가 이전 app proof/flow 지원 |
| N | N | N-1 | Backend 관리 plane의 직전 계약 호환 |
| N-1 | N-1 | N | 단계적 rollout 중 정상 |

- protocol version negotiation 실패가 update UI나 Target OTA trigger를 막아서는 안 된다.
- mandatory update는 출입을 무조건 즉시 차단하기 전에 offline/비상 정책을 별도로 따른다.
- Backend schema migration은 expand→migrate→contract 순서를 사용해 구버전 앱/Target과
  병행 기간을 갖는다.
- mobile과 Target artifact는 독립적으로 배포·rollback할 수 있어야 한다.

## 7. Release blocking 시험

| 시험 | Mobile 기대 결과 | Target 기대 결과 |
|---|---|---|
| primary endpoint 차단 | fallback metadata/APK 접근 | periodic/MQTT 실패 뒤 local AP recovery 가능 |
| scanner/GATT 고장 | 설정/manual update 정상 | 출입 protocol 오류와 OTA engine 분리 |
| MQTT 차단 | 영향 없음 | periodic HTTPS OTA 가능 |
| Backend app 차단 | stable fallback landing 사용 | manifest host 접근 또는 local AP recovery |
| 다운로드 50% 중단 | 기존 앱 유지, 재시도 가능 | active slot 유지, 재시도 가능 |
| artifact hash 오류 | installer 호출 금지 | inactive image boot 금지 |
| signing identity 오류 | installer 호출 금지 | manifest/image 거부 |
| 설치/flash 중 전원 차단 | Android 기존 앱 유지 | 이전 bootable slot 부팅 |
| 새 버전 즉시 crash | 사용자가 이전 정상 APK 복구 가능 | health window 실패 후 자동 rollback |
| N/N-1 조합 | update UI와 인증 유지 | OTA와 legacy protocol 유지 |
| 저장 공간 부족 | 명확한 복구 안내 | active slot/NVS 보존 |

## 8. 모든 PR의 OTA Definition of Done

모바일, Target, Backend, protocol, storage, network 관련 PR은 다음을 답해야 한다.

1. mobile update discovery/download/install 경로에 영향이 있는가?
2. Target periodic/MQTT/local recovery OTA 경로에 영향이 있는가?
3. active slot/기존 APK/credential/ACL을 실패 시 보존하는가?
4. N/N-1 compatibility가 유지되는가?
5. update telemetry와 rollback reason을 확인할 수 있는가?
6. 해당 영향의 자동 또는 실기기 regression test가 있는가?

하나라도 미확인이라면 OTA 영향 없음의 근거를 남기거나 #23의 시험을 수행하기 전에는
병합하지 않는다.

## 9. 전환 Gate

- **OTA-G0 Contract:** metadata, signature, state machine, health/rollback 기준 확정
- **OTA-G1 Component:** mobile/Target 독립 update path와 실패 보존 시험 통과
- **OTA-G2 Compatibility:** N/N-1 matrix 통과
- **OTA-G3 Recovery:** Target local AP recovery와 mobile fallback distribution 실증
- **OTA-G4 Production:** canary update, install/boot health confirmation, rollback runbook 승인

새 모바일 병목 축소 아키텍처는 OTA-G0~G3을 통과하지 않으면 production rollout할 수
없고, legacy path도 제거할 수 없다.

## 10. 2026-08-01 구현 감사 결과

| 구성요소 | 코드상 기준선 | P0 판정 |
|---|---|---|
| Target | `app0`/`app1`/`otadata`는 존재하나 `OtaManager`는 MQTT 호출 시 `HTTPUpdate`만 실행 | periodic HTTPS, safe-state 연동, signature, explicit valid mark, rollback 미구현 |
| Mobile | app/WebView/scanner 경로에서 metadata를 읽고 임시 디렉터리에 APK 다운로드 후 installer 호출 | scanner/WebView 독립 UI, fallback, hash/certificate 검증, install health 미구현 |
| Backend | APK와 mobile `version.json`을 동일 FastAPI/NAS 경로에서 제공 | 독립 secondary distribution과 signed metadata 보장 미구현 |
| CI | 일반 main push는 firmware/APK canary와 legacy `version.json`을 빌드·검증·보존하고 production job은 skip | production signing과 physical release evidence가 없으며 명시적 승인 release 전까지 배포 차단 |

dual partition의 존재나 과거 OTA 성공은 rollback 증거가 아니다. 따라서 현재 물리 Target과
Android 완료 기준은 `pending`이며 issue #23을 자동 close하지 않는다.

## 11. Machine-readable 계약과 서명 규칙

실행 가능한 계약은 `ota/` 아래에 둔다.

- Target/mobile schema: `ota/schemas/*.schema.json`
- deterministic Ed25519 positive/tampered vectors: `ota/test-vectors/`
- 상태 머신과 recovery/fault matrix: `ota/*.json`
- validator/release blocker: `scripts/ota_contract_gate.py`

manifest v1의 서명 입력 `sgk-json-v1`은 최상위 `signature`만 제거하고, nested/float 값을
금지하며, UTF-8·key sort·공백 없음·ASCII escape 없음으로 직렬화한 바이트다. Ed25519를
사용하고 `signing_key_id`로 rotation을 식별한다. test vector의 RFC 8032 key는 production
trust root가 아니며 production private key는 GitHub secret/HSM 경계 밖으로 출력하거나 저장하지
않는다.

N-1 소비자를 위해 Target `version == firmware_version`, Mobile
`version == version_name`, `build_number == version_code` alias를 schema semantic check로
강제한다. fallback URL은 primary APK URL과 달라야 한다.

상태 머신의 `failure_preserves`와 `invariants`는 단순 문자열 목록이 아니라 구성요소별
필수 집합과 정확히 같아야 한다. initial/terminal success도 각각 Target
`IDLE`/`MARK_VALID`, Mobile `IDLE`/`COMPLETE`로 고정한다. recovery matrix는 자유 텍스트를
허용하지 않고 allowlist outcome/action과 선언된 상태 간 `from_state`→`to_state`를 사용하며,
각 장애 ID의 Gate·결과·동작·전이가 기준 semantic mapping과 정확히 일치해야 한다.

## 12. CI release gate 판정

`.github/workflows/ota_contract.yml`은 PR/main에서 schema, signature tamper vector, dual-slot
layout, state/recovery/fault 계약을 검사한다. firmware/mobile build workflow의 일반 main push와
기본 canary dispatch는 build/test/contract 검증과 Actions canary 보존까지만 수행하고 production
release job을 실행하지 않는다. 운영 배포는 쓰기 권한자가 `workflow_dispatch`의
`release_target=production`을 명시하고 `production` GitHub Environment 승인을 통과한 경우에만
별도 job으로 진입한다. 이 job은 `ota/release-evidence.json`의 OTA-G0~G4, physical test, 승인자가
모두 통과하지 않으면 production NAS SFTP 전에 실패한다.
release mode는 해당 build의 manifest와 production pinned public key도 입력받아 schema와 실제
Ed25519 signature를 재검증한다. 동시에 workflow가 SFTP/Actions에 올릴 바로 그 firmware/APK
경로를 필수 입력받아 실제 byte length와 SHA-256을 signed manifest와 비교한다. Android는
`apksigner verify --print-certs`가 보고한 단일 signing certificate SHA-256까지 signed metadata와
일치해야 한다. artifact 누락·교체·truncation·digest/certificate mismatch는 모두 fail-closed다.
따라서 evidence나 signed metadata만 맞추고 다른 bytes를 배포할 수 없다.

`contract` PASS는 문서/벡터/정적 불변조건만 증명한다. `release` PASS만 production 배포 허가를
뜻하며, evidence 파일을 형식적으로 수정하는 것은 시험을 대체하지 않는다.
정적 workflow 회귀 검사는 push job에 release/SFTP가 다시 들어가거나 production job의 명시적
dispatch 조건, Environment, evidence validator, 동일 canary artifact 결합이 제거되면 contract
검증 자체를 실패시킨다.

## 13. 운영 책임과 runbook

canary, 중단 기준, Target rollback, mobile stable fallback, 장애별 복구, telemetry와 사후 기록은
`wiki/ota_operations_runbook.md`를 따른다. 실제 ESP32/Android 결과는
`wiki/hardware_test.md`에 원시 증거와 함께 추가한다.
