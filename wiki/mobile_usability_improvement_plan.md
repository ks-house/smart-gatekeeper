# Mobile usability improvement plan

- Last updated: 2026-08-30
- Planning baseline: annotated tag `baseline-mobile-usability-2026-08-30`
- Exact source: `38fe3b164e6615a9b727910a7776de5d5747eec7`
- Published identities at the baseline: mobile `1.0.0-g38fe3b1` build `30501`,
  Target `2.1.359+main.g38fe3b1`

## 0. Implementation progress

- 2026-08-30 P0 (`#265`, merged by PR #266): implemented a native
  Home/Activity/Settings shell, credential/public-key-bound personal status and
  lifecycle APIs, bounded privacy-safe local activity, terminal-state Android
  notifications, and a separate advanced diagnostics route.
- The transitional WebView now projects the same credential-bound status and no
  longer calls retired `/user/me` as an authority. Its broken administrator
  `/api/v1/logs` history affordance was removed.
- Backend ACL API tests (9), Flutter analysis, all 49 Flutter tests and the
  hosted Android Gradle/APK canary passed before merge.
- 2026-08-30 P1 source candidate (`#269`): added generated ko/en resources for
  the normal shell, explicit semantics for live readiness/support controls, a
  normal-settings update experience with installed/available version,
  download progress and replacement first-run health, plus a preview-first
  bounded support report whose copy action is disabled until explicit consent.
  The report contains opaque event correlation and excludes tenant label/name,
  unit, MAC, token, key and proof material.
- Phone installation, connected screen readback, notification delivery,
  foreground/screen-off Target trials, ultrasonic/contact actuation and actual
  door movement remain pending. They are not implied by this source status.

## 1. Goal and evidence boundary

The next mobile iteration has one product goal: a resident should understand
whether Smart Key is ready, what just happened at the Target, and the one next
action to take without reading BLE/GATT/MQTT terminology.

The baseline tag records source and CI-published artifact identity. The phone is
currently disconnected, so it does **not** prove APK installation, connected
visual behavior, screen-off repetition, sensor/contact actuation, or actual door
movement. Android's package installer confirmation also remains a platform
security boundary; this plan does not promise unattended APK installation.

## 2. Current implementation audit

### 2.1 Implemented capabilities to preserve

| Area | Current source state | Product treatment |
|---|---|---|
| First-run capability Gate | Versioned disclosure, missing-permission checks, dedicated battery exemption, recovery shell | Keep behavior; simplify copy and next actions |
| Background presence | Filtered native PendingIntent wake, boot/package re-registration, durable WorkManager/GATT state | Preserve; do not claim force-stop recovery or OEM reliability without physical evidence |
| Local credential and access | AndroidKeyStore credential, Backend enrollment, signed Target ACL, action-1 ARM and terminal action-2 | Preserve security contract and OTA independence |
| Foreground Target visibility | One-second projection of recent detection and durable worker state | Promote to the primary user journey with plain-language states |
| Settings | One `Smart Key 설정` route with `Smart Key` and `진단·튜닝` tabs | Keep one route; separate user controls from engineering controls |
| Mobile update | Signed primary/fallback manifest, APK size/hash/package/certificate checks, installer handoff, first-run identity health | Preserve fail-closed behavior and old-app/credential retention |
| Privacy foundation | Redacted app logger and Backend consent-bound support export primitive | Reuse for a user-visible support flow |

### 2.2 Mobile-facing items that are not implemented or not wired

| ID | Priority | Gap and source evidence | Required outcome |
|---|---|---|---|
| MU-P0-01 | P0 | The WebView home calls `/api/v1/user/me` through a retired `device_id`/`ble_device_mac` lookup, while local access is authorized by a distinct Keystore credential and signed Target ACL. `EnrollmentState` exists but is used only by tests. | One authenticated, credential-bound status contract returns `unregistered`, `pending`, `approved`, `revoked`, or `expired`, tenant/door display data, ACL version/expiry, and a safe next action. Retire the legacy device-ID authority after migration. |
| MU-P0-02 | P0 | The operational screen exposes raw `Local GATT`, `Native Worker`, feature flags, kill switch, protocol phase timings and `ARMED n ms`. `DoorState` exists but is not wired into the production UI. | A native user Home shows `준비 확인 → Target 감지 → 인증 → 접근 대기 → 문 열림 확인/결과 불명/실패`, one primary action, last event time, and reason-specific recovery. Raw metrics move to diagnostics. |
| MU-P0-03 | P0 | Background detection can wake and journal a session, but the user has no durable, plain-language access-result notification or foreground activity feed. Foreground visibility requires opening settings and polling the health bridge. | Post privacy-safe local notifications and persist a bounded activity timeline for detected/armed/confirmed/unknown/failed. Never say “문 열림” before terminal Target evidence. |
| MU-P0-04 | P0 | The WebView “최근 출입 감지 이력” calls the administrator-only `/api/v1/logs` endpoint without its required admin session and tenant header, then silently ignores failure. | Remove the false affordance until a user-scoped endpoint exists, then add a credential-bound, tenant-filtered, paginated history API and safe text rendering. Do not expose the admin audit API to the app. |
| MU-P0-05 | P0 | Recovery lists missing requirements, but several actions and explanations are mixed Korean/English and generic settings links do not map each failure to one corrective action. Bluetooth-return re-registration remains issue #179. | Map every blocked reason to one action: enable Bluetooth/location, grant the exact permission, open the dedicated battery/OEM page, retry wake registration, update, or contact support. Preserve manual local and updater access. |
| MU-P1-01 | P1 | The app declares `ko/en`, but most strings are hard-coded and recovery is bilingual. There is no generated localization catalog or complete locale test. | Move user strings and reason messages to generated ko/en resources; adopt system locale first and provide an in-app language selector only if field feedback requires it. |
| MU-P1-02 | P1 | Some screens have semantics, but the complete navigation, icon/emoji labels, focus order, contrast and large-text layout are not accepted. | TalkBack traversal, non-color-only status, 200% font, landscape/foldable and minimum touch-target acceptance for every user route. |
| MU-P1-03 | P1 | The updater verifies and installs safely, but the normal user does not get one consolidated current version, available version, progress, installer-cancel/failure, first-run health and retry history view. | Add a plain update card with current/available version, progress, verified/failed reason, retry/fallback state and post-replacement health. Keep Android confirmation explicit. |
| MU-P1-04 | P1 | Redacted logging and a Backend export primitive exist, but there is no app preview/consent/share-to-ticket flow. | Build a bounded redacted support report preview with explicit consent, share/copy action, opaque session/event IDs, and no name/unit/MAC/token/key/proof. |
| MU-P1-05 | P1 | Current access latency is visible as a single raw number. Connected evidence is sparse and cannot distinguish UX delay from GATT phases reliably. | Record a bounded rolling sample, show only a user phrase such as `출입 준비 완료`, and keep phase timing in diagnostics. Measure 10 connected foreground and 10 screen-off trials before changing protocol timing. |
| MU-P2-01 | P2 | Approval push described in the old scenario is not implemented; there is no Firebase dependency or approval notification client. | After the authoritative enrollment contract exists, add privacy-safe approval/revocation notification or bounded status refresh. Do not use push as the only revocation authority. |
| MU-P2-02 | P2 | Multi-door/multi-tenant selection, phone replacement, lost-phone revocation and credential transfer are not complete end-user journeys. | Add explicit door selection and credential lifecycle flows only after the single-owner core loop meets its usability and physical Gates. |
| MU-P2-03 | P2 | iOS is outside the current Android production build and evidence path. | Keep iOS as a separate product decision and backlog; do not let it delay Android core-loop usability. |

## 3. Recommended information architecture

The normal app should have three user destinations. Engineering controls remain
available, but not in the normal path.

1. **홈**
   - readiness summary: `사용 가능`, `확인 필요`, or `사용 불가`
   - latest Target/access state and time
   - one context-sensitive primary action: `설정 완료`, `등록 요청`,
     `다시 연결`, `문 열기`, or `결과 확인`
2. **활동**
   - bounded privacy-safe detection/access/update timeline
   - clear distinction between `접근 대기(ARMED)` and `문 열림 확인`
3. **설정**
   - permissions/background, credential/door, update, language, support
   - `고급 진단` behind an explicit secondary entry; worker phases, RSSI,
     feature flags and Target tuning never compete with the primary action

The hosted WebView can remain for low-risk content and transitional enrollment,
but it must not be the authority for credential status, access result, update
trust, or recovery. Those states belong to the native shell and authenticated
Backend contracts.

## 4. Delivery plan

### Phase 0 — baseline and connected walkthrough

- Keep `baseline-mobile-usability-2026-08-30` immutable.
- Reconnect the Samsung device, install the exact baseline APK without clearing
  app data, and capture the Home/settings/recovery/update screens.
- Run one foreground and one screen-off walkthrough to establish factual labels
  and latency, without treating two trials as reliability acceptance.

Exit: a redacted before-capture and an agreed five-step user journey exist.

### Phase 1 — truthful core Home (MU-P0-01, 02, 04)

Source status: **merged by PR #266, deployed on the NAS, and replacement-installed
in exact production app `1.0.0-g89164ce`; the connected Home/credential/ACL
readback passed.**

- Introduce a native `SmartKeyViewModel` that joins capability readiness,
  credential/enrollment state, latest Target session and update state.
- Wire the already-defined `DoorState` and `EnrollmentState` into production.
- Replace/remove the retired WebView identity and silently broken history
  affordances; add the credential-bound Backend status endpoint and migration.
- Move worker health, feature flags, latency phases and Target tuning to advanced
  diagnostics. Keep the single settings destination.

Exit: a user can tell, in one screen, whether access is ready and why; no stale
device-ID state can contradict the Keystore/ACL authority.

### Phase 2 — live result and recovery (MU-P0-03, 05; #179)

Source status: **activity and terminal notification are installed. One
foreground action-1 reached `ARMED`, and one screen-off first match completed
the GATT Worker and notification. Bluetooth OFF→ON and ordinary process-absent
wake remain open in #179/#51; truthful manual action-2 wording is #276.**

- Add a bounded native activity store and local notifications for meaningful
  state transitions.
- Add exact reason-to-action mapping and OS/OEM deep links where Android permits.
- Close Bluetooth OFF→ON native re-registration issue #179 and distinguish
  ordinary process reclaim from force-stop.

Exit: foreground and background trials both leave a truthful, inspectable result
and one recovery action; unknown outcomes are never auto-retried.

### Phase 3 — update, language, accessibility and support (MU-P1-01..04)

Source status: **merged by PR #270 and installed in the exact production app.
Generated ko/en normal-shell copy, live-region semantics, normal update status
and consented redacted support report have source/widget coverage; connected
settings/update readback passed, while TalkBack, 200% text and responsive-layout
acceptance remain separate.**

- Consolidate update status and first-run health in normal settings.
- Convert user copy to generated ko/en resources.
- Complete TalkBack, 200% font, foldable/landscape and touch-target work.
- Add the preview-first redacted support report flow.

Exit: the complete normal-user path passes widget/accessibility contracts and a
connected visual walkthrough without accessing engineering diagnostics.

### Phase 4 — performance and lifecycle expansion (MU-P1-05, MU-P2-01..03)

Source status: **bounded authoritative status refresh and privacy-safe GATT
phase diagnostics are installed. The phone is connected and one foreground
ARMED result plus one screen-off completion were observed, but the required 10
foreground plus 10 screen-off sample set has not been run. No latency SLO is
accepted. Multi-door/phone transfer and iOS remain separately gated scopes.**

- Measure first, optimize the dominant connected GATT phase second, and preserve
  N/N-1 plus OTA rollback throughout.
- Add enrollment notifications and multi-door/device lifecycle only after the
  personal-production core loop is stable.
- Treat iOS as a separately approved scope.

Exit: performance and commercial expansion have evidence-based targets rather
than adding complexity to an unproven core journey.

## 5. Acceptance metrics

| Metric | Candidate target | Evidence |
|---|---|---|
| First-run understanding | Ready/blocked state and one next action visible within 90 seconds | fresh-install screen recording + state fixture |
| Core navigation | Home to recovery/update/manual action in at most two taps | widget navigation contract + connected walkthrough |
| State truth | zero `confirmed`/"실제 문 열림" display without an independent authoritative physical event; Target `OPENED`는 command-executed로만 표시 | native ledger fixtures + negative/unknown cases |
| Foreground visibility | latest native event reflected within two seconds | bridge/widget timing test + connected observation |
| Latency | establish connected P50/P95 with 10 foreground and 10 screen-off trials; improvement candidate targets presence→ARMED P95 below 2.5 seconds without protocol weakening | redacted phase sample and Target terminal timestamps |
| Recovery | each blocker exposes exactly one safe next action; manual local and updater stay reachable | permission/Bluetooth/battery/force-stop matrix |
| Update | bad hash/certificate/version and installer cancel preserve old app and credential; successful replacement reports exact first-run health | existing OTA contract plus connected replace/cancel drill |
| Accessibility | TalkBack order, 200% font, foldable/landscape, contrast and touch targets pass | widget/golden checks + Samsung walkthrough |
| OEM reliability | release Gate remains the #51/#54 Samsung physical matrix, not synthetic ADB | signed evidence bundle |

The P95 latency target is a candidate objective, not a current promise. If radio
or Target conditions dominate, the plan reports that boundary instead of
weakening authentication, replay protection, result confirmation, or OTA.

## 6. Current issue register and implementation order

1. [#276](https://github.com/ks-house/smart-gatekeeper/issues/276) — source
   candidate now projects action-1 `SUCCEEDED` as armed and action-2 `OPENED`
   as command-executed across Home, WebView, advanced control and the bounded
   activity timeline. CI, exact-main signed publication and connected ko/en
   replacement-install readback remain separate acceptance Gates.
2. [#179](https://github.com/ks-house/smart-gatekeeper/issues/179) — run the
   Bluetooth OFF→ON registration recovery trial without opening the Activity.
3. [#51](https://github.com/ks-house/smart-gatekeeper/issues/51) — complete
   process-absent, 100-run Samsung/OEM, accessibility/responsive and repeated
   latency/battery acceptance.
4. [#54](https://github.com/ks-house/smart-gatekeeper/issues/54) — connect the
   sensor/relay/contact/door fixture and complete physical/operator/canary Gates.

Issue #262 is closed after authoritative credential status was installed and
visually confirmed. Epic #13 is closed after its redesign implementation and
bounded connected acceptance; its remaining commercial Gates are consolidated
into #51/#54/#48 rather than duplicated. Each follow-up PR must preserve
mobile/Target OTA contracts and keep source/test, CI publication, connected
runtime, Target terminal and physical-door evidence separate.
