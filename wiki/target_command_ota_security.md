# Target command and OTA security

> Scope: GitHub issue #50, software implementation only. Production enablement and all physical acceptance Gates remain closed.

## 1. Verified per-Target command transport

- The Target accepts MQTT only when the broker host, non-1883 port, unique password, root CA, and signer identity are provisioned.
- The broker username must equal the Target ID derived from the ESP32-C6 MAC. The Target subscribes only to `gatekeeper/v1/targets/<target_id>/command` and `/acl` with QoS 1.
- `security/mosquitto.conf` disables anonymous and retained publications. `security/target-acl` uses `%u` pattern rules so one Target credential cannot read or write another Target namespace.
- The backend uses `ssl.CERT_REQUIRED`, a configured CA file, hostname verification, and non-retained QoS 1 publications. There is no plaintext, `CERT_NONE`, `tls_insecure_set(True)`, or Target `setInsecure` fallback.

## 2. Signed command envelope

Every effect is covered by a deterministic `sgk-command-v1` P-256 signature over:

`action`, `boot_id`, `door_id`, `expires_at`, `issued_at`, `key_id`, `nonce`, `schema_version`, `session_id`, `target_id`, `tenant_id`, and `value`.

The Target rejects malformed tokens, wrong Target/tenant/door/boot identities, unknown key IDs, high-S or invalid signatures, commands issued more than 30 seconds in the future, expired commands, and TTLs above 120 seconds. The supported N/N-1 protocol window remains versions 1 through 2; no legacy unsigned command topic is subscribed or dispatched.

## 3. Durable replay and idempotency boundary

The replay ledger is stored in two alternating NVS records with generation and CRC checks. A nonce/session/digest record is persisted before the effect and marked complete only after the effect attempt, so a reset before completion returns `duplicate_uncertain` and never repeats a relay, reboot, configuration, or OTA effect. Completed duplicates return their duplicate status without execution; storage write or readback failure rejects the command before any effect.

## 4. Signed Target OTA

- Periodic HTTPS manifest checks run after 60 seconds and every six hours, with a bounded 15-minute retry after failure. Signed `ota_check` remains an additional trigger, not the only trigger.
- The Ed25519 manifest binds board, dual-slot layout, version, protocol range, artifact URL, exact byte size, SHA-256, signing key, build, commit, and publication identity.
- The artifact must use HTTPS and fit the inactive OTA partition. The Target streams it through one verifier/writer, checks exact size and SHA-256, validates the ESP image, and only then selects the inactive partition.
- A pending image enters a health window after reboot. It is marked valid only after 30 seconds of safe Target state, network or authenticated recovery availability, and minimum heap; failure to become healthy within 120 seconds invokes the ESP-IDF automatic rollback API.
- A durable version floor blocks downgrade. The manifest protocol range must overlap Target protocol 1..2, preserving N/N-1 compatibility.

## 5. Authenticated local recovery and manual recovery

Local recovery is independent of STA, DNS, MQTT, and Backend availability. It starts only with unique WPA2 and HTTP Basic credentials, stages the same signed manifest at `/recovery/manifest`, and uploads firmware at `/recovery/firmware` through the same inactive-slot size/hash/image verifier. The access point does not provide an unauthenticated captive portal; operators open the fixed local address deliberately. Manual local GATT access remains available under its existing feature and safety Gates and is not retired by this command path.

## 6. Production hardening policy

`ENABLE_HARDWARELESS_RC=0` and `SGK_PRODUCTION_BUILD=0` are the default build flags. The lab hardwareless environment is explicit and non-default; a production build with hardwareless RC enabled fails compilation, and compile-OFF firmware clears stale hardwareless NVS enablement. `security/target-production-policy.json` keeps production disabled and requires Secure Boot v2, release-mode flash encryption, encrypted NVS, signed application anti-rollback, locked debug/download paths, unique credentials, and controlled manufacturing rotation evidence.

## 7. Evidence boundary

Software evidence for this change consists of host command replay/mutation/fault tests, OTA contract/state/fault tests, backend tests, static insecure-path checks, and an ESP32-C6 PlatformIO build. It does not prove real broker certificate deployment, credential crossover rejection on the NAS, ESP32-C6 radio operation, local recovery on a device, inactive-slot boot, valid marking, power-loss behavior, automatic rollback, eFuse/debug hardening, N/N-1 device interop, relay safety, operator runbook acceptance, or production authorization. OTA-G1..G4, RELAY-G0..G2, physical soak, and production deployment therefore remain pending and fail-closed.
