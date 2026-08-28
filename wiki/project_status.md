---
title: smart-gatekeeper current project status
type: reference
project: smart-gatekeeper
status: active
updated: 2026-08-29
source_of_truth: true
applies_to:
  - firmware
  - android
  - backend
  - operations
---

# 현재 프로젝트 상태

> 관측 기준: USB Target source 계보 `21e71d1c8faf469d101a477207276a80297873c8`, Android production-signed `1.0.0-g40852b7` (`versionCode=22401`). Fold7의 main-screen action-2는 authenticated GATT terminal success와 UI `문이 열렸습니다 (4585ms)`를 반환해 이전 stale-app `PROTOCOL_INCOMPATIBLE`을 재현하지 않았다. Exact-main Target `2.1.291+main.g89e047c`는 NAS에 게시됐지만 연결된 Target 설치·재부팅 health는 아직 serial 권한 경계로 확인하지 못했다. relay contact/load, actual door, post-fix screen-off action-1, sensor 및 rollback Gate는 계속 열려 있다.
>
> 이 문서는 **저장소 최신 구현**, **검증 증거**, **현장 배포 상태**를 분리해 보여 주는 시작점이다. 세부 계약은 링크된 문서와 코드를 따른다.

## 2026-08-28 external Synology backend CI deployment candidate

- The backend is already running on the personal Synology NAS, but the
  new lane is currently a local repository candidate rather than a deployed
  production system.
- The existing NAS SFTP-only identity remains suitable for firmware/APK artifact
  delivery but has no remote shell for Compose, migration or readiness work.
- The implementation and acceptance plan are documented in
  [nas_backend_external_deployment_plan.md](nas_backend_external_deployment_plan.md):
  the protected backend workflow now builds DS423+ `linux/amd64` API/DB images,
  publishes exact GHCR digests with provenance, signs a four-file release
  bundle, joins Tailscale with OIDC and invokes only `apply/status` through a
  forced SSH dispatcher. The NAS wrapper verifies signature, descriptor,
  Compose hashes, fixed repositories/digests/schema, existing volumes and local
  secret files before backup-first migration, then requires loopback and public
  `/ready` before recording the current release.
- Host validation currently passes the focused deployment-contract tests, Compose
  rendering, shell syntax, trusted-input completeness and the 35-check backend
  commercial contract. Separate bootstrap work has prepared the NAS wrapper,
  tailnet policy and protected GitHub Environment as recorded below. No GHCR
  image, workflow deployment, database migration, Compose cutover or reverse
  proxy change has occurred.
- Before first adoption the owner must separately admit the protected-workflow
  policy rotation, pass the hosted tagged-runner status preflight, and stop the
  legacy API/DB in an approved change window. The exact live mounts and first
  off-NAS isolated restore are already evidenced below. The wrapper rejects another running
  project holding the MariaDB volume or API port and never attempts a blind DB
  rollback.
- Owner-provided live container inventory now identifies legacy
  `gatekeeper-api` from local image `smart_gatekeeper-api` with wildcard IPv4
  and IPv6 host port `8000`, and `gatekeeper-db` from mutable tag
  `mariadb:10.11` with no published DB host port. This confirms the exact two
  containers that must be stopped during first adoption. Their exact mounts and
  volume identities were subsequently resolved as recorded below; automatic
  deployment is still not authorized until the backup/restore and live-control
  Gates close.
- A subsequent mount inventory fixes the DB data volume as
  `smart_gatekeeper_mariadb_data` and the APK source as the existing bind path
  `/volume1/docker/smartbox_ota/gatekeeper_apk`. The API is a live source bind
  from the NAS repository and has no `/var/lib/smart-gatekeeper` mount; its
  default `target_config.json` therefore lives under `/app` and requires a
  metadata check/copy into the new state volume. Existing DB init-SQL binds are
  not persistent data and will be replaced by the immutable DB image/migration
  runner.
- The candidate no longer assumes a new `gatekeeper_runtime` account. Both DB
  initialization and API connection now require explicit `DB_RUNTIME_USER` so
  the first adoption can retain the exact existing account. Passwords remain
  unprinted and will be migrated to NAS-local secret files.
- Readback now confirms `DB_NAME=smart_gatekeeper` and
  `DB_RUNTIME_USER=gatekeeper_user`. The legacy target config is a root-owned,
  mode `0555`, 135-byte regular file at `/app/target_config.json` with SHA-256
  `c5668365bd130ec42c7f49aafc53491b1a6ad3a3eb4858f3215b83de3505ece9`;
  the successful bootstrap copied those exact bytes into the prepared API
  state volume without changing the running legacy API.
- Secret-semantic readback confirms the API DB password matches the DB account,
  required DB/MQTT/API/operations/ACL values are set, both active P-256 scalars
  have valid shape, and the personal administrator password is active with a
  valid length. Administrator mTLS identities and the ACL transition signer are
  empty, so the transition pair remains disabled. No secret value or secret
  hash was recorded.
- The production API now reads the active personal administrator credential
  from a NAS-local file secret; ambiguous direct-plus-file configuration and an
  unreadable file fail closed. The one-time
  `bootstrap_legacy_synology.sh` candidate validates the exact observed legacy
  containers/mounts, stages existing values without printing them, copies the
  exact target config, and creates bind-backed API/APK/backup volumes without
  stopping the live project. Owner execution now reports successful preparation:
  the legacy containers remained unchanged, all three new external volume names
  were created, and the copied target config retained the expected SHA-256.
  This is NAS layout evidence only; DB migration, new containers and cutover
  have not run.
- Independent read-only verification now passes all 14 secret-file contracts,
  the exact runtime key set, all three external volumes and unchanged running
  legacy containers. The DB ledger contains migrations `002` through `007`;
  one active credential/grant has latest snapshot `313` and an exact applied
  ACK at `313`. The three legacy tenant rows report no `public_key` mode because
  the personal bootstrap intentionally retains its mapped row in `dual` mode.
  Exact tenant/door/Target boolean correlation remains the final lookup-disable
  check before the separate owner decision. Owner execution subsequently passed
  every boolean: feature flags, target-auth scope, dual/public tenant mapping,
  active ACL tenant, exact active credential/grant and snapshot/ACK hash/version
  all match. Latest snapshot and applied ACK advanced together to `314` during
  the live readback. The technical path for disabling legacy lookup is present;
  owner approval and off-NAS restore remain mandatory before cutover.
- Owner size readback reports the current `smart_gatekeeper` database at
  2,686,976 bytes over 20 tables, with a 1,638,400-byte largest table. The
  repository now contains a no-cutover NAS dump/inventory helper plus WSL
  digest/authentication/encryption and exact-digest isolated-restore harness.
  Twelve focused deployment tests and the 35-check repository contract pass;
  owner execution subsequently created a consistent 792,678-byte SQL dump and
  bundle SHA-256 `d2321993a1858ec053c614bf6aecb212012f2dd25db59ff2fd49ed42056f418d`
  for deployed source `7c2764a1a16492ec1620079c8211b47287b1b3fd`, while both legacy
  containers stayed running. The root-only NAS copy and temporary owner export
  were transferred with exact sidecar validation. WSL produced a mode-0600
  AES-256 GPG copy whose streamed decrypt hash matched the NAS bundle, then
  restored the dump into pinned MariaDB on IPv4 localhost. Exact schema/content
  inventory passed in 1.680 seconds with 316 ACL snapshots, one credential, one
  target boot-state row and three tenants. This closes the first isolated
  restore Gate only; two disposable labs and plaintext copies await owner
  cleanup, and recurring off-site 3-2-1 backup remains open. Owner subsequently
  authorized cleanup: both WSL containers/volumes and all WSL plaintext
  bundle/work files were removed, while the encrypted bundle, authenticated
  manifest, restore result and keys were retained mode `0600`. NAS owner-home
  export deletion subsequently passed through interactive SSH; all temporary
  plaintext copies are now removed. The NAS root-only backup remains retained
  by design.
- The initial GitHub control-plane readback confirmed `origin/main` equaled local main at
  `21e71d1c8faf469d101a477207276a80297873c8`, the environment token is
  authenticated as repository ADMIN, and `production` already has owner review
  plus a `main`-only branch policy. Backend deploy variables/secrets were absent
  at that snapshot; their later bounded setup is recorded in the 2026-08-29
  section. The trusted workflow policy still requires a separate exact-candidate
  authorization rotation.

## 2026-08-28 current WSL/Fold7 core action-2 check

- WSL-attached CH343 Target booted the local personal-production image, restored
  saved Wi-Fi at `192.168.35.18`, connected exact per-Target MQTTS, applied
  signed ACL v303, and started the enabled GATT/iBeacon service. Windows-hosted
  ADB kept the authorized Fold7 connected independently.
- The installed app's main WebView reported backend status `승인됨` and exposed
  the enabled `문 열기` button. Native health was `HEALTHY`, BLE owner
  `native_gatt`, and local consent `local_keystore_authenticated`.
- One main-screen action-2 tap connected to the Target, discovered the service,
  and enabled Target Hello, Challenge and Result indications. It then closed in
  about 1.8 seconds with UI result `수동 출입 실패: PROTOCOL_INCOMPATIBLE`.
  Target serial recorded only the accepted connection: there was no proof-verification evidence,
  `AUTH_PENDING`, `RELAY_HOLD`, relay ON/OFF or terminal Result OK.
- The installed `3cf6eaa` and current Target source still have protocol/framing
  version 1 and no diff in the core Android/Target GATT protocol files. The
  public error can also represent a rejected Target Hello or unexpected message
  type, so the exact on-wire cause is unresolved and must not be called a simple
  version-range mismatch without packet/transport diagnostics.
- A preceding dashboard `1-Tap 수동 로컬 개방` control was found in the exact
  installed source to enqueue the action-1 WorkManager retry path, not the
  terminal action-2 executor. It remained `Target Result: NONE` during the
  bounded observation and was not used as action-2 success evidence.

Current core manual-open acceptance is therefore **FAIL at the authenticated
protocol boundary**. The non-retryable result was not repeated. This run safely
failed before relay actuation and provides no physical contact or door-motion
evidence.

## 2026-08-29 production-app action-2 recovery

- Windows ADB showed the connected Fold7 still running stale
  `1.0.0-g3cf6eaa` / 21701. The NAS production APK
  `1.0.0-g40852b7` / 22401 was downloaded and independently matched its
  55,786,649-byte length, SHA-256
  `2790c2844c62881a9fc3e27c1632514fb2ba82080deb12d2ff3775373b63468d`
  and signer-certificate SHA-256
  `8bdbcf86c2530d424758a37b5a678de02b8f35587143d820c730b83cfe1d7ba0`.
  `adb install -r` preserved the approved user and native credential state.
- One main-WebView `문 열기` action-2 completed with terminal UI
  `문이 열렸습니다 (4585ms)`. Native health remained `HEALTHY` with last
  latency 4585 ms; Android recorded successful characteristic writes,
  indications and a normal local GATT disconnect. The prior
  `PROTOCOL_INCOMPATIBLE` was not reproduced.
- This closes the currently connected authenticated mobile-to-Target action-2
  software/FSM outcome. It does not prove physical relay contacts/load, actual
  door motion, AJ-SR04T threshold, repeated latency, screen-off action-1 or OTA
  rollback.
- Exact-main run `33199155599` separately published signed encrypted Target
  `2.1.291+main.g89e047c`. Publication is not installation: current Target
  install, reboot and health remain unconfirmed because this shell's group list
  has not refreshed `dialout` access to `/dev/ttyACM0`.

## 2026-08-29 backend NAS GitHub CI policy connection

- Backend-NAS feature PR #186 passed fresh hosted trusted, OTA and backend
  MariaDB checks at merge-connected head `732e672`, then merge-commit merged as
  exact main `89e047c2416de6924ee4b7aff4daf4250d55f907`.
- Bridge PR #187 and final admission PR #188 connected and authorized the exact
  82-path feature bundle without rebasing or squashing. This immediate final
  rotation removes both `25562d1` transition identities and pins only
  `current-main-baseline` to actual merged main `89e047c`.
- The GitHub `production` Environment has owner review and a `main`-only branch
  rule. Exact NAS variables, pinned SSH host key/private key, release signer and
  both Tailscale OIDC secret names are present; secret values were never read
  back. The narrow tailnet grant is saved, and a WSL user-owned source passed
  private forced `status` plus arbitrary-command rejection.
- Manual exact-main run `33199183911` then exercised the ephemeral
  `tag:sgk-github-deploy` runner through Tailscale and the pinned forced SSH
  endpoint. Its retained evidence is exactly `status=not-deployed`; all
  publication and `apply` jobs were skipped.
- The private CI transport Gate is therefore closed, but the new stack is not
  deployed. Database migration, legacy-container cutover, API readiness,
  rollback and external service evidence remain separate production Gates.

## 2026-08-26 issue #179 Bluetooth-state recovery candidate

- Android's modern implicit-broadcast limits make a manifest-only
  `ACTION_STATE_CHANGED` receiver unreliable. The candidate registers a native
  process-lifetime receiver from `GatekeeperApplication`, independently of the
  Flutter UI/isolate, while the existing foreground service keeps the process
  resident.
- Persistent registration intent survives a Bluetooth-OFF registration attempt;
  disable intent is committed before best-effort platform stop. The first
  observed `STATE_ON` reconciles one exact PendingIntent scan by stop-then-start.
  OFF/TURNING/repeated-ON and disabled states do not dispatch work, and the state
  receiver never invokes action 1 directly.
- Seven focused Python source/pocket contracts, an expanded 174-test mobile/
  OTA/trusted suite and the Android Gradle `:app:testDebugUnitTest` build
  (209 tasks) passed locally. The phone remains disconnected, so OFF→ON
  broadcast delivery, OS first match and terminal action-1 `ARMED` are
  explicitly pending connected acceptance.

## 2026-08-26 exact-main 285 ACL-before-BLE connected acceptance

- PR #176 and both trusted-policy PRs merged; final source/policy main is
  `577533186ba5b40ca13fc47aadf51747e2057b73`. Run `32916682601` built,
  production-signed, encrypted and atomically NAS-published it as
  `2.1.285+main.g5775331`.
- The connected 282 Target accepted the signed manifest, downloaded the exact
  1,849,860-byte encrypted artifact, verified the inactive image and rebooted
  into exact 285. Saved Wi-Fi returned at `192.168.35.19`; exact per-Target
  MQTTS, retained diagnostics/config and signed ACL delivery recovered.
- The corrected boot order was observed directly: `BLE waiting for active ACL`
  appeared before MQTT connection; signed ACL v203 applied; only then did the
  Target start GATT, iBeacon and the enabled Hardwareless transport. This closes
  the Target-side startup-order acceptance for issue #175.
- A following 30-second connected interval remained stable and periodic HTTPS
  OTA reported `already current: 2.1.285+main.g5775331`. No pending-image
  health-window/valid-mark trace appeared, so issue #172 remains open and this
  is not rollback proof.
- Android is disconnected, so the fixed Target has not yet received a new
  Samsung screen-off first match. AJ-SR04T and relay contact/load are absent;
  ultrasonic threshold, electrical contact and actual door movement remain
  unclaimed. Android Bluetooth OFF->ON re-registration is tracked separately by
  issue #179.

## 2026-08-26 exact-main 282 connected controls and boot ACL race

- Target and production-signed Android were aligned to exact main
  `3cf6eaa925e5ef38ee7d538a6d7a1cf8720ad219`: Target
  `2.1.282+main.g3cf6eaa`, Android `1.0.0-g3cf6eaa` / 21701. The APK hash,
  embedded source and production signer matched before replacement install.
- The actual main-screen action-2 completed authenticated GATT, Target relay
  command ON then timer-bound OFF, and terminal UI success in 4,636 ms. A
  separate foreground action-1 completed `Presence -> ARMED` in 4,688 ms once
  the Target ACL was active. These are board/FSM/GPIO command results, not
  relay-contact voltage, actuator or actual-door evidence.
- A controlled Home + Dozing + secure-keyguard attempt held the Target absent
  for 15 seconds and then booted it. Android received the first match with
  `screen_interactive=false`, RSSI -51 and 5.37 ms callback latency, connected
  and configured GATT, but failed after about 3.4 seconds without `ARMED`.
- Source and runtime order identify the race: `TargetAclManager::begin()` must
  leave a stored ACL inactive without trusted wall time, while setup advertised
  iBeacon/GATT before MQTT delivered the fresh signed ACL. Issue #175 defers
  personal Hardwareless BLE until `hasActiveAcl()` becomes true, starts it once,
  and leaves non-Hardwareless immediate beacon startup unchanged.
- Android has now been disconnected. Hosted CI, merge, exact-main Target boot
  order verification and a new physical screen-off repetition remain pending.
  AJ-SR04T and relay/contact/load are absent, and issue #172 still owns
  pending-image valid-mark/rollback proof.

## 2026-08-26 exact-main 281 OTA acceptance and current mobile boundary

- Runs and atomic NAS evidence published exact main
  `082e431b50cd569ab0f557d463305e3b48ad27cc` as
  `2.1.281+main.g082e431`. The encrypted artifact is 1,849,444 bytes with
  SHA-256 `ea17493b...ab5566`; the signed manifest SHA-256 is
  `d936f157...b92eda9`.
- The installed pre-fix 493 image accepted that manifest but reproduced the
  second-handshake Mbed TLS `-9984` failure before any inactive write. A bounded
  COM5 bootstrap then wrote bootloader, the reviewed 16 MiB partition table,
  `boot_app0` and exact-source 082 firmware at the documented offsets. It did
  not run `erase_flash` or write `firmware.factory.bin`; every region passed
  esptool readback verification and saved Wi-Fi/security NVS remained present.
- From that corrected downloader, the independent periodic HTTPS path accepted
  the signed 281 manifest, started the exact 1,849,444-byte encrypted download,
  verified the inactive image and rebooted. Exact CI identity
  `2.1.281+main.g082e431` then restored `192.168.35.19`, exact per-Target MQTTS,
  ACL v188 and enabled GATT. A later periodic check reported already current.
  This closes the #166 TLS reuse defect; #160 is closed as superseded.
- The OTA boot never logged `pending image health window started` or `running
  image marked VALID`, including after a full 30-second healthy interval. Issue
  #172 owns the distinct production N16 bootloader pending-verify/rollback Gate.
- On the exact 281 Target, a new Samsung screen-off first match arrived at RSSI
  -53 with `screen_interactive=false`. Android connected, discovered services
  and enabled all three indications, but WorkManager returned `FAILURE` after
  about 3.4 seconds and Target never entered `ARMED`. The secure keyguard blocks
  the redacted native health screen and current manual-open retest until the
  user unlocks the phone. The earlier 493 action-1/action-2 successes remain
  valid historical connected evidence but do not override this failed current
  repetition.
- AJ-SR04T and relay/contact/load remain physically absent. Sensor threshold,
  relay voltage/contact timing, actual door movement, automatic rollback and
  final wall-install acceptance are not claimed.

## 2026-08-26 exact-main Android action acceptance and Target OTA TLS blocker

- Main run `32903378187` built, production-signed and atomically published exact
  source `1e3dfcf32c7b3ef88121fb824c35d81d2f6d40a7` as Android
  `1.0.0-g1e3dfcf` / `versionCode=21001`. Downloaded APK SHA-256
  `cbf8497c...9243a5b` matched its signed manifest, embedded the exact source
  SHA and retained production signer SHA-256 `8bdbcf86...e1d7ba0`.
  `adb install -r` preserved the original first-install timestamp, app data and
  AndroidKeyStore-authenticated native state.
- The actual main-screen `문 열기` action reached HA `AUTH_PENDING` at 07:14:20,
  Target relay-command ON and HA `RELAY_HOLD`/door-open at 07:14:23, timer-bound
  OFF/`COOLDOWN` at 07:14:24 and `IDLE` at 07:14:29 without a Target reset.
  This passes the connected action-2 board/GPIO command path; no physical relay
  contact or door mechanics were attached.
- With the app on Home and the Samsung phone still `Dozing`, one authenticated
  Target reboot created a fresh beacon. Native WorkManager completed successfully
  and HA independently observed `AUTH_PENDING` at 07:17:33 then `ARMED` at
  07:17:36. The bounded Flutter owner-exclusion path produced one ranging attempt
  about every 30 seconds rather than the earlier immediate retry storm. Issues
  #156 and #158 are closed by this connected evidence.
- Target run `32903378312` published signed exact-main firmware
  `2.1.275+main.g1e3dfcf`, but the installed 493 Target accepted the manifest and
  then failed the immediately following artifact TLS handshake with Mbed TLS
  `-9984`; it did not write or boot the new slot. The NAS serves a valid longer
  Let's Encrypt chain rooted at the provisioned ISRG Root X1. PR #161 changed
  the two clients to sequential lifetime, and run `32907218154` then published
  `2.1.278+main.gc5d79eb`; the connected Target again accepted the signed
  manifest and failed the second artifact handshake with the same `-9984`.
  That disproves client destruction alone. Issue #166 instead requires the
  signed artifact to use the exact manifest HTTPS authority and reuses the
  already CA/hostname-verified HTTP/1.1 keep-alive connection; no certificate
  bypass or insecure fallback is allowed.
- AJ-SR04T and a physical relay/contact fixture are still absent. Therefore
  `ARMED -> distance <= 80 cm -> RELAY_HOLD`, electrical contact timing,
  pending-image valid marking, rollback and final wall-install acceptance remain
  open evidence Gates.

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
  closed; issue #156 then tracked the missing terminal action-1 result. The later
  exact-main Android `1e3dfcf` trial documented above reached terminal `ARMED`
  and closed #156, superseding this earlier failure classification.
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

1. Issue #172에서 production N16 bootloader/OTA data가 새 OTA image를 `PENDING_VERIFY`로 표시하고 firmware가 30초 health window 뒤 valid mark하는지, 실패 시 이전 slot으로 rollback하는지 별도 확인한다. 281의 install/reboot/current-version 성공만으로 이 Gate를 닫지 않는다.
2. 약신호 compatibility release를 동일 위치에서 홈 AP와 가까운 AP로 A/B하고, 홈 위치 RSSI를 최소 `-75 dBm` 이상으로 개선한 뒤 Wi-Fi/DHCP/MQTTS와 broker/WAN 장애 자동 복구를 실측한다.
3. GPIO3 Active-LOW relay, High-Z OFF, ECHO 5 V 보호, 전원 강하와 반복 구동을 물리 검증한다.
4. Samsung/OEM 화면 OFF, Activity 종료, OS background 제한을 release artifact로 반복 검증한다.
5. Personal Hardwareless RC의 compile/runtime enable, current Android APK의 493 Target action-2 relay-command와 한 번의 screen-off action-1 `ARMED`는 관측했다. Exact 281 반복은 OS first-match/GATT indication까지 간 뒤 WorkManager `FAILURE`로 끝났으므로, 잠금 해제 후 durable reason을 읽고 current manual action-2와 Samsung/OEM screen-off·process-killed pocket action-1의 반복/latency 분포를 다시 검증한다. Commercial/default compile-OFF와 local kill switch는 보존한다.
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
