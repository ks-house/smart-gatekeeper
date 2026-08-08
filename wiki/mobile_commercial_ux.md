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

The updater accepts only signed metadata containing artifact size, SHA-256,
certificate SHA-256, primary and fallback URLs, and an N/N-1 protocol range. It
downloads to a temporary file, validates bytes and certificate before opening the
installer, retains the existing APK and credential on every failure, and records
first-run install health. Release Gradle configuration fails closed when a real
release keystore is unavailable; debug signing is never a release fallback.

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
