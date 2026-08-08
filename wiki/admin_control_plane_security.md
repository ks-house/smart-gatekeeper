# Admin control-plane security (Issue #49)

## Status and evidence boundary

This is a host/software control-plane hardening change. It adds no Samsung/OEM,
ESP32-C6 radio, relay, bootloader/rollback, OTA install-health, operator, or
production-authorization evidence. Those gates remain separate and fail closed.

## Route inventory and required authority

| Route family | Authority | Tenant scope | Extra controls |
|---|---|---|---|
| `POST /api/v1/admin/sessions` | verified mTLS fingerprint | identity mapping | rate limit and lockout window |
| `/admin`, admin tenant/config/log data | server-side session | identity tenant list | role check; PII-minimized tenant results |
| tenant approve/reject, target config | `TENANT_ADMIN` | `legacy:<id>` or global `*` | CSRF, mTLS reauthentication, idempotency key, immutable audit |
| ACL management `/api/v1/admin/acl/*` | admin session boundary plus existing ACL contract | `X-Tenant-ID` | CSRF and mTLS reauthentication before route handler |
| force-open proposal | `SECURITY_OPERATOR` | request tenant | reason, CSRF, fresh mTLS, idempotency, immutable audit |
| force-open approval | distinct `SECURITY_APPROVER` | proposal tenant | fresh mTLS; no MQTT effect before approval |
| Target ACL/OTA pull, ACK and health | target credential contract | target tenant/door | not an admin session route |
| APK/version download and health | public recovery/distribution contract | n/a | intentionally independent of admin auth |

The retired `/api/v1/door/open` device-ID bearer route and anonymous device-ID
data/write routes are not registered. A supplied device ID is not proof of
identity or permission.

## Deployment contract

`ADMIN_MTLS_IDENTITIES_JSON` maps a proxy-verified certificate SHA-256
fingerprint to a stable subject, roles, and allowed tenant scopes. The API only
accepts the identity when `X-SSL-Client-Verify: SUCCESS` is supplied by the
mutual-TLS terminating proxy and the fingerprint matches; an empty/malformed
mapping returns failure, never a development principal. Deploy the proxy so
clients cannot reach the application port or forge these proxy headers.

Sessions are opaque, HTTP-only, Secure, SameSite=Strict cookies with bounded
server-side state. Unsafe actions need the per-session CSRF token, a fresh mTLS
proof plus `X-Admin-Reauthenticate: mtls`, and a bounded `Idempotency-Key`.
`POST /api/v1/admin/sessions/rotate` invalidates all server-side sessions after
identity/key rotation. Authentication attempts are rate limited by client peer.

## Audit and failure semantics

Migration `003_admin_security_up.sql` creates `admin_audit`, indexes it by actor
and tenant, rejects UPDATE/DELETE through MariaDB triggers, and records only the
stable actor subject, tenant scope, action/object reference, hashed idempotency
key, and timestamp. Audit/storage failure rejects the associated control action;
there is no mock success response.

Force-open is intentionally a software command publication result, not a claim
that a physical relay moved. The proposal expires in five minutes; a different
authorized approver must complete it, and a failed MQTT publish returns an error
without a successful-control result. Existing OTA target/download paths remain
independent so an admin identity outage cannot remove recovery access.

## Threat-model tests

`backend/tests/test_admin_security.py` exercises anonymous requests, forged
roles, stale/revoked sessions, missing CSRF, cross-tenant mutation, stolen-ID
legacy-route use, replayed idempotency, and mTLS authentication rate limiting.
`backend/tests/test_migrations.py` verifies the append-only audit migration and,
when `RUN_MARIADB_INTEGRATION=1`, validates the real MariaDB immutable trigger.
