# Local-PC diagnostic read API

Status: Backend deployed as `00bee34343827181cbaa449244dbfe96044a6e94` via
PR #387 at 14:28 KST on September 7. NAS token activation remains pending.
This is separate from administrator cookie authentication and from door control.

## Scope

The dedicated token can perform only these reads:

| Route | Result |
| --- | --- |
| `GET /api/v1/diagnostics/bundles?limit=20&before_id=…` | Most recently stored opted-in reports, receipt/export times, database row IDs and pagination cursor |
| `GET /api/v1/diagnostics/bundles/{id}` | Validated report including sessions/wakes/optional scan lifecycle, plus up to 500 matching integrity-verified Target events |

`id` is the decimal row ID returned by the list, not `bundle_ref`. Different
phones can have identical content references, so the latter is not an exact
database identity. IDs/timestamps are strings where needed to preserve integer
precision. Target event truncation is explicit; absent events do not prove that
no physical action occurred. A successful mobile session still does not prove
door movement.

This capability reads all opted-in mobile bundles in this single-owner Backend,
not only one phone. The list excludes tenant/credential IDs and names; the detail
revalidates the closed support schema and excludes arbitrary DB columns. It is
not a tenant-scoped commercial support credential. It cannot create admin
sessions, read general admin routes, change settings, enroll devices, trigger
OTA or open doors. There is no POST/PUT/DELETE route or command publisher here.

## Server configuration and rollout

Set `DIAGNOSTICS_READ_TOKEN_SHA256` to the lowercase SHA-256 hex digest of the
client's randomly generated token. Both Compose profiles pass this optional
value. Empty/malformed configuration disables only these reads (503), not
normal access/readiness/OTA. No DB migration is required.

The current NAS wrapper rejects unknown runtime keys. **First review/admit and
install the updated wrapper** that permits this optional digest, keeping every
other exact-key check. Only then add the single digest assignment to the existing
root-controlled `runtime.env`; do not replace that file with the one-line snippet. Deploy the
Backend containing these routes and recreate its API container through the
normal deployment path. Do not send the raw token to CI, firmware, HA or mobile.
Server restart keeps the capability when the configured digest is unchanged.
To revoke it, remove/change the digest and recreate the API container. This
single-owner token has no built-in expiry, so revoke it if the PC/file is lost
or compromised. It is not the mobile API key or administrator password.

The server compares digests in constant time, limits reads/failed requests to
60 per minute per peer per process, returns `Cache-Control: no-store` for data,
and keeps query sizes bounded. A shared reverse-proxy peer shares that quota.
TLS is required on the public endpoint. Tokens must never be sent in a query
string. Do not enable request-header/body logging for this endpoint.

## Local PC (WSL Bash)

One-time generation, without displaying the token:

```bash
python3 scripts/read_diagnostics.py --init-token
```

This creates `~/.config/smart-gatekeeper/diagnostics-read.token` with mode 0600,
refuses an existing destination, and prints only the file location and server
digest assignment. It was already run on the current owner's WSL PC during this
implementation; **do not rerun it to retry a failed read**. A separate local
`diagnostics-read.server.env` snippet contains only the digest for NAS setup.

The client automatically uses that default token file. Alternatively provide
exactly one of `SGK_DIAGNOSTICS_READ_TOKEN` or
`SGK_DIAGNOSTICS_READ_TOKEN_FILE` in the actual client process environment:

```bash
export SGK_DIAGNOSTICS_READ_TOKEN_FILE="$HOME/.config/smart-gatekeeper/diagnostics-read.token"
python3 scripts/read_diagnostics.py --check-token
python3 scripts/read_diagnostics.py --limit 20
python3 scripts/read_diagnostics.py --bundle-id 123
```

Replace `123` with a returned ID. `--check-token` validates local availability
only, never Backend activation. The default origin is the owner's HTTPS backend;
`--base-url` accepts another HTTPS origin without credentials/path/query. TLS
certificate verification is never disabled. Redirects are refused so a response
cannot forward the Authorization header elsewhere. Tokens are not CLI arguments
or output, and error output does not echo response bodies or headers. Successful
report JSON is intentionally printed for local inspection; do not publish it.

HTTP 404 can mean the old deployment lacks the route (or a detail row is absent),
503 can mean the capability is disabled or storage unavailable, 401 means the
token does not match, and 429 means wait for the limit to reset. Do not retry by
generating another token or changing the administrator password.

## Validation and evidence boundary

Tests cover disabled/wrong credentials without DB calls, read-only methods and
no administrator authority, list bounds/cursor, exact row retrieval, verified
event correlation, malformed stored-report rejection, safe errors, rate limits,
private non-overwriting token creation, env/file exclusivity, HTTPS and redirect
guards. Existing administrator/mobile/OTA routes retain their own authorization.
Live NAS activation and real uploaded-report readback remain pending.

Local results: 233 Backend tests complete with two existing real-MariaDB skips,
four PC-client tests pass, and the OTA contract passes. The new API/client tests
account for seven/four tests respectively. Existing route inventory assertions
now use OpenAPI paths rather than assuming every FastAPI router node has `.path`.

The following deployment-input changes were separately admitted by policy
PR #388 before merge-connecting that main into PR #387. Local policy tests and
the hosted trusted-base check pass; all 23 protected paths remain enforced:

| Protected candidate | SHA-256 |
| --- | --- |
| `backend/compose.production.yml` | `709f70c7683636a0eb34a9822212b4369d5e5b906bbdeae81c3e2307236f953a` |
| `backend/deploy/sgk_backend_deploy.sh` | `c368931822e5bf6c2cb50b9d12f7b0fe372f61f47f03eb98245b9c0e48118003` |
| `ops/backend_trusted_bundle_paths.json` | `b4512474c0bda2901b978b038f7dd47dd5b401066bb9521f2e4f8d4b7086db65` |

The unauthenticated live list-route probe returned 404 on September 7. The local
token file exists with mode 0600 and `--check-token` succeeds, but neither proves
NAS activation. Do not generate another token to resolve that 404.

After deployment run `34086666204`, external `/ready` returns that exact source
and all checks pass (DB, MQTT, collector, authentication and evidence integrity).
API image digest is `9c56cdb92797158dbfd31fef40f327336a26a3a59c79f64ab0c6fa60a86a6439`.
The dedicated PC token now receives 503, consistent with the deliberately
disabled capability until NAS digest configuration. This is not an empty report
list and does not establish real report readback.

The current GitHub production variable identifies NAS SSH port **8822**.
Port 22 refuses connections; port 8822 is reachable but this PC's available
noninteractive authentication is rejected. CI's forced `apply`/`status` key
does not authorize editing the root wrapper or runtime configuration. Owner
setup must use the existing NAS administrative path and the previously created
digest snippet; do not regenerate the PC token or loosen the forced key.
