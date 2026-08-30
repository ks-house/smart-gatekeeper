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
identity or permission. The same URI additionally accepts the mobile
credential-signature v3 envelope: Android signs the exact `SGKRMO01` canonical
request with its enrolled non-exportable P-256 key, and the Backend verifies the
active credential, tenant and exact door grant before consuming a durable nonce.
This user credential path is separate from administrator sessions and from the
two-person administrator force-open path.

The single-owner personal app uses a narrower compatibility exception for
enrollment only: Flutter native code, not WebView JavaScript, calls
`POST /api/v1/user/request` with the build-injected mobile API key and the
install-scoped device ID. New rows are pending; repeating the request for an
already active device never revokes it. `GET /api/v1/user/me` uses the same
native-held key. These endpoints do not open a door or publish MQTT. The admin
tenant list includes `ble_device_mac` so the owner can match the pending row to
the device code shown by the app.

## Deployment contract

For a single-owner personal deployment, `PERSONAL_ADMIN_PASSWORD` enables the
bounded `/admin/login` bootstrap without weakening or replacing the mTLS path.
It creates a server-side `personal-session` principal scoped to `*`, uses the
same Secure/HttpOnly/SameSite cookie and CSRF controls, rate-limits failed
password attempts, and requires a fresh personal session marker for unsafe
actions. Keep this secret separate from the mobile control API key. Commercial
or multi-operator deployments must continue to use proxy-verified mTLS and
separate operator/approver identities.

Production Compose supplies the same value as the NAS-local
`PERSONAL_ADMIN_PASSWORD_FILE` secret. Direct and file forms are mutually
exclusive: setting both, or configuring an unreadable file, disables the admin
authentication boundary rather than silently selecting one. CI never receives
or prints the password.

The personal NAS compose binds API port `8000` on the NAS/LAN solely for the
DSM reverse proxy, which terminates public HTTPS on `4442`. Do not forward port
`8000` on the router.

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
`.github/workflows/backend_security.yml` runs those backend and real-MariaDB
migration checks against the exact pull-request SHA; a green local container
run is useful evidence but never substitutes for this hosted result.

## Additive v2/v3 manual-control compatibility contract

Issue #49 does not reinterpret an N-1 `device_id` as a credential. The legacy
`POST /api/v1/door/open` URI remains reserved for compatibility, but a request
without the v2 proof envelope receives an upgrade-required failure and causes no
database or MQTT effect. The authenticated v2 manual envelope binds tenant,
device locator, action, reason, nonce, expiry, and idempotency key to proof of
possession; server storage consumes the nonce exactly once before MQTT.

`force_open_approvals` is the durable cross-process state machine:
`PENDING -> RECONCILIATION_REQUIRED -> PUBLISHED`, with a unique
proposer/scope/idempotency key. The approver must be a different, freshly
mTLS-authenticated subject. `RECONCILIATION_REQUIRED` and its immutable audit
fact commit before any broker call, so a crash, broker failure, or final
persistence outage is visible to an operator and never silently retried as an
unknown physical open. `mobile_control_nonces` makes replay persistence survive
API restarts.

The mobile v3 envelope binds credential ID, 32-byte random nonce, expiry,
fixed reason and idempotency key in a 128-byte canonical input. Its replay row
is stored in `mobile_credential_control_nonces` before broker publication. It
uses neither the APK-wide API key nor the legacy tenant HMAC. A 2xx response is
explicitly `broker-ack-only`; Target receipt, relay/contact and physical door
state require separate evidence. A client transport timeout is outcome-unknown
and must not cause an automatic retry of a physical-effect request.

The approval handler reads precisely the durable names `tenant_scope` and
`proposer_subject`; it never falls back to transient aliases such as
`tenant_id` or `subject`. Security coverage exercises a successful two-person
transition with exactly one broker publication, and separately proves that
self-approval, expiry, replay, cross-tenant approval, and a pre-reserved
`PUBLISHING` operation cannot publish.

The approval transaction owns its lock through identity, role, tenant,
distinct-approver, and idempotency checks, and every exit rolls back and closes
that exact connection. The reconciliation disposition is precommitted before
the broker call; if this write cannot commit, publication is blocked. After a
broker attempt, the final `PUBLISHED` state and immutable
`FORCE_OPEN_PUBLISHED` audit record commit together; a failure leaves the
already durable reconciliation fact visible and returns non-success.

Ingress is a concrete reverse proxy deployment requirement: it terminates
mTLS, accepts public traffic, strips client-supplied identity headers, rebuilds
them only after verification, and reaches the un-published API service over its
private network. The backend trusts only `ADMIN_TRUSTED_PROXY_IPS`; an empty or
invalid allow-list disables administrator login. Issue #51 keeps device-ID-only
Web enrolment/control disabled and truthful; issue #52 owns scoped mobile
possession-credential provisioning and the v2 client envelope rollout. Until
that rollout exists, Flutter must not import or expose the legacy Backend HMAC
secret, and N/N-1 clients receive upgrade-required with no effect. Both issues
must retain N/N-1 update/rollback compatibility.

## Personal administrator account-management console

The personal administrator console now has explicit, audited operations for
editing a registration name/unit and deleting one user account. `PATCH
/api/v1/admin/tenants/{id}` validates the database bounds (name 1..50, unit
1..20) and records `TENANT_PROFILE_UPDATED`. `DELETE` is deliberately not a
raw row deletion: an enrolled account must first have its public credential
linked, that credential is revoked, a replacement signed ACL is published, and
only then is the legacy personal-data row deleted with
`TENANT_ACCOUNT_DELETED`. Access history remains with its tenant foreign key
set to null; immutable administrator audit never stores the deleted name/unit.

Migration 009 adds only the unique nullable account-to-public-credential link.
New enrollment writes it atomically. Already enrolled phones reconcile it only
after presenting the matching public key during a normal status request. A
dual-mode account without that verified link returns HTTP 409 instead of being
deleted unsafely. Deleting the canonical legacy owner transfers that mapping to
another active, credential-linked family account when one exists.

The global access-history view uses `/api/v1/admin/access-events`, not the
single-legacy-scope `/api/v1/logs` compatibility route. Mobile manual-open rows
mean Backend validation plus broker acceptance/failure only; they never claim
Target receipt or physical door movement. UI failures preserve the HTTP detail,
and an expired personal reauthentication response directs the operator to login.

Personal reauthentication now defaults to 900 seconds and accepts configured
values from 300 through 3600 seconds. The server-side session, CSRF,
same-origin cookie, administrator role, tenant authorization and idempotency
requirements are unchanged.

PR #303 merged and Backend run `33316931652` attempt 2 deployed this contract
as exact source `05a58dc3785ca36924c062181a6a3bc114c68281`. Canonical NAS
evidence and independent strict-TLS `/live` and `/ready` both passed for that
exact build with every readiness check true. This proves source, CI, schema 009
migration, deployment and service readiness; it does not by itself prove an
operator completed an edit, deletion or access-history browser journey.
