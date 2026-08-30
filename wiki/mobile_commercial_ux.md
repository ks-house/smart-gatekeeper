# Mobile commercial UX and recovery contract (#51)

Last updated: 2026-08-30

## Capability shell

On first launch, the app presents a plain-language disclosure before making any
location, Bluetooth, notification, background-location, or battery-exemption
request. Consent is stored as a versioned local preference. After consent, the
app requests only missing foreground permissions, then Android's
`locationAlways` permission when applicable, and finally opens the dedicated
`ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` package intent. It never substitutes
generic application settings for that battery Gate. Deferring consent makes no
system request and enters the recovery shell; an OS denial remains visible there
with a retry action. Already-granted requirements are checked, never re-requested.
Manual recovery and verified update access remain available while automatic
background wake is degraded.

The first-run screen reports `Ready`, `Degraded`, or `Blocked` and keeps manual
local GATT, authenticated `manual_remote`, updater, settings, and redacted
diagnostics reachable without the scanner, WebView, or foreground service. A
denied permission therefore changes automatic-wake capability; it does not hide
recovery capabilities.

The main WebView shell and degraded recovery shell expose one shared
`Smart Key 설정` destination instead of separate local-control and diagnostics
pages. Its `Smart Key` tab retains manual local access, Target detection,
credential/fallback and independent OTA controls; its `진단·튜닝` tab retains
privacy-redacted RSSI, scan health, Target tuning and logs. Consolidation changes
navigation only and does not make advanced controls available without their
existing Backend authentication contract.

`BleWakeRegistrar` is invoked after the visible permission gate on fresh install,
persists the opt-in, and re-registers on `BOOT_COMPLETED` and
`MY_PACKAGE_REPLACED`. The status channel exposes the next action and allows a
user retry. Android force-stop, Bluetooth-off, revoked permissions, and OEM
restricted battery remain explicit limitations; synthetic ADB is not Samsung or
One UI acceptance evidence.

## Authenticated Target and durable result

The OS-filtered wake records the latest Target locator only in encrypted
no-backup storage. The locator is bound to a Keystore HMAC identity, credential
presence, Bluetooth enabled state, and a bounded freshness window. Manual retry
resolves this capability; it never sends a sentinel address such as
`TARGET_LOCAL`. Native retry returns an explicit durable queue result and session
ID, while the worker ledger preserves Target reason, transport status, retry
delay, and proof uncertainty. A successful UI state is shown only after the
Target result is durably committed; proof uncertainty is shown as `unknown` and
is never replayed automatically.

## Updater and release signing

The updater consumes the exact `ota/schemas/mobile-manifest.schema.json` field
set and verifies its `sgk-json-v1` Ed25519 signature against an APK-pinned key ID
and public key. Raw duplicate keys, escaped aliases, unknown/nested fields,
legacy field aliases, trailing data, insecure or identical endpoints, version
alias drift, unsupported Android SDK, and non-overlapping protocol ranges fail
closed. A manifest cannot carry or select its own trust root.

Primary and secondary metadata discovery are independent. Only the two APK URLs
covered by the verified manifest can be downloaded; a WebView link, remote
config value, or direct method call cannot install without that manifest. The
app writes a temporary file, validates exact size, SHA-256, package identity,
single signing certificate, and certificate SHA-256 before opening the Android
installer. Before permissions, BLE, WebView, scanner, or foreground service
startup, the replacement app reconciles the pending signed build/version,
installed `base.apk` SHA-256, and single current signer digest. Only an exact
match records first-run health and clears the pending identity; rejection,
storage failure, or an unchecked install remains explicit and never displays a
"latest" state. The old APK and credentials survive every pre-install failure,
and the verified candidate identity remains durable for recovery diagnosis.

CI pins both metadata URLs, updater key ID, and updater public key into the APK.
It runs Flutter and targeted native GATT tests before building and embeds the
exact source commit as a packaged Flutter asset. The already-protected
`scripts/ota_contract_gate.py` producer inspects the exact APK with
`apkanalyzer` and `apksigner`, requires package ID, version name, positive
version code, embedded commit, and exactly one certificate to match, then
creates and independently verifies the exact 22-field schema over those same
APK bytes. Pull requests, main-push canaries, and branch-dispatch canaries use
only the public RFC 8032 test seed/key and `.invalid` endpoints; every build job
reachable from those events contains zero production-secret expressions.
Production APK signing, updater runtime inputs, the manifest private key, and
production URLs are injected only after an exact-main source check and protected
contract/tests in the explicit `production` environment job. The production job
rebuilds and verifies the exact main APK; candidate Gradle/Dart code never
receives the keystore or production runtime inputs. Debug signing is never a
release fallback.

## Manual control compatibility

The normal user-visible **문 열기** button is a Backend remote-control action;
it is not the hands-free Local GATT action. The native shell creates a fresh
nonce, expiry and idempotency key, signs the fixed-width `SGKRMO01` canonical
request with the already-enrolled non-exportable AndroidKeyStore P-256 key, and
sends only the credential ID and signature to `POST /api/v1/door/open`. It never
embeds the shared Backend API key or the legacy tenant HMAC secret in this
control request.

The Backend requires an active credential, active tenant, an exact active grant
for the configured door, a valid signature and an unused durable nonce before
publishing the existing per-Target signed MQTTS force-open command. The prior
HMAC v2 envelope remains available for N-1 compatibility; a device-ID-only
request still returns HTTP `426` and has no database or broker effect. HTTP 2xx
means only that the Backend accepted the proof and received broker acknowledgement.
The app must not infer Target receipt, relay actuation or physical door movement;
a transport timeout is terminal `outcome unknown` and is never retried
automatically.

Hands-free pocket approach remains action 1 over Local GATT followed by Target
sensor assessment. Native action 2 remains an advanced diagnostic/recovery seam,
not the normal Home-button transport.

## Privacy and UI

The Home identity card is a per-phone account projection, not the shared ACL
tenant label. After public-key proof succeeds, the Backend resolves only the
legacy account row bound to that exact credential and returns its `name` and
`unit_number`; the app derives the visible label from those two fields. Multiple
residents may continue to share one household ACL tenant and door grant without
seeing the first resident's name. If a Backend cannot provide the credential-
bound fields, the app shows a generic/unavailable identity instead of falling
back to legacy `tenant_label` data that may contain another resident's PII.

Support diagnostics redact tenant/unit/device identifiers, URLs and query
strings, tokens, API keys, passwords, Bluetooth addresses, credentials, raw
proof material, and unbounded exception text at the `AppErrorLogger`
plain/error/debug output and its UI/IPC sinks. Door state is truthful
(`detecting`, `authorizing`, `armed`,
`opening`, `confirmed`, `unknown`, `failed`) and enrollment distinguishes
unregistered, pending, approved, revoked, and expired. The shell uses semantic
labels/live regions, keyboard/focusable controls, large-text-safe responsive
layouts, and English/Korean locale resources.

No Samsung/OEM, relay, radio, bootloader, install/health, or production gate is
claimed by host tests. Legacy scanner, explicit `manual_remote`, independent
mobile updater, Target dual-slot rollback, periodic HTTPS, authenticated local
recovery, and OEM limitations remain preserved.

## Native onboarding, logout and role-based settings

Registration no longer opens the legacy `/app` WebView. A native, registration-
only screen accepts name and unit, shows pending/approved state, and deliberately
contains no door-open, credential, Backend URL, RSSI or installer-tuning controls.
Normal Settings retains only background-access status, signed app update,
system language, redacted support and account logout. Engineering GATT controls
remain in source for service builds but are unreachable from normal-user and
recovery-shell navigation.

Logout is a credential revocation, not a visual reset. The phone signs the
fixed-width `SGKOUT01` proof; the Backend consumes its nonce, revokes the exact
credential, publishes the replacement signed ACL and removes the linked account
row before returning `local_clear_authorized`. Only then does Android stop BLE
wake/work, remove encrypted locators and delete the exact non-exportable key and
credential locator. A timeout or server rejection preserves the local key and
never reports success.

Migration 010 gives every account `mobile_role=USER` by default. The administrator
console may set `TENANT_ADMIN` under the existing CSRF, RBAC, idempotency and
fresh reauthentication gates. The mobile status response projects that role only
after exact credential/public-key proof. It reveals a separate administrator
settings entry that opens the existing secure console; it does not bypass the
console password or reauthentication for unsafe actions.

PR #309 merged these paths as exact source
`1b701df93194029fb7be733a372f7ddb68f57e97`. Backend run `33323849258`
attempt 2 deployed the same source and schema 010 after backup and passed
canonical plus independent strict-TLS readiness. Target run `33323849255`
signed and atomically published exact-main personal OTA
`2.1.399+main.g1b701df`. Mobile run `33323849352` passed host/native CI and
signed, atomically published and HTTPS-read-back personal OTA
`1.0.0-g1b701df` / `35801`. Independent primary/fallback manifests matched
exact commit and APK SHA-256
`bc4d24fdeacda655a1f1465f466abf15192c3287117965308abe1329cdc9faf3`.
Publication and installation are separate evidence; no phone
logout, fresh registration rendering, or `TENANT_ADMIN` navigation is claimed
until observed on an updated device.
