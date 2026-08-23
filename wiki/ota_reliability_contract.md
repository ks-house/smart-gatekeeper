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

벽에 매립되어 USB/serial 접근이 어려운 Target은
[`embedded_target_connectivity_policy.md`](embedded_target_connectivity_policy.md)를 추가 최상위 운영 계약으로 적용한다.
Wi-Fi STA와 MQTTS 자동 복구, availability/status last-seen 경보, periodic HTTPS pull, 공유기·broker·WAN 단절
복구 시험이 없으면 “언제든 원격 OTA 가능”으로 판정하지 않는다. BLE beacon 감지와 broker PUBACK만으로는 이
조건을 충족하지 않는다.

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

### 3.3 #14 BLE wake PoC 비회귀 상태

filtered PendingIntent scan PoC는 update discovery/control plane과 다른 receiver action과
저장소를 사용하며 Flutter engine을 wake 전제조건으로 삼지 않는다. opt-in 등록은
`BOOT_COMPLETED`와 `MY_PACKAGE_REPLACED` 뒤 native에서 복구하지만, 앱 업데이트 발견·APK
검증·설치 자체는 BLE event나 이 receiver에 의존하지 않는다.

이 분리는 설계·코드 수준 증거일 뿐 OTA Gate 통과가 아니다. Samsung 기기에서 package
replace 뒤 scanner와 무관하게 start/resume/manual update가 접근 가능하고 기존 APK가
설치 실패 때 보존되는지 확인하기 전에는 OTA-G1/G2/G3을 pending으로 유지한다. 상세는
[android_ble_wake_adr.md](android_ble_wake_adr.md#8-otarollback-영향)를 따른다.

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

서명 알고리즘의 header 상수나 compile 성공만으로 Target runtime 지원을 주장하지 않는다.
실제 production toolchain/configuration이 제공하는 crypto provider로 exact positive manifest와
tampered negative vector를 검증해야 한다. Provider 초기화·알고리즘 지원·서명 검증 중 하나라도
실패하면 artifact 요청과 inactive-slot write 전에 중단하고, Secret이나 서명 원문 없이 운영자가
단계를 구분할 수 있는 failure reason을 남긴다.

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

## 10. 구현 상태 snapshot

### 10.1 2026-08-12 저장소 최신 구현

| 컴포넌트 | 저장소에 구현된 계약 | 계속 pending인 증거 |
|---|---|---|
| Target | periodic HTTPS pull, CA 검증, Ed25519 manifest, SHA-256/size, inactive-slot write, safe-state wait, boot health valid mark/rollback, version floor, signed MQTT trigger, authenticated local recovery | exact-main signed image를 매립 Target에 설치한 뒤 version/boot/health/rollback과 power/network fault를 확인해야 함 |
| Mobile | signed update identity, recovery shell, 기존 APK 보존·first-run health 계약, scanner/WebView와 분리된 recovery 접근 | release artifact의 실제 install/fallback, OEM별 updater 및 N/N-1 실기기 증거 |
| Backend/operations | signed OTA metadata API와 signing bootstrap, production secret contract, canary staging/evidence validator | live NAS production publish, reverse proxy/secondary recovery source와 operator acceptance |

이 표는 **repository implementation**을 설명한다. 개인 현관 Target은 2026-08-12 관측 시 구형
`2.1.0-g75b946a`였으므로 최신 Target OTA 구현이 현장에 배포됐다는 뜻이 아니다. 현재 현장 경계는
[personal_prod_incident_2026_08_12.md](personal_prod_incident_2026_08_12.md)를 따른다.

### 10.2 2026-08-01 역사적 감사 결과

> 아래 표는 계약 수립 당시의 gap snapshot이며 현재 구현 상태가 아니다. 당시 gap이 어떻게 닫혔는지는 위 10.1과 [current_code_audit.md](current_code_audit.md)를 따른다.

| 구성요소 | 코드상 기준선 | P0 판정 |
|---|---|---|
| Target | `app0`/`app1`/`otadata`는 존재하나 `OtaManager`는 MQTT 호출 시 `HTTPUpdate`만 실행 | periodic HTTPS, safe-state 연동, signature, explicit valid mark, rollback 미구현 |
| Mobile | app/WebView/scanner 경로에서 metadata를 읽고 임시 디렉터리에 APK 다운로드 후 installer 호출 | scanner/WebView 독립 UI, fallback, hash/certificate 검증, install health 미구현 |
| Backend | APK와 mobile `version.json`을 동일 FastAPI/NAS 경로에서 제공 | 독립 secondary distribution과 signed metadata 보장 미구현 |
| CI | 이 표 작성 당시 일반 main push는 firmware/APK canary만 빌드·검증·보존하고 production job을 skip했음 | 현재 exact-main 개인 Target OTA 자동 게시와 commercial release 승인은 별도 경로이며 아래 12절을 따름 |

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

`.github/workflows/ota_contract.yml`은 PR/main에서 schema, signature tamper vector, dual-slot layout, state/recovery/fault 계약을 검사한다. Firmware workflow의 모든 main push는 secret-free canary가 통과한 뒤 exact-main 개인 설치 Target용 production profile을 privileged compiler job에서 빌드한다. 이 job은 mode/SHA-256으로 고정한 build input tree만 실행하고 평문 image를 X25519/HKDF/AES-GCM 단기 handoff로 바꾼다. Isolated publisher는 handoff를 인증 복호화해 dedicated content key의 `SGKOTA2` AES-256-GCM envelope와 schema-v2 signed manifest만 NAS에 게시한다. 두 job은 exact `main` deployment branch policy만 있고 required reviewer가 없는 `personal-auto-ota` Environment를 사용한다. 자동 version은 protected main first-parent count를 수치 precedence로 쓰며, commit별 immutable encrypted artifact/manifest를 stage/readback한 뒤 `version.json`만 OpenSSH `posix-rename`으로 원자 교체한다. NAS의 더 최신 signed pointer는 stale run이 덮지 못하며 이전 정상 artifact는 보존한다.

이 자동 개인 설치 게시 결과는 `production_authorized: false`, `release_evidence: false`인 transport evidence다. NAS 게시 성공은 Target download, inactive-slot install, reboot, health valid mark 또는 rollback 성공을 뜻하지 않는다. 기존 commercial Target job은 plaintext schema-v1 migration이 남아 있어 encrypted-v2 전환이 별도로 승인될 때까지 명시적으로 비활성이다. Commercial mobile job은 main-only `production` GitHub Environment의 required reviewer와 `ota/release-evidence.json` Gate를 계속 요구하며 자동 개인 게시가 그 gate를 대체하지 않는다.

보호 workflow와 OTA gate 자체의 PR 변경은 `.github/workflows/trusted_workflow_policy.yml`이 default-branch `base.sha`의 validator/policy만 실행해 별도로 승인한다. Candidate의 workflow, gate, dependency 파일은 GitHub API에서 inert bytes로만 읽고 normalized SHA-256이 하나의 approved bundle과 전체 일치해야 한다. Format v3는 candidate SHA의 recursive tree에서 `.github/workflows/`와 `.github/actions/` exact inventory, regular-file mode와 namespace casing도 검사한다. Candidate가 policy를 함께 수정해도 현재 판정에는 사용되지 않으며, bootstrap과 2단계 rotation은 [trusted_workflow_policy.md](trusted_workflow_policy.md)를 따른다.
release mode는 해당 build의 manifest와 production pinned public key도 입력받아 schema와 실제
Ed25519 signature를 재검증한다. 동시에 workflow가 SFTP/Actions에 올릴 바로 그 firmware/APK
경로를 필수 입력받아 실제 byte length와 SHA-256을 signed manifest와 비교한다. Android는
`apksigner verify --print-certs`가 보고한 단일 signing certificate SHA-256까지 signed metadata와
일치해야 한다. artifact 누락·교체·truncation·digest/certificate mismatch는 모두 fail-closed다.
따라서 evidence나 signed metadata만 맞추고 다른 bytes를 배포할 수 없다.

`contract` PASS는 문서/벡터/정적 불변조건만 증명한다. `release` PASS만 production 배포 허가를
뜻하며, evidence 파일을 형식적으로 수정하는 것은 시험을 대체하지 않는다.
정적 workflow 회귀 검사는 허용되지 않은 push job에 release/SFTP가 들어가거나, exact-main 개인
Target job의 `personal-auto-ota` Environment·main-only policy·secret provenance·monotonic version·signed immutable bytes·readback·
atomic pointer contract가 약화되거나, commercial production job의 명시적 dispatch 조건,
Environment, evidence validator, 동일 artifact 결합이 제거되면 contract 검증 자체를 실패시킨다.

firmware와 mobile의 pull request/branch-dispatch canary job 및 main-push의 public build job은 production secret
표현식이나 상속된 secret 환경을 전혀 받지 않는다. 이 공개 canary는 고정 RFC 8032 시험 키와
`.invalid` artifact URL만 사용하며 installable production release가 아니다. 개인 Target secret과
배포 URL은 exact `refs/heads/main` 및 commit 확인, 보호된 contract/root test 통과,
`personal-auto-ota` 경계 뒤에서만 주입한다. 개인 mobile publisher도 main-only, no-review
`personal-auto-ota` Environment를 사용하되 설치 앱의 기존 trust identity는 전용
`MOBILE_OTA_SIGNING_*` 이름으로 Target `OTA_SIGNING_*`와 분리한다. Commercial release만 required
reviewer가 있는 `production` Environment를 사용한다. Candidate가 제어하는
실행 파일은 그 검증 전에 secret을 받을 수 없고, job DAG/step 순서/artifact propagation 회귀는 보호된
`ota_contract_gate.py`의 음성 mutation test가 fail-closed로 차단한다.

공급망 회귀 검사도 모든 `uses:` action의 full commit SHA, versioned `ubuntu-24.04` runner label,
firmware Python `3.10.20`, mobile Python `3.12.13`·Temurin `17.0.16+8`·Flutter `3.44.8`, exact
Android archive URL/size/SHA-256, pinned Java로 실행하는 `apksigner.jar`/`apkanalyzer` 경로, 두 Gradle wrapper distribution checksum과
hash-complete transitive `ota/requirements.lock`의 `pip --require-hashes` 설치를 묶어 검증한다.
이 pin/lock 검사는 source와 CI dependency provenance를 제한할 뿐 실기기 설치 증거로 승격하지 않는다.

## 13. 운영 책임과 runbook

canary, 중단 기준, Target rollback, mobile stable fallback, 장애별 복구, telemetry와 사후 기록은
[ota_operations_runbook.md](ota_operations_runbook.md)를 따른다. 실제 ESP32/Android 결과는
[hardware_test.md](hardware_test.md)에 원시 증거와 함께 추가한다.

## 14. Hardwareless RC와 production 승인 분리

2026-08-02의 Epic #13 구현 승인은 **G0-SW / Hardwareless RC**에 한정한다. Wave 0 계약을
준수한 #17~#22의 feature-flagged 구현, 코드 리뷰·merge, unit/integration/virtual-E2E는
물리 Samsung/ESP32-C6 없이 진행할 수 있다. 이는 OTA `contract` PASS와 같은 software
evidence이며 OTA-G1~G4 또는 production evidence로 승격하지 않는다.

**G0-HW / Production**은 계속 fail-closed다. Samsung/OEM BLE wake, ESP32-C6 real
GATT/radio coexistence, relay/AJ-SR04T/real BLE, dual-slot bootloader health·rollback·power-loss,
periodic HTTPS와 인증된 local recovery, mobile updater 독립성·fallback, N/N-1,
RELAY-G0~G2, 물리 E2E·rollout 증거가 모두 필요하다. 이 Gate 전에는 production enable,
legacy retirement, Epic closure를 금지하고 #14/#18/#22/#23/Epic #13을 open으로 유지한다.

이 분리는 `../ota/hardwareless-implementation-gates.json`에서 기계 판독하며 기존
`release-evidence.json`은 `release_blocked=true`, `physical_tests=pending`, OTA-G1~G4
`pending`을 유지한다. 인증된 모바일 `manual_remote` 명시적 문 열기와 legacy rollback,
Target dual-slot/rollback·periodic HTTPS·인증 local recovery, mobile manual updater 독립성,
N/N-1 불변조건은 G0-SW 작업으로 약화할 수 없다.
## 15. 2026-08-09 issue #50 Target implementation status

The Target implementation now verifies Ed25519 manifests, downloads only over CA-verified HTTPS, writes the inactive OTA partition, checks exact size/SHA-256/image validity, selects the candidate only after verification, and uses pending-verify continuous-health marking or automatic rollback. Every failed health predicate resets the healthy-since window. A remote download that makes no progress for 30 seconds or exceeds five minutes aborts the inactive write and returns to the 15-minute retry schedule. Periodic HTTPS and authenticated local WPA2/Basic recovery are independent of MQTT; an authenticated station-local request can open a bounded AP+STA recovery window even while DNS, Backend, MQTT, or the manifest host is unavailable, while signed `ota_check` remains an optional trigger. Protocol overlap 1..2, a crash-safe strictly ordered SemVer floor, rejection of equal-precedence alternate and exact-current reflash identities, quarantine of the exact failed floor after bootloader rollback, the previously bootable slot, and manual local recovery preserve N/N-1 and rollback paths. A strictly newer version remains eligible after rollback so a corrected image can recover the installation.

This is host/software evidence only. Real ESP32-C6 bootloader, partition, power-loss, health-valid, rollback, radio, broker certificate, local recovery, N/N-1, operator, and production evidence remains pending; OTA-G1..G4 and production authorization stay fail-closed. See [target_command_ota_security.md](target_command_ota_security.md).

## 16. 2026-08-23 personal main-push OTA publishers

The single-owner installation has two narrowly scoped automatic delivery lanes.
The commercial mobile definition remains evidence/reviewer-gated, while the
legacy plaintext Target commercial definition is disabled pending encrypted-v2
migration. Both personal lanes run after an
exact `main` push and their public build/test dependency succeeds; an exact-main
manual dispatch enters them only when `release_target=canary`. The Target lane
uses the no-review, main-only `personal-auto-ota` Environment for Target runtime
configuration and repository-scoped signing/NAS names. The commercial
`production` Environment remains main-only and reviewer-protected.

The mobile signing lane uses the same main-only, no-review `personal-auto-ota`
Environment, but consumes dedicated `MOBILE_OTA_SIGNING_*` names because the
embedded Target and the already-installed APK have different OTA trust
identities. The unsigned producer remains separate. Before signing, the
publisher accepts exactly one regular non-symlink APK within the bounded size
range and rechecks its SHA-256. Workflow validation pins the installed mobile
key identity and Android package signer so Environment shadowing or keystore
rotation fails before NAS contact.

Before either NAS root is changed, the mobile publisher preflights both roots.
An APK without metadata, unverifiable existing metadata, or a candidate below
the highest signed version-code floor fails closed. A valid signed floor remains
binding even if its paired APK is absent or corrupt; such a pair requires a
strictly higher candidate to repair and cannot be overwritten by equal/stale
bytes. This all-roots-first rule prevents a fallback mutation followed by a
primary-floor rejection.

The mobile lane then produces a release APK and signed manifest, stages both in the
primary and fallback NAS directories, performs SFTP readback, preserves
immutable candidates plus the previous valid artifact/manifest pair, and uses
SFTP `posix_rename` to promote APK bytes before metadata. Job concurrency
serializes publishers without cancelling an active two-file promotion. The
publisher rejects stale pointers, double-reads each final pair, restores the
previous pair if APK/manifest promotion or either promotion readback fails, and
requires both public HTTPS
origins to serve the exact artifact and manifest. This supplies the owner's
updater; it does not assert that an Android package installer completed, that
first-run health passed, or that fallback/rollback has been exercised on a
device. Each retry uses a bounded higher Android version code derived from the
workflow run and attempt, and artifact/evidence names preserve each attempt.
Both automatic password-authenticated publishers require a repository-pinned
NAS host key and reject runtime keyscan. Those observations belong in
`hardware_test.md`.

The mobile `release_to_production` job remains manual, protected by the
`production` Environment, and blocked by `ota/release-evidence.json`. The Target
job with that name is explicitly disabled pending encrypted-v2 migration so it
cannot publish plaintext schema-v1 firmware. Personal automatic publication
does not set commercial evidence, enable Hardwareless RC, retire the legacy
path, or close OTA-G1..G4.

## 17. 2026-08-24 Target content confidentiality and bootstrap

Public Target distribution uses `SGKOTA2\0 || nonce(12) || ciphertext || tag(16)`.
The content key is a dedicated 32-byte Secret and is never derived from MQTT or
recovery credentials. A separate HKDF nonce key computes a deterministic nonce
from the exact AAD and plaintext SHA-256, so an exact commit rerun produces the
same envelope while different commit/content identity produces a different
nonce. AAD is `smart-gatekeeper-target-content-v1\n<commit>\n<key-id>\n`.

Manifest schema v2 binds envelope size/SHA-256, plaintext size/SHA-256,
`AES-256-GCM` and content key ID under the existing Ed25519 signature. HTTPS and
authenticated local recovery feed one streaming decrypt/write engine. It does
not select the inactive partition until envelope digest, plaintext digest, ESP
image validation and GCM tag all succeed; failure aborts the inactive write and
does not erase NVS or the active slot.

Schema-v1 firmware cannot consume this envelope. The Target received its first
NVS-preserving USB bootstrap to schema-v2 consumer `2.1.233+main.g9e9114b` on
2026-08-24, but a subsequent content-key rotation intentionally invalidated its
ability to decrypt future envelopes. Exact main `2.1.234+main.g3927a97` contains
the rotated material and was therefore installed by one additional
NVS-preserving USB bootstrap. The workflow's exact contract kept the
policy-pinned ID `personal-target-content-20260824-1`; this emergency rotation
must be audited by exact firmware commit and manifest because the unchanged ID
does not distinguish the two material epochs. A strictly newer exact-main
periodic HTTPS OTA must now prove inactive-slot install, reboot and health-valid
marking.
The content key is embedded in firmware; without ESP32 flash encryption this is
NAS-at-rest/distribution confidentiality, not resistance to an attacker with
physical flash read access.

## 18. 2026-08-24 H5 manifest rejection and Ed25519 provider correction

Exact H5 main `6517caa957dcf1c42ece49d15e38a428c81262e5`, version
`2.1.235+main.g6517caa`, passed CI publication, NAS/public exact-byte readback and
independent local Ed25519, AES-256-GCM, ciphertext/plaintext SHA-256 and ESP32-C6
N16 image checks. Those checks prove the published bytes and offline key binding,
not that H4's embedded verifier can consume them.

The running H4 did not reboot during the periodic check window. An authenticated
same-LAN recovery request then posted the exact H5 manifest and received HTTP 400
before any artifact upload or inactive-slot write. H4 remained online on Wi-Fi
and MQTTS, and the existing `app1` was not displaced. This is a fail-closed
preservation result and a failed OTA attempt, not OTA-G1/G3/G4 completion.

The failure was a crypto-provider mismatch: the H4 binary selected PSA
PureEdDSA, while its actual ESP32-C6 Arduino/ESP-IDF Mbed TLS configuration did
not provide that algorithm at runtime despite exposing the PSA identifier in
headers. Manifest verification has therefore moved to the bundled Espressif
libsodium provider, with `sodium_init()` and
`crypto_sign_verify_detached()` plus compile-time 32-byte public-key and 64-byte
signature contracts. Initialization or signature failure remains fail-closed.

The libsodium change currently has source, host-test and ESP32-C6 build/capacity
evidence only. H4 cannot authenticate its corrective successor, so exact
merged-main H6 must first be installed app-only over USB while preserving NVS,
OTA data and the fallback slot. It becomes physical OTA evidence only after a
strictly newer H7 is accepted by H6, writes the inactive slot, reboots with the
expected version/new boot ID, completes the continuous health window and is
marked valid. Automatic rollback, power-loss and N/N-1 recovery remain separate
pending Gates.
