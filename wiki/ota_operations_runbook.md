# OTA 운영 runbook

> Last updated: 2026-08-24
> Scope: Android mobile, ESP32-C6 Target, Backend/NAS distribution, CI
> Status: 절차 확정; OTA-G1~G4 실기기 증거 pending

## 1. 배포 전 판정

### 1.1 Exact-main 개인 Target 자동 게시

`main` push가 public build/test를 통과하면 privileged compiler job이 exact SHA를 full-history
checkout하고 mode/SHA-256으로 고정된 build input inventory에서 `esp32c6_production` N16 image를
빌드한다. 평문 image는 X25519/HKDF/AES-GCM 단기 handoff로만 isolated publisher job에 전달되며,
public Actions artifact에는 노출되지 않는다. Version은
`2.1.<first-parent-count>+main.g<short-sha>`여야 하며, commit count를 patch precedence로 사용해
임의 SHA lexicographic order와 stable `2.1.1` prerelease 충돌을 피한다. build ID는 `main.<count>`가 아니라
`main-<first-parent-count>-<full-sha>`로 결정하고 commit timestamp를 publication/build epoch로
사용한다. Publisher는 handoff를 인증 복호화한 뒤 별도 Target content key로 `SGKOTA2` AES-256-GCM
envelope를 만들고 평문을 삭제한다. Production Ed25519 key로 schema-v2 manifest를 생성·재검증한 뒤
다음 순서를 모두 통과해야 한다.

실패한 main-push workflow의 GitHub rerun은 같은 push event를 유지하므로 더 큰
`github.run_attempt`와 충돌 없는 Actions artifact 이름으로 이 자동 게시를 재시도한다. exact
`refs/heads/main`에서 `release_target=canary`로 수동 dispatch해도 checkout SHA 일치를 확인한 뒤
personal publisher를 실행한다. physical-test와 commercial dispatch choice는 이 경로에 들어오지 않는다.

1. `.sgkenc` firmware envelope와 manifest를 commit별 immutable staging path에 upload한다. 평문
   `firmware.bin`은 NAS에 전송하지 않는다.
2. 두 파일을 다시 내려받아 local bytes와 비교한다.
3. 기존 signed `version.json`이 더 최신이면 stale run을 중단한다.
4. 기존 정상 artifact/manifest와 새 immutable pair를 보존한다.
5. OpenSSH `posix-rename` 한 번으로 `version.json` pointer를 교체하고 다시 읽어 비교한다.
6. `SECRET_OTA_VERSION_URL`과 manifest의 commit별 immutable artifact URL을 HTTPS로 다시 받아
   provisioned `SECRET_ROOT_CA_CERT`로 TLS chain을 검증한 뒤 local signed manifest/firmware와
   byte-for-byte 비교하고 재검증한다. HTTPS 외 protocol redirect는 거부한다.

`version.json`이 실제로 없을 때만 최초 bootstrap을 자동 허용한다. 파일이 존재하지만 current
schema/signature로 검증되지 않으면 구형 queued workflow나 잘못된 key rotation이 새 pointer를 덮지
못하도록 fail-closed하며, 운영자가 별도 migration을 결정해야 한다.

기존 현장 `2.1.0-gd06519e`는 plaintext schema-v1 consumer이므로 encrypted schema-v2 pointer를 읽을 수
없다. 최초 1회는 NVS를 지우지 않는 USB app-slot bootstrap으로 v2 consumer를 설치해야 하며, 그 뒤
두 번째 exact-main release를 periodic HTTPS OTA로 install→reboot→health 확인한다. Content key rotation도
동일하게 old/new reader overlap이나 USB bootstrap 계획 없이는 수행하지 않는다.

자동 password-authenticated publisher에는 independently verified `NAS_KNOWN_HOSTS`가 필수다. 값이
없거나 live key와 다르면 credential 전송/게시 전에 실패하며 runtime keyscan으로 우회하지 않는다.
NAS가 `posix-rename`을 지원하지 않아도 이전 pointer를 유지한 채 fail-closed한다.

이 job은 exact `main`만 허용하고 required reviewer가 없는 `personal-auto-ota` Environment를 사용한다.
따라서 검사를 통과한 main push와 exact-main `release_target=canary` dispatch는 승인 대기 없이
진행한다. Commercial mobile job은 별도 `production` Environment의 main-only policy와 required
reviewer(`tworimpa`)를 계속 적용하고 Target commercial job은 encrypted-v2 migration 전까지 disabled이며,
개인 자동 게시가 그 승인을 우회하거나 대체하지 않는다.

Secret materialize와 NAS contact 전에 실행하는 공급망 preflight에서 모든 `uses:` action은 full commit SHA, runner는
`ubuntu-24.04` label로 고정되어야 한다. Firmware lane은 Python `3.10.20`, mobile lane은 Python
`3.12.13`, Temurin `17.0.16+8`, Flutter `3.44.8`, Android build-tools `36.0.0`의
`apksigner.jar`와 cmdline-tools `12.0`의 `apkanalyzer`를 사용한다. Mobile signing publisher는 세 공식
archive의 URL·byte size·SHA-256을 검증하고 path traversal을 거부한 뒤에만 압축을 해제하며 runner의
mutable Android SDK를 탐색하지 않는다. Python dependency는
`ota/requirements.lock`을 `pip --require-hashes`로 설치하며, main Gradle `9.1.0`과 vendored
Gradle `5.4.1` distribution은 각각 wrapper의 검토된 `distributionSha256Sum`과 일치해야 한다.
누락되거나 다른 tool을 runner에서 임의 탐색해 대체하지 않는다.

commercial `2.2.0` 이상을 배포하면 다음 personal main publish 전에 이 lane의 major/minor base와
contract를 `2.2` 이상으로 명시적으로 올린다. 그렇지 않으면 signed NAS current core가 더 높으므로
publisher가 stale downgrade로 실패하는 것이 정상이며, 기존 pointer를 강제로 덮지 않는다.

이 단계의 성공은 개인 Target이 새 manifest를 조회할 수 있는 NAS transport 증거일 뿐이다.
실제 install→reboot→Wi-Fi/MQTTS health→valid mark/rollback은 아래 Target canary 절차로 별도 확인한다.
또한 자동 게시 evidence는 commercial `release` 승인이나 `ota/release-evidence.json` 갱신이 아니다.

### 1.2 Exact-main 개인 Mobile 자동 게시 preflight

`publish_personal_mobile_ota`는 public mobile build/test 뒤의 exact `main` push 또는 exact-main
`release_target=canary` dispatch에서만 실행하며 main-only, no-review `personal-auto-ota` Environment를
사용한다. Signing 전에 unsigned artifact가 정확히 한 개의 regular file이고 symlink가 아니며 허용
size/SHA-256이 유지되는지 확인한다. 설치 앱이 신뢰하는 mobile identity는 전용
`MOBILE_OTA_SIGNING_*` 이름을 사용해 같은 Environment의 Target `OTA_SIGNING_*` 값과 shadowing되지
않는다. Secret 이름과 범위는
[`env_setup.md`](env_setup.md)에 기록하며 값은 문서나 로그에 남기지 않는다.

NAS 변경 전 publisher는 primary와 fallback root를 **모두** 읽어 다음 preflight를 적용한다.

1. metadata가 없고 APK도 없는 root만 bootstrap 대상으로 본다.
2. APK만 있거나, metadata가 존재하지만 schema/Ed25519 signature를 검증할 수 없으면 전체 publish를
   중단한다.
3. 유효하게 서명된 metadata의 version code는 paired APK가 누락·손상되어도 floor로 유지한다.
4. 두 root 중 가장 높은 floor보다 낮은 candidate는 거부한다. 손상된 equal-floor pair의 repair도
   strictly higher version code가 필요하며 equal identity의 다른 bytes는 거부한다.
5. 양쪽 preflight가 모두 통과한 뒤에만 staged upload/readback, immutable retention,
   APK→manifest `posix_rename`, public primary/fallback HTTPS exact-byte readback을 수행한다.
6. SFTP readback은 220 MiB regular-file 상한, 64-request prefetch, 120초 channel idle timeout을
   적용하고 publisher job 전체는 30분 안에 종료되어야 한다. 같은 root의 preflight state를 publish에
   재사용하되 exact root binding과 promotion 직전 signed metadata 재확인은 유지한다. 30분 초과,
   channel timeout 또는 수동 취소는 배포 성공이 아니며 evidence/HTTPS 단계가 skipped이면 NAS의
   fixed APK와 manifest를 다시 확인한 뒤 strictly newer exact-main build로 복구한다. 남은 staging
   directory를 자동 삭제하거나 stale/equal version code로 강제 덮어쓰지 않는다.

이 순서는 fallback에 새 APK를 올린 뒤 primary의 더 높은 floor를 발견하는 partial stale publish를
막는다. 성공해도 NAS publication evidence일 뿐 Android installer 승인·완료, first-run health,
credential 보존 또는 fallback/rollback의 실기기 증거는 아니다.

### 1.3 Commercial release 판정

Target의 기존 `release_to_production` job은 plaintext schema-v1을 게시할 수 있으므로 encrypted-v2
migration이 별도로 완료될 때까지 조건에 `false &&`를 포함해 실행 불가다. Mobile commercial job은
아래 evidence와 `production` Environment 승인을 계속 요구한다. Personal automatic publisher는 어느
commercial Gate도 대체하지 않는다.

벽 매립형 Target에는 다음 연결 preflight를 먼저 적용한다.

- 최근 status 수신이 15초 이내인지 확인한다.
- 현재 boot ID, firmware version, Wi-Fi RSSI와 MQTTS availability가 서로 일치하는지 확인한다.
- 90초 이상 status가 없으면 OTA 명령을 발행하지 않고 Target offline incident로 전환한다.
- BLE beacon만 보이는 상태를 online으로 취급하지 않는다.
- 자세한 SLO, 자동 복구와 매립 승인 기준은
  [`embedded_target_connectivity_policy.md`](embedded_target_connectivity_policy.md)를 따른다.

1. `python scripts/ota_contract_gate.py contract`와 OTA 단위 테스트를 실행한다.
2. release commit에서 mobile/Target N/N-1 조합과 `ota/fault-injection-plan.json`의
   모든 physical Gate 증거를 수집한다.
3. `ota/release-evidence.json`에 증거 위치, 승인자, 승인 시각을 기록한다. 실제 증거 없이
   `pending`을 `passed`로 바꾸지 않는다.
4. release manifest, 실제 배포할 firmware/APK 경로, pinned production public key를 전달한
   `python scripts/ota_contract_gate.py release`가 통과하고 GitHub `production` Environment
   보호 정책(`environment: production`, 외부 API 설정)을 만족하는 경우에만 production NAS 배포를
   허용한다. Gate 입력 artifact는 이후 Actions/SFTP upload 대상과 동일한 경로여야 하며,
   실제 byte length·SHA-256을 signed metadata와 비교한다. APK는 Android SDK `apksigner`로
   서명 유효성과 certificate SHA-256도 확인한다. 누락·교체·truncation·certificate mismatch는
   모두 배포 중단 조건이다. 현재 CI는 canary artifact를 먼저 보존하고 이 단계에서
   production SFTP를 차단한다.

5. mobile과 Target을 동시에 강제하지 않는다. 먼저 canary를 배포하고 N/N-1 telemetry를
   확인한 뒤 각 artifact를 독립적으로 확대한다.

## 2. Target canary 절차

1. 현재 slot, firmware version, boot ID, reset reason, NVS schema를 기록한다.
2. relay가 OFF이고 gate FSM이 IDLE인지 확인한다.
3. signed manifest의 board, flash layout, protocol 범위, size, digest, signing key를 확인한다.
4. inactive slot에만 기록하고 pending boot로 전환한다.
5. 재부팅 뒤 제한된 health window에서 relay default OFF, self-test, version/boot ID,
   Wi-Fi와 최소 하나의 update control plane을 확인한다.
6. 모든 조건을 만족한 뒤에만 valid mark한다. timeout, crash, reset loop 또는 health 실패는
   이전 slot rollback을 기대한다.
7. MQTT 차단 상태의 periodic HTTPS와 Backend/DNS 차단 상태의 authenticated local AP를
   별도로 시험한다.

The automatic Target path aborts an artifact transfer after 30 seconds without
progress or five minutes total. After a pending image fails health and the
bootloader returns to the prior slot, the exact failed version is quarantined;
leaving the same manifest published must not trigger another installation.
Recovery publication must therefore use a strictly higher SemVer version, not
the failed version with only different build metadata.

## 3. Mobile canary 절차

1. 기존 APK version code, signing certificate digest, credential/preferences schema를 기록한다.
2. BLE scanner, foreground service, WebView를 각각 고장 주입해도 cold start/resume/settings의
   update control이 접근 가능한지 확인한다.
3. primary endpoint를 503으로 만들고 secondary metadata/APK를 사용한다.
4. metadata signature, APK SHA-256, APK signing certificate를 installer 호출 전에 확인한다.
5. 사용자 거부, 저장 공간 부족, 50% 다운로드 중단, 손상 APK에서 기존 앱과 credential이
   유지되는지 확인한다.
6. 설치 후 first-run health와 N/N-1 Target 통신을 확인한다. Android의 사용자 설치 승인은
   우회하지 않는다.

## 4. 중단·rollback 판단

다음 중 하나면 rollout을 즉시 중단한다.

- relay가 boot/OTA 중 ON이 되거나 one-shot cutoff가 지연됨
- artifact signature/digest 불일치가 installer/boot 선택 전에 차단되지 않음
- Target health 실패인데 valid mark되거나 이전 slot이 부팅되지 않음
- mobile 설치 실패가 기존 APK/credential을 손상함
- periodic HTTPS, local recovery, stable mobile fallback 중 약속된 경로가 막힘
- N/N-1에서 update UI 또는 OTA control plane이 접근 불가

Target은 새 slot valid mark 전이면 재부팅해 bootloader rollback을 관찰한다. valid mark 뒤
문제가 발견되면 마지막 정상 signed image를 새 OTA로 재배포하며 임의 partition erase를 하지
않는다. Mobile은 마지막 정상 서명 APK의 stable fallback URL을 제공하고 사용자의 package
installer 승인을 받는다. DB/NVS migration은 expand 단계 또는 copy-on-write 사본으로 되돌린다.

## 5. 장애별 운영 경로

| 장애 | 1차 | 2차 | 성공 증거 |
|---|---|---|---|
| MQTT 장애 | Target periodic HTTPS | authenticated local AP | install→reboot→health→valid |
| primary NAS 장애 | secondary distribution | local AP 또는 stable browser landing | 검증된 artifact 설치 |
| Target reset loop | bootloader rollback | local AP로 정상 image | 이전 version boot + health |
| mobile scanner/WebView 장애 | settings/manual update | stable browser landing | installer + new first-run health |
| 잘못된 signature/hash | 배포 중단 | signing pipeline/key ID 감사 | installer/boot 미호출 |
| 전원 차단 | 이전 정상 버전 부팅 확인 | local recovery | slot/APK 보존 증거 |

## 6. 필수 telemetry와 사후 기록

secret 원문 없이 component, device ID, current/target version, protocol range, stage, attempt,
error code, artifact digest, signing key ID, boot/install confirmation, rollback reason, boot ID를
기록한다. 성공은 upload/PUBACK/download가 아니라 mobile install 또는 Target
install→reboot→health confirmation이다. 모든 실기기 결과는 `wiki/hardware_test.md`에 날짜,
commit/build, 반복 횟수와 원시 증거 위치를 추가한다.

Recovery 자동 판정은 `ota/recovery-matrix.json`의 allowlist outcome/action과 안전한 상태 전이만
허용한다. 운영자가 임의 자유 텍스트나 partition/APK erase 같은 파괴적 동작으로 바꾸지 않으며,
새 recovery 동작이 필요하면 schema, semantic mapping, 장애 주입 negative test를 같은 PR에서
먼저 갱신하고 재검토한다.

## 7. 2026-08-24 personal automatic publication evidence

- Target main run `32668550147` published exact H11
  `2.1.242+main.g7a55a66` to both immutable and latest NAS paths. Independent
  Ed25519, AES-256-GCM, plaintext/image and 16 MB N16 capacity checks passed;
  each 7,340,032-byte slot retained 5,543,952 bytes.
- The physical Target proved the corrected encrypted pipeline through complete
  signed H10 download, inactive-image verification and reboot, and currently
  runs exact H11 with MQTTS and an `already current` periodic check.
- The retained boot path did not expose `PENDING_VERIFY` health-window/valid
  logs. Operators must therefore record this as install/reboot evidence only;
  health-valid and rollback remain separate mandatory trials.
- A stalled pre-fix Android publisher can hold the per-main concurrency group
  and keep a corrected run pending. After confirming its exact old SHA/job and
  that a newer main run exists, cancel only that obsolete mobile workflow run;
  never cancel a Target publisher or an unidentified run. The bounded publisher
  must then finish both NAS roots and public HTTPS equality before APK install.
