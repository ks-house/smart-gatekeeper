# Mobile commercial UX and recovery contract (#51)

Last updated: 2026-08-09

## Capability shell

The first-run screen reports `Ready`, `Degraded`, or `Blocked` and keeps manual
local GATT, authenticated `manual_remote`, updater, settings, and redacted
diagnostics reachable without the scanner, WebView, or foreground service. A
denied permission therefore changes automatic-wake capability; it does not hide
recovery capabilities.

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
installer. The old APK and credentials survive every failure, and first-run
health remains durable. Release Gradle configuration fails closed when a real
release keystore is unavailable; debug signing is never a release fallback.

## Manual control compatibility

The explicit local GATT retry remains available through the encrypted recent
Target capability. It does not claim that an MQTT `manual_remote` command moved
the relay. Main's `/api/v1/door/open` now requires the additive v2 proof envelope;
the app does not possess or expose the legacy Backend HMAC secret. Until issue
#52 provisions a scoped possession credential and completes the client rollout,
the legacy Web shell keeps anonymous enrolment, device-ID status, and remote-open
actions visibly disabled and sends no mock-success request. An HTTP `426` from an
N-1 client is an upgrade-required result with no control effect.

## Privacy and UI

Support diagnostics redact URLs, tokens, API keys, passwords, Bluetooth
addresses, credentials, raw proof material, and unbounded exception text at the
logging boundary. Door state is truthful (`detecting`, `authorizing`, `armed`,
`opening`, `confirmed`, `unknown`, `failed`) and enrollment distinguishes
unregistered, pending, approved, revoked, and expired. The shell uses semantic
labels/live regions, keyboard/focusable controls, large-text-safe responsive
layouts, and English/Korean locale resources.

No Samsung/OEM, relay, radio, bootloader, install/health, or production gate is
claimed by host tests. Legacy scanner, explicit `manual_remote`, independent
mobile updater, Target dual-slot rollback, periodic HTTPS, authenticated local
recovery, and OEM limitations remain preserved.
