# Signed NAS project maintenance

The owner requested unattended administration across Smart Gatekeeper and SmartBox. The existing deployment, broker and HA fixed-command keys remain intact. Their fixed commands intentionally cannot replace root-owned operator code; a separate signed maintenance path handles reviewed diagnostics and maintenance updates without repeated password entry after initial registration.

## Authority

This signer authorizes Python code running as NAS root. It is privileged administration, not a sandbox. The separate SSH transport key alone cannot authorize code: an RSA3072/SHA256 signature from the local operator signer must cover the exact script digest, action label, UUID, issued/expiry times and execution deadline. Ordinary SSH shells and extra arguments are refused. Signed scripts must stay within the owner's authorized project work; physical door/lid actions, arbitrary reboot and repeated OTA are not implicit diagnostic permission.

The private signer and SSH key remain only in the operator's owner-private WSL configuration, outside Git. NAS stores only the public verifier and forced transport key. Registration preserves existing key and sudo-policy bytes, checks that the operator cannot write the root program, validates exact passwordless sudo, and rolls back failed privilege registration. No HA/broker/device configuration is changed by installation itself.

## Protocol and evidence

- Fixed server operations: status, submit, result.
- Closed JSON manifests, SHA256 content binding, real OpenSSL RSA verification, maximum15-minute authorization and maximum15-minute execution.
- Root captures the signed payload before execution. UUID replay returns the existing receipt without another process.
- One active maintenance worker, detached execution, private stdout/stderr and root-owned receipts. Output is exported only as an explicitly emitted bounded JSON object; raw stderr remains private.
- Isolated Python invocation and explicit process environment; no password, forwarding, arbitrary unsigned path or shell fallback.
- A timeout is terminal execution evidence, not successful administration. Never reissue a new UUID because an observation timed out; inspect the existing handle and receipt first.
- Signature/transport acceptance, code completion, code-update readback, service readiness, broker identity, OTA install and physical results are separate claims.

The current first use is a read-only comparison of Synology Docker log query variants, followed by a reviewed operator-code update if evidence identifies a compatibility defect. Keep the existing HA preparation and broker authentication gates; do not bypass a missing notice or disable anonymity prematurely.

The local signer and NAS verifier both use OpenSSL RSA3072/SHA256. No cryptography Python package is required. Hosted CI exercises real signatures.

2026-10-17: PR449 merged34867e7f after all hosted gates passed. Persistent setup-signed-maintenance.sh is captured from merged bytes. Dedicated-key authentication is not yet accepted; first administrator registration remains pending. This grants signed root-code execution, not a code sandbox.

Operating acceptance2026-10-17: registration is independently verified by fresh dedicated-key status, signer match, refusal cases and successful signed UID0 diagnostics/operator update. Administrator prompts are no longer needed for approved signed maintenance. This access success does not complete broker/HA authentication migration.

See [Docker log recovery](docker_log_recovery.md) for bounded Synology SQLite observation and the process-preserving daemon recovery plan.

Owner authorization2026-10-17: NAS settings inspection/cleanup through the management address is approved today only. This does not create an ongoing future settings-change approval.
