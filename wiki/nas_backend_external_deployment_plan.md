# Synology NAS backend external deployment plan

> Status: **repository implementation merged; private CI status preflight passed; no NAS deployment has been run.**
> Last reviewed: 2026-08-29
>
> Scope: deploy the FastAPI and MariaDB images in
> `backend/compose.production.yml` to the existing personal Synology NAS from
> outside the home network without exposing DSM, SSH, the Docker socket, the
> database, or API port 8000 to the public Internet.

## 1. Decision

Use a **push-image, private-control deployment**:

```text
reviewed exact main
        |
        v
GitHub-hosted CI -- test / SBOM / attest / build DS423+ linux/amd64 images
        |
        v
GHCR immutable API + DB digests and signed release descriptor
        |
        v
protected production approval
        |
        v
ephemeral Tailscale runner identity
        |
        v
NAS forced deploy command -- backup / pull / migrate / ready / record
        |
        v
existing public origin :4442 through an allow-listed ingress proxy
```

The deployment/control plane is private. The service/data plane remains the
existing HTTPS/MQTTS architecture. Router port forwarding must not be added for
DSM, SSH, port 8000, MariaDB, or the Docker API.

The recommended initial solution set is:

| Role | Solution | Why it is needed |
|---|---|---|
| immutable image registry | GitHub Container Registry (GHCR) | stores the API and DB images by exact `sha256` digest instead of a mutable tag |
| CI builder | GitHub-hosted Actions runner + Docker Buildx | keeps source compilation and registry credentials off the NAS and can produce the NAS CPU architecture |
| private deployment path | Tailscale on Synology + Tailscale GitHub Action using workload identity federation | reaches the NAS without a public SSH/DSM port; each workflow gets a short-lived tagged node |
| narrow deployment authority | separate NAS deploy account, SSH key forced to one root-owned deploy wrapper, and narrowly scoped `sudo` if required | prevents a CI credential from becoming an interactive NAS administrator or unrestricted Docker socket user |
| runtime orchestrator | Synology Container Manager / Docker Compose | applies the reviewed production Compose and provides an operator GUI fallback |
| secrets | NAS-local, permission-restricted secret files mounted as Compose secrets | secrets remain on the NAS and are not copied from GitHub in `.env` or command output |
| database protection | migration logical backup plus encrypted off-NAS Hyper Backup | supports backup-first schema change and 3-2-1 retention; a NAS volume alone is not a disaster-recovery copy |
| independent verification | external HTTPS/TLS monitor and release evidence log | proves the service from outside the NAS; `/live` alone is not readiness |

No new paid SaaS is required for the first personal deployment. Tailscale,
GHCR, GitHub Actions, Container Manager, and Hyper Backup are sufficient if the
NAS model supports Container Manager and its CPU/storage capacity is adequate.

## 2. Current repository and NAS evidence boundary

- The local candidate in `.github/workflows/backend_security.yml` retains the
  backend tests, dependency audit, SBOM/evidence and MariaDB migration tests,
  then adds GHCR `linux/amd64` API/DB publication, registry provenance,
  signed-bundle creation, protected `production` approval, ephemeral Tailscale
  reachability, restricted SSH application and NAS evidence readback. It has
  passed repository contract/static tests but has not been merged, run on
  GitHub, or admitted by the trusted-workflow policy rotation.
- `backend/compose.production.yml` already requires independently pinned API and
  DB repositories/digests, runs a backup-first one-shot migration to schema
  `007`, admits the API only after migration, uses an internal DB network, and
  publishes no host API/DB port.
- `backend/docker-compose.yml` builds source on the NAS, bind-mounts the app,
  contains development/personal defaults, and exposes port 8000. It is an
  operator compatibility path, not the external production deployment
  baseline.
- The existing firmware/APK NAS publisher is SFTP-only. That account has no
  remote shell and therefore cannot pull images, render Compose, run migrations,
  or check container readiness. Preserve it for artifact publication and create
  a separate deployment identity.
- A green CI job, a GHCR push, an SSH command exit code, or a Compose start is
  not deployment completion. Completion requires the NAS-side release record,
  migration result, exact running image digests, `/ready`, public-origin
  readback, and a bounded observation window.

## 3. Required Phase 0 inventory

Record these read-only facts before selecting image targets or changing the
NAS. Values are intentionally not guessed in this plan.

| Fact | Command/UI source | Gate |
|---|---|---|
| NAS model and CPU architecture (`amd64` or `arm64`) | DSM Info Center and `uname -m` through an owner-approved session | both API and DB images contain this architecture |
| DSM and Container Manager versions | Package Center | Compose file renders and project lifecycle is supported |
| Docker/Compose engine versions | restricted diagnostic command | `depends_on` completion, health checks, read-only/tmpfs, resource limits, and secret mounts work as expected |
| Btrfs/snapshot and free-space state | Storage Manager | DB backup, old/new images, and rollback reserve fit before pull |
| Tailscale package availability | Synology Package Center | NAS joins the private tailnet without enabling Funnel |
| current public ingress | DSM reverse proxy export/read-only capture | `https://tworimpa.synology.me:4442` remains unchanged for the installed app |
| backup destination | Hyper Backup task and restore target | at least one encrypted copy exists outside this NAS |

### 3.1 Collected inventory evidence

The owner-provided DSM Info Center capture on 2026-08-28 establishes the
following non-secret deployment facts:

| Fact | Observed value | Decision |
|---|---|---|
| NAS model | Synology DS423+ | installed Container Manager is the deployment runtime candidate |
| DSM | 7.3.2-86009 Update 4 | capture exact runtime compatibility evidence before live deployment |
| CPU | Intel Celeron J4125, 4 cores at 2 GHz; `uname -m=x86_64` | backend image platform is confirmed as `linux/amd64` |
| memory | 18 GB | adequate for the current API/DB resource limits, subject to actual free-memory/load evidence |
| thermal state | normal in the capture | point-in-time UI state only; not a soak/capacity result |
| Container Manager | running, package `24.0.2-1606`; installed equals Package Center online version | compatible candidate; disposable Compose feature/secret probe remains required |
| Docker/Compose | Docker client `24.0.2`; Compose `v2.20.1-6047-g6817716` | daemon architecture query was permission-denied as the non-privileged owner, which does not block the `uname` platform proof and does not justify a privilege change |
| Volume 1 | `btrfs`, normal; about 13 TB used and 28.9 TB free (`df` rounded 42 TB total/29 TB available) | filesystem and capacity support image rollback reserve and snapshot-capable storage; actual snapshot/backup policy remains pending |
| Tailscale | DSM package ID `Tailscale` is installed and running at `1.58.2-700058002`; packaged CLI reports NAS IPv4 `100.95.243.92`; WSL reaches private SSH `4422` and its ED25519/ECDSA keys intersect the already trusted public-bootstrap DSM keys | exact private host, matched ED25519 known-host entry, narrow tag grant and GitHub OIDC credential/Environment secret names are configured; exact-main run `33199183911` passed the ephemeral tagged-runner forced-status exchange |
| DSM reverse proxy | HTTPS public listener `4442` to HTTP `localhost:8000`; HSTS off; no DSM access-control profile | preserves the installed app origin, but the current proxy capture does not prove the administrator mTLS/header contract |
| router exposure | confirmed blanket external forward `4000-4999`; protocol/target details not yet captured | P0 excessive-exposure finding: inventory listeners, add exact required rules and verify them before removing the range |
| public IPv6 | a read-only DNS check observed an AAAA answer for the current public hostname; NAS listeners also bind wildcard IPv6 | IPv4 NAT narrowing alone is insufficient; verify router/DSM IPv6 inbound default-deny and exact service rules without recording the public address |
| DSM configuration backup | automatic encrypted DSM configuration backup enabled; owner capture showed a successful run | protects selected DSM configuration only; it is not Hyper Backup evidence for containers, MariaDB, volumes or migration backups |

The capture also contained owner account, server identity and device serial
information. Those values are deliberately not copied into the repository or
deployment evidence. Snapshot policy, Hyper Backup, GitHub/Tailscale grants,
router protocol/target and exact required ports, and disposable Compose
secret/volume compatibility remain pending.

### 3.2 Router range narrowing procedure

Do not delete the `4000-4999` rule first because that can interrupt the installed
app or Target MQTTS. First identify which NAS TCP listeners currently occupy the
range. Run this read-only block on the NAS and record only the port column; local
addresses may be redacted:

```sh
echo 'LISTENING_TCP_4000_4999'
{ if command -v ss >/dev/null 2>&1; then ss -lnt; else netstat -lnt; fi; } \
  | awk 'NR == 1 || $4 ~ /:4[0-9][0-9][0-9]$/'
```

The repository currently has evidence for two externally consumed TCP ports in
that range:

- `4442`: installed mobile app/WebView, APK and backend HTTPS through DSM
  Reverse Proxy;
- `4883`: public MQTTS listener used by the Target.

The owner-provided non-privileged listener inventory observed no UDP listener in
the range and these TCP listeners on both wildcard IPv4 and IPv6 where shown:

| TCP port | Current classification |
|---|---|
| `4080` | plaintext nginx returned HTTP 403; TLS negotiation failed; no approved external consumer |
| `4085` | DSM HTTPS Reverse Proxy for InfluxDB, forwarding to local HTTP `4086`; owner confirms current external use, so temporary exact-rule retain; authentication/access-control review pending |
| `4086` | Container host mapping to InfluxDB `8086/tcp`; direct HTTP/proxy-bypass path and must not remain blanket-public |
| `4087` | Container host mapping to Grafana `3000/tcp`; direct HTTP/proxy-bypass path and must not remain blanket-public |
| `4088` | DSM HTTPS Reverse Proxy for Grafana, forwarding to local HTTP `4087`; owner confirms current external use, so temporary exact-rule retain; Tailscale-only migration remains preferred |
| `4123` | DSM HTTPS Reverse Proxy to a LAN Home Assistant `8123`; owner confirms current external use, so exact-rule retain |
| `4222` | DSM SFTP, `SSH-2.0-OpenSSH_8.2`; existing GitHub NAS artifact publisher uses it, so temporary exact-rule retain until that workflow joins Tailscale |
| `4422` | DSM interactive SSH, `SSH-2.0-OpenSSH_8.2`; owner currently uses it externally, so temporary exact-rule retain while private Tailscale SSH replacement is proven |
| `4442` | repository-confirmed current mobile/WebView/APK/backend HTTPS origin |
| `4443` | current HTTPS OTA virtual host: correct SNI returned HTTP 200 with verified TLS for both `/firmware/version.json` and `/gatekeeper_apk/version.json`; exact-rule retain |
| `4883` | repository and live-history confirmed public Target MQTTS |

Listening on the NAS does not by itself prove that a service must be reachable
from the Internet. Resolve unknown ownership from the DSM Reverse Proxy rule
list and Container Manager container/project port list. A process-name lookup is
optional; do not grant Docker/root access solely for this inventory.

The protocol fingerprint is enough to reject `4080` as a deployment-control
port. Owner/DSM configuration identifies `4222` as SFTP used by the existing
GitHub NAS publisher and `4422` as externally used interactive SSH. Both are
temporary compatibility ports, not the target backend deployment control plane.
Port `4443` has separately passed correct-host firmware/APK version-path checks.

A live modern-`scp` attempt against interactive SSH `4422` authenticated but
failed with `subsystem request failed` because the client requested SFTP. This
is an endpoint/protocol mismatch, not a file-permission or password failure.
Bootstrap transfer therefore uses an authenticated non-interactive SSH stdin
stream, or the separately configured `4222` SFTP service, without weakening
host-key checks or cryptographic algorithms.
The first streamed execution stopped at preflight because DSM's `sudo bash`
environment omitted the Docker CLI from `PATH`; no secret/state directory or
volume mutation had begun. The helper now resolves only the current executable
or fixed Synology Container Manager package paths before making any Docker call.
The following retry reached secret staging but stopped on a Bash 4.4
same-declaration local expansion under `set -u`. Root deployment directories may
now exist; the EXIT trap removes the temporary staging directory, and no secret
file, external volume, container or database change was reached. Local variable
initialization is now split into portable assignments, and retry is idempotent
against the already-created empty directories.

Current no-downtime narrowing candidate:

| Action | TCP ports | Condition |
|---|---|---|
| retain as exact public rules now | `4085`, `4088`, `4123`, `4222`, `4422`, `4442`, `4443`, `4883` | all have named current consumers; verify authentication/TLS and client operation after the change |
| remove with blanket range | `4080`, `4086`, `4087` | no accepted direct-public need; 4086/4087 bypass HTTPS proxies |
| later remove after private migration | `4085`, `4088`, `4222`, `4422` | move observability, GitHub SFTP and interactive SSH to Tailscale before closing their public rules |

Owner use does not by itself close the security Gate for public InfluxDB or
Grafana. Their exact rules are temporary compatibility decisions; application
authentication, DSM/proxy access control, alerting and eventual Tailscale-only
access remain required.

Every other listening or forwarded `4xxx` port needs a named service owner and
current client before it is retained. The eventual change order is:

1. add exact individual TCP forward rules for every accepted service while the
   old range still exists;
2. verify public `4442` TLS and `/ready`, Target `4883` CA/hostname/MQTTS
   recovery, and any other named service;
3. remove the `4000-4999` range rule;
4. repeat the external checks and retain rollback evidence.

Some routers reject individual rules that overlap an existing range. If exact
rules cannot be staged while `4000-4999` exists, use a short owner-controlled
change window: save/capture the current rule, prepare all eight TCP entries,
remove the range, add the exact entries immediately, and run the verification
matrix. Restore the old range only as a time-bounded rollback when a required
service fails and the exact mapping cannot be corrected in the window.

Because the public hostname currently resolves over IPv6 and the observed
listeners include `:::` bindings, apply the same policy at the router/DSM IPv6
firewall. A NAT-only IPv4 change is not acceptance. From an independent network,
verify required services over the hostname and verify direct `4080`, `4086` and
`4087` are unreachable over both address families; do not copy the public IP
addresses into evidence.

The deployment control plane uses Tailscale and must not add another public
router port. No router rule is changed during inventory.

The accompanying Container Manager port capture also shows API host
`0.0.0.0:8000 -> 8000/tcp`, plaintext MQTT
`0.0.0.0:1883 -> 1883/tcp`, and MQTTS
`0.0.0.0:4883 -> 8883/tcp`; MariaDB `3306/tcp` has no host mapping in that
capture. Ports 8000 and 1883 are outside the current router range but remain LAN
exposure/hardening items. The hardened production Compose removes the API host
port; a reviewed loopback ingress overlay must preserve DSM's
`localhost:8000` upstream without publishing the API directly.

### 3.3 Owner collection procedure

Prefer DSM UI first. Collect only the following values; do not capture passwords,
tokens, certificate/private-key contents, serial numbers, MAC addresses, public
IP addresses, or full tailnet status.

1. **Control Panel -> Info Center -> General**: NAS model, DSM version, and
   installed memory.
2. **Package Center -> Installed**: Container Manager version. Search for
   Tailscale and record only `installed`, `available`, or `not available`, plus
   its version when installed.
3. **Storage Manager -> Volume**: volume name, filesystem (`Btrfs` or `ext4`),
   total size, and free size. Do not change snapshot or scrub settings.
4. **Hyper Backup**: record whether a task exists, whether its destination is on
   this NAS or off-NAS, encryption on/off, and the latest successful run time.
   Do not disclose the remote account or destination hostname.
5. **Control Panel -> Login Portal -> Advanced -> Reverse Proxy**: locate the
   HTTPS `4442` rule and report only its destination shape, for example
   `127.0.0.1:8000`, `LAN-IP:8000`, or `other`. Do not edit the rule.
6. **Router/firewall view**: answer yes/no whether any of ports 22, 5000, 5001,
   8000, 3306, 2375, or 2376 are forwarded from the Internet. Do not send the
   public IP.

If SSH is already enabled, connect from the same LAN to the NAS private address
and run this read-only block. In WSL or PowerShell the connection command is
`ssh <DSM-user>@<NAS-LAN-IP>`. Do not open or forward SSH on the router. If SSH
is disabled, the UI facts may be sent first; enabling SSH is not required just
to start the review.

```sh
echo 'MODEL'
cat /proc/sys/kernel/syno_hw_version 2>/dev/null || true

echo 'KERNEL_ARCH'
uname -m

echo 'DSM_VERSION'
sed -n 's/^\(productversion\|buildnumber\|smallfixnumber\)=/\1=/p' /etc.defaults/VERSION

echo 'CONTAINER_MANAGER_PACKAGE'
synopkg version ContainerManager 2>&1 || true

echo 'DOCKER_CLIENT'
docker --version 2>&1 || true

echo 'DOCKER_SERVER_ARCH_VERSION'
docker info --format '{{.Architecture}} {{.ServerVersion}}' 2>&1 || true

echo 'COMPOSE'
docker compose version 2>&1 || docker-compose version 2>&1 || true

echo 'VOLUME_FREE'
df -h /volume1 2>&1 || true

echo 'TAILSCALE_PACKAGE'
synopkg version Tailscale 2>&1 || true
```

`docker info` may return permission denied for a non-administrator. That result
is useful and should be reported as-is; do not add the account to a privileged
group or run an unreviewed `sudo` command merely to collect it. Map
`x86_64 -> linux/amd64` and `aarch64 -> linux/arm64`; any other architecture
requires a separate image-compatibility decision.

Paste the sanitized result in this form:

```text
NAS model:
Kernel architecture:
DSM version/build:
Memory:
Container Manager version:
Docker server version/architecture:          # or permission denied
Docker Compose version:
Volume filesystem / total / free:
Tailscale: installed / available / unavailable, version if installed
Hyper Backup: task yes/no, off-NAS yes/no, encrypted yes/no, latest success
Reverse proxy 4442 destination: loopback:port / LAN:port / other
Public forwarding 22/5000/5001/8000/3306/2375/2376: all no / list only ports that are yes
```

Run a disposable Compose compatibility probe before production. In particular,
the current production file declares `external: true` secrets and volumes.
Docker Compose supports Linux file-mounted secrets, but Synology's installed
Compose implementation must prove how it resolves external secrets. If external
secrets are not supported, create a NAS overlay file that maps each secret to a
root-owned `file:` path. Do not weaken the application to plaintext environment
variables.

## 4. Build and publish lane

Add a separate exact-main release workflow; do not extend pull-request jobs with
production credentials.

1. Trigger on a reviewed `main` commit or an explicit versioned dispatch.
2. Re-run the existing backend security, migration, dependency, SBOM, and
   trusted-workflow Gates.
3. Build `backend/app/Dockerfile` and `backend/db/Dockerfile` for the Phase 0 NAS
   architecture. Build `linux/amd64,linux/arm64` only if both are actually
   tested; otherwise publish the exact required platform and say so.
4. Push to GHCR with traceability tags, but deploy only immutable digests:
   `ghcr.io/ks-house/smart-gatekeeper-backend@sha256:<digest>` and
   `ghcr.io/ks-house/smart-gatekeeper-db@sha256:<digest>`.
5. Generate and attest a release descriptor that binds:
   - exact 40-hex source commit;
   - API and DB repository/digest/platform;
   - production Compose SHA-256;
   - expected schema version/digest (`007` and its current ledger digest);
   - SBOM/provenance references;
   - minimum deploy-wrapper version;
   - previous known-good descriptor for rollback.
6. Publish no runtime secret, private signing scalar, API key, MQTT credential,
   database password, NAS credential, or decrypted Target artifact in an Actions
   artifact or container layer.

The publication job needs `packages: write`; the deployment job needs only
`packages: read`. Both retain `contents: read`, while provenance/workload
identity receives only its required `id-token` and attestation permissions.
Pin third-party Actions by full commit SHA, consistent with the existing
workflow.

## 5. Private control plane

### 5.1 Recommended lane

Use the official Tailscale Synology package. The GitHub-hosted deployment job
joins the tailnet as an ephemeral tagged node through workload identity
federation. Tailnet grants allow only:

```text
tag:sgk-github-deploy -> tag:sgk-nas-deploy:<restricted SSH port>
```

It must not reach DSM administration, MariaDB, MQTT administration, other LAN
hosts, or the public service port. Do not enable Tailscale Funnel for this lane.

The live GitHub repository OIDC configuration currently reports
`use_default=true` and `use_immutable_subject=false`. Because the deployment job
binds the `production` Environment, create the Tailscale OpenID Connect trust
credential with the exact GitHub subject
`repo:ks-house/smart-gatekeeper:environment:production`, tag
`tag:sgk-github-deploy`, and only the write scopes required to create the
ephemeral node (`Keys > Auth Keys` and `Devices > Core`). Record the generated
client ID and audience in the `production` Environment as
`TS_OIDC_CLIENT_ID` and `TS_OIDC_AUDIENCE`; the workflow already has
`id-token: write` and does not use a long-lived Tailscale client secret.

The NAS endpoint must be the NAS's exact Tailscale MagicDNS FQDN or stable
Tailscale IPv4 address, not its public Synology hostname. Set it as
`NAS_TAILSCALE_HOST` only after a self-only NAS readback and a private-path SSH
probe. Generate `NAS_DEPLOY_KNOWN_HOSTS` for that exact host and port `4422`
over a trusted LAN/tailnet path, then compare the key fingerprints with the
already accepted DSM SSH host key before storing it. A successful `ssh-keyscan`
connection alone is not trust evidence.

The live tailnet policy still contains the default `* -> *`, `ip: ["*"]`
grant. Because grants are additive, the narrow CI rule cannot enforce isolation
until that wildcard source rule is replaced. Preserve current user-owned device
behavior with an `autogroup:member -> *` compatibility grant and add the CI
tag-to-exact-host `tcp:4422` grant separately. Before saving, inventory every
currently tagged device: `autogroup:member` excludes tag-based identities, so
each pre-existing service tag needs an explicit compatibility decision. Do not
use `autogroup:tagged -> *` because it would also re-expand the new CI runner.
The current Machines overview shows three user-owned devices and no visible tag
badges, including connected NAS `tworim423` at `100.95.243.92`. Owner detail
readback confirms all three expose no subnet routes, are not allowed as exit
nodes and have no Apps routing. The wildcard replacement therefore has no
pre-existing tagged or routed-source compatibility exception to preserve.
The owner saved the replacement with no validation errors. A WSL user-owned
source then reached private NAS SSH and reproduced `status=not-deployed` with
exit zero; an attempted arbitrary command was forced to the dispatcher allowlist
and returned exit 126. This proves the private network/host-key/forced-command
lane after the grant change. The Tailscale OIDC credential was subsequently
created and both `TS_OIDC_CLIENT_ID` and `TS_OIDC_AUDIENCE` secret names are
present in the protected GitHub Environment; values were not read back. The
workflow now has a separate manual exact-`main` status-only preflight which can
exercise the first tagged exchange without building, signing or invoking
`apply`. That hosted run remains pending until the protected workflow bytes are
admitted and merged.

On the NAS, create a deployment identity distinct from the current SFTP-only
publisher. Its authorized key is restricted to one root-owned wrapper, for
example `sgk-deploy`, with no PTY, forwarding, agent forwarding, or arbitrary
command. The wrapper accepts only a validated release descriptor reference or
digest and runs from a fixed project directory. If Container Manager requires
privilege, allow only this wrapper through `sudo`; do not add the account to an
unrestricted administrator group and do not expose `/var/run/docker.sock` to a
network service.

### 5.2 Bootstrap lane

Before CI automation, an owner can use the same Tailscale path from a trusted
laptop and invoke the wrapper manually. This proves NAS compatibility, backup,
ingress, and rollback with fewer moving parts. After one recorded successful
manual canary, connect the protected GitHub Environment to the same wrapper.

### 5.3 Not recommended as the default

- **Persistent self-hosted GitHub runner on the NAS:** a workflow compromise can
  persist on the NAS and a Docker-capable runner is effectively privileged.
  GitHub specifically warns against self-hosted runners for untrusted public-
  repository workflows. If ever required, make it repository-only,
  pull-request-ineligible, isolated, ephemeral/JIT, and separately reviewed.
- **Public SSH/DSM port forwarding:** expands the attack surface and is not
  needed when the runner can join a private tailnet.
- **Watchtower/Portainer mutable-tag auto-update:** bypasses the exact-digest,
  backup-first migration, readiness, approval, and rollback evidence contract.
- **Cloudflare Tunnel for deployment:** unnecessary for a private control plane
  and would complicate the installed app's exact public origin. It is not a
  substitute for the existing raw MQTTS service contract.

## 6. NAS-side transactional deployment

The deploy wrapper performs the following fail-closed sequence and writes a
sanitized append-only release record for every attempt.

1. Validate the descriptor schema, signature/attestation, exact main commit,
   image digest formats, allowed GHCR repositories, platform, Compose digest,
   and wrapper version.
2. Acquire a deployment lock. Reject concurrent or replayed attempts.
3. Record current descriptor, exact running container image IDs/digests,
   migration ledger, `/live`, `/ready`, free space, and NAS time.
4. Require current `/ready` or an explicit incident-mode owner approval. A
   broken current release must not silently redefine the success baseline.
5. Create the migration logical backup and SHA-256 sidecar. Copy/confirm it in
   the approved encrypted backup destination before a destructive or
   incompatible migration.
6. Authenticate to GHCR using the protected job's short-lived, repository-scoped
   `github.token` carried in a versioned SSH stdin envelope immediately before
   the signed bundle. Keep its Docker config only in the root-only per-attempt
   directory and remove it through the common success/failure cleanup; never
   store a long-lived registry credential on the NAS. Pull both exact digests,
   verify local image IDs/platforms, and never run `latest`.
7. Materialize a release directory containing only the descriptor, reviewed
   Compose, non-secret configuration, and digest evidence. Secrets are
   referenced from the fixed NAS secret directory.
8. Render Compose and reject any API/DB public host binding, source bind mount,
   mutable image reference, missing external volume, or plaintext secret.
9. Run `migrate` once. Require exit 0, schema `007`, exact ledger digest, and
   the migration backup record before API admission.
10. Start/replace the API and DB project. Wait for DB health and `/live`, then
    require `/ready=200` with every readiness check true.
11. Verify the expected running API/DB digests from the engine, not just the
    descriptor.
12. Read back the installed app origin through
    `https://tworimpa.synology.me:4442` and verify certificate, `/live`, and
    `/ready` semantics. A monitor outside the NAS should repeat this check.
13. Observe a bounded canary interval, broker connectivity, error logs, and
    metrics/alert delivery. Only then atomically mark the descriptor current.
14. Retain the previous descriptor and image digests until the rollback window
    closes; garbage collection is a separate owner-reviewed operation.

The wrapper must redact values and names that disclose tenant/device identity or
credentials. Record hashes/IDs, UTC timestamps, exit states, readiness check
names, and image digests instead.

## 7. Ingress and administrator boundary

`backend/compose.production.yml` intentionally has no host port. Add a reviewed
ingress layer instead of exposing the API container directly:

- a dedicated nginx/Caddy/Traefik container joins only the `edge` network;
- it binds a fixed NAS-loopback/LAN-only port for DSM reverse proxy, never a
  router-forwarded API port;
- DSM continues serving the installed mobile app's existing
  `https://tworimpa.synology.me:4442` origin;
- the proxy strips all inbound client-certificate identity headers;
- for administrator routes it verifies the client certificate and reconstructs
  the trusted headers only toward the API from an IP in
  `ADMIN_TRUSTED_PROXY_IPS`.

Whether DSM Reverse Proxy alone can satisfy the repository's exact mTLS header
contract is a test Gate, not an assumption. If it cannot, route administrator
access through the dedicated mTLS proxy or keep it private on Tailscale while
the public tenant/app routes remain on DSM. Never relax the backend's fail-closed
admin checks to accommodate the proxy.

## 8. Secret and state layout

Suggested NAS layout (exact volume number remains an owner choice):

```text
/volumeN/docker/smart-gatekeeper-backend/
  releases/<source-sha>/        # descriptor, Compose, non-secret config, evidence
  current.release.env           # atomic signed descriptor copy maintained by wrapper
  secrets/                      # root/deploy-readable only, never synchronized to Git
  migration_backups/            # Compose external volume or fixed bind, encrypted copy off-NAS
  evidence/                      # append-only sanitized deployment records
```

The existing APK artifact directory remains a separately managed read-only
external volume. MariaDB data, API state, APK artifacts, and migration backups
must not be deleted during routine deployment. Secret rotation is an explicit
overlap/canary procedure, not an incidental deployment side effect.

The current personal administrator password is active and therefore must be
preserved as the NAS-local `personal_admin_password` file secret. The ACL
transition signing pair is disabled and is not introduced by first adoption.
The exact-layout `bootstrap_legacy_synology.sh` helper copies current values
without printing them, preserves the confirmed target-config bytes, and creates
the three required bind-backed volumes while leaving the live containers and
MariaDB volume untouched. It refuses to overwrite any differing destination.

For the personal installation, NAS-local files are the smallest adequate secret
solution. Consider SOPS+age, Infisical, or Vault only when multiple operators,
central rotation, audit integration, or additional hosts justify their
operational cost.

## 9. Rollback contract

| Failure point | Automatic action | Owner decision required |
|---|---|---|
| descriptor, signature, pull, render, or preflight failure | keep current project untouched | no, diagnose and produce a new reviewed release |
| migration fails before API admission | keep traffic on current API when compatible; capture migration backup/evidence | before retry or any DB repair |
| new API fails `/ready` with unchanged/additive compatible schema | reapply previous exact API/DB descriptor only if N/N-1 compatibility is already proven | if compatibility is unknown |
| destructive/incompatible schema or data corruption | stop admission; preserve evidence and backups | yes, named restore point and accepted data-loss window |
| public ingress fails but internal `/ready` succeeds | revert ingress release or route to previous healthy API | yes if certificate/origin changes |

Do not automate a blind down-migration or production DB restore. A restore is
accepted only from an independently verified backup into an isolated MariaDB,
with measured RPO/RTO and an owner-approved production change window.

## 10. Delivery stages and acceptance

### Stage A — read-only inventory and local canary

- capture Phase 0 facts;
- render the current production Compose with dummy secret files on the exact NAS
  Compose version;
- prove a disposable API/DB project, ingress loopback, and cleanup without
  touching production volumes;
- test a backup and isolated restore.

Acceptance: compatibility report and no production mutation.

### Stage B — manual private deployment

- install/configure Tailscale and tailnet grants;
- create the forced-command deploy identity and NAS-local secret/volume layout;
- publish exact digest images and invoke one owner-approved canary manually;
- record backup, migration, digests, `/ready`, external origin, and rollback.

Acceptance: one exact release and one rollback rehearsal through the private
path. This proves deployment mechanics, not Target/door behavior.

### Stage C — protected CI deployment

- add the `production` GitHub Environment with required reviewer;
- use GitHub-hosted runner + Tailscale workload identity federation;
- call only the forced deploy command; collect sanitized evidence;
- require an external monitor and bounded canary before success.

Acceptance: approved exact-main deployment with no public management port and a
complete release record.

### Stage D — operational hardening

- scheduled encrypted off-NAS backup and independent restore drills;
- certificate/package-credential expiry alerts;
- off-NAS `/ready` and TLS monitoring plus broker 4883 monitoring;
- log retention, alert acknowledgement, capacity thresholds, and documented
  break-glass recovery;
- 24-hour soak and mobile/Target N/N-1 checks before any commercial claim.

Acceptance: deployment, runtime service, and physical Target evidence remain
separate. Backend success does not assert door movement, relay safety, mobile
background success, or Target OTA health.

## 11. Implementation backlog

1. `DONE (live inventory)` Collect NAS/DSM/CPU/Compose/storage facts and prove
   one encrypted off-NAS backup plus isolated exact-inventory restore. A
   recurring independent backup destination remains open.
2. `DONE (repository design)` Select ephemeral Tailscale plus restricted
   OpenSSH forced command. The dedicated non-admin account passes its exact
   local sudo `status` probe, but has `/sbin/nologin` and no `.ssh/authorized_keys`,
   so it cannot carry the forced command. Do not grant administrator membership
   or broaden DSM SSH; preflight the existing SSH-capable owner account for the
   separate forced-key fallback. Owner account `noty00` has `/bin/sh`, current
   SSH access and no existing `.ssh`/`authorized_keys`, so an atomic one-key
   installation can proceed with exact NOPASSWD wrapper commands and both
   positive/negative forced-command tests. The forced key now authenticates and
   maps both requests to the dispatcher, but DSM returns permission denied while
   executing its root-owned mode-`0755` path. Live readback isolated this to
   Linux mode `0700` on both the deployment base and `bin`, not Synology ACL or
   a `noexec` mount. Correct only base to traversal-only `0711` and `bin` to
   `0755`; retain secrets, trust, incoming and release state as root-only. The
   resulting forced command executes and rejects arbitrary input, while status
   next exposed DSM sudo PATH omission of Docker; the corrected wrapper resolves
   only fixed Synology package paths or an executable PATH client. Exact owner
   installation and WSL readback now return `status=not-deployed` with exit zero,
   while arbitrary input returns exit 126. The same forced contract subsequently
   passed over the pinned private Tailscale endpoint after the narrow grant was
   saved; only the ephemeral tagged GitHub source remains unexercised.
3. `DONE (repository)` Add `compose.synology.yml` with NAS-local file secrets,
   named external volumes and loopback-only API ingress.
4. `DONE (repository)` Add exact GHCR digest publication/provenance and a signed
   release descriptor to the protected backend workflow. No image has yet been
   published by this candidate.
5. `DONE (NAS install and private owner-source status)` Add and install the fail-closed deploy
   wrapper and forced dispatcher with exact protected hashes, root ownership and
   mode `0755`. The SSH-capable owner fallback key is forced through the
   dispatcher; private Tailscale `status` returns `status=not-deployed` and an
   arbitrary command is rejected. The tagged GitHub source remains pending.
6. `DONE (NAS layout preparation)` Add and owner-execute a no-cutover legacy bootstrap for the
   confirmed DB user/password pair, active personal admin credential, exact
   target config, NAS-local secret files and external volume layout. Existing
   API/DB remained running. Independent read-only layout/ACL readback passed;
   exact boolean tenant/door/Target correlation also passed at snapshot/applied
   ACK 314. The technical path is present, while the owner lookup-disable
   decision remains separate from deployment automation.
7. `DONE (pre-cutover backup Gate)` Prove a consistent logical backup,
   authenticated off-NAS transfer, encrypted WSL copy and isolated exact-
   inventory restore before the first DB-changing deployment. Recurring 3-2-1
   scheduling and key separation remain operational hardening work.
8. `P1` Run owner-approved manual canary and rollback rehearsal.
9. `DONE (private CI status preflight)` Validate the protected GitHub `production` Environment,
   Tailscale OIDC client/tag grant, strict NAS host key and Environment
   secrets/variables. `NAS_DEPLOY_USER=noty00`, `NAS_DEPLOY_PORT=4422` and the
   public readiness URL are set. `NAS_TAILSCALE_HOST=100.95.243.92` and its
   independently matched ED25519 `NAS_DEPLOY_KNOWN_HOSTS` entry are also set.
   The exact OIDC subject is confirmed; the client ID and audience credential
   were created and both protected Environment secret names are present.
   The wildcard grant has been replaced after confirming no tagged or routed
   compatibility sources, and the user-owned WSL-to-NAS forced-SSH contract
   passes. Latest manual exact-main run `33234620284` at
   `d9ecc87e04fc2b0e57cc892e549b02ddce26184a` obtained only
   `tag:sgk-github-deploy`, reached the pinned forced SSH endpoint and retained
   `status=not-deployed`; its image publication and deployment jobs were
   skipped. The owner then stopped exactly the recorded legacy API/DB
   containers without deleting them or their volumes, opening the first-
   adoption maintenance window. This closes transport/status and concurrent-
   owner preconditions only, not release `apply` or readiness.
10. `P1` Add external readiness/TLS/expiry monitoring and alert acknowledgement.
11. `P2` Evaluate a central secret manager only when operator/host count requires
    it.

The first protected attempt with the corrected absolute Synology Docker path,
run `33235596047` at exact main `21a0124f6e4b5dfc300b205073e1b464066355e8`,
reached the two immutable image pulls but GHCR returned `unauthorized` because
the NAS had no package credential. The wrapper failed before Compose or
migration and did not attempt a database rollback. The owner restarted the
retained legacy API/DB; external `/live` returned HTTP 200 for build `7c2764a1`
and `/ready` returned the expected legacy-only HTTP 503 with every check true
except `legacy_prearm_retired=false`. The ephemeral envelope change passed fresh
Trusted, OTA and Backend checks and merge-committed as main
`42b754d75863072e4ad0af32f2667ff54ceb050c`. This admits the source only: exact
root-owned wrapper installation, a new maintenance stop, protected deployment,
matching status/readiness and backend-included access remain open.

After the exact `afda60b4...` wrapper was installed and the legacy pair was
stopped again, protected feature-main run `33240731351` passed release
signature, attestation, Tailscale OIDC, forced SSH and ephemeral GHCR
authentication. The NAS pulled exact API digest `36c777a9...` and DB digest
`4ec45e3d...`, created both project networks and started
`smart-gatekeeper-production-db-1`. DSM then rejected a nonzero Docker
`NanoCPUs` request because this DS423+ kernel lacks the CPU CFS controller. The
failure occurred before migration and the wrapper did not attempt DB rollback;
no `status=deployed` or readiness evidence exists. That wrapper version also
left the partial project for explicit recovery.

The first correction retained the portable base CPU limits and set `cpus: 0`
for migration and API in the Synology overlay. Hosted Compose rendering omitted
the field, but DSM Compose v2.20.1 preserved the zero value as a Docker
`NanoCPUs` update request. Run `33241850366` therefore failed before migration
after starting the exact new DB. Apply failure cleanup ran
`down --remove-orphans` only for the fixed production project, never
`--volumes`, recorded the cleanup result and
continues to prohibit blind DB rollback. The workflow also uses the Tailscale
action's valid `sha256sum` input. Policy PR #216, policy-connected feature PR
#215 and final policy PR #217 passed their Hosted checks and merged through
final main `bb970bb68c365140b2b1717116fc19eac307cb59`; the reviewed feature main
is `6b1f1da3359dcca95c8434b73970ba992ef9d41d`. Its backend run `33241850366`
published exact images/provenance and was owner-approved after exact wrapper
installation and a new maintenance stop. The cleanup contract passed: the
partial production DB and networks were removed without volume deletion, and
no DB rollback was attempted. Because zero does not reset this field on DSM,
the next source candidate removes `cpus` from both production inputs while
retaining memory/PID/capability/read-only hardening. Owner recovery restarted
both retained legacy containers; external `/live` returned HTTP 200 for build
`7c2764a1` and `/ready` returned the expected legacy HTTP 503 with only
`legacy_prearm_retired=false`. Protected source authorization, fresh CI and
another change window remain required. No deployed/readiness result exists yet.

CPU-field-free feature main `b6cab8384efe7b5e046841ff84681b74d0cae113`
was admitted by final policy main `7a09a25ad01e21b7d0e515cbbf96bce2ca5af23a`.
Protected run `33245672804` proved the next layer: exact DB startup and migration
`up 007` passed with a retained pre-migration backup, and the API container was
created. Loopback `/ready` did not pass, so the wrapper removed only the
partial production project, retained all external volumes, and attempted no
blind DB rollback. The retained legacy pair was restarted and public liveness
returned to HTTP 200.

The source audit isolated a file-permission contract error. The immutable API
runs as `10001:10001`, but bootstrap had installed every NAS secret as
`root:root 0600`. Docker Compose documents that a local `file:` secret is a
bind mount and its `uid`, `gid` and `mode` cannot be remapped. The corrected
layout therefore keeps the containing directory `root:root 0700`, keeps only
the DB root password `root:root 0600`, and makes API-consumed secret files
`root:10001 0640`. Host group traversal remains impossible, while the exact
container group can read only the explicitly mounted files. Failure cleanup
also retains non-secret container state and a root-only bounded API log before
removal. Protected authorization, exact NAS metadata readback and another live
window remain separate Gates.

Secret-access feature PR #223 and bootstrap-arity feature PR #226, together
with their bounded policy admission/final rotations through PR #228, passed
the required Hosted Trusted, OTA P0 and Backend checks. The reviewed backend
feature main is `3fdc615833da68af22623eefafc876d4c84b86d7`; final policy main is
`ae69332f16d855f39cec99bd46a21736194769b1`. Exact feature-main run
`33246998513` passed tests, real MariaDB verification, evidence/provenance and
both immutable image publications and now waits at protected production
approval. Approval remains withheld until bootstrap SHA-256 `1969b5a8...`,
verifier `2b58d125...`, wrapper `234231e8...`, secret metadata contracts and
`status=not-deployed` are read back from the NAS while the recovered legacy
pair remains running. These are explicit pre-cutover Gates, not deployment
evidence.

The executable bootstrap and owner checklist are in
[`backend/deploy/README.md`](../backend/deploy/README.md). Repository completion
does not close the backup/restore, first handover, live workflow, NAS readiness,
mobile, Target or physical-door Gates.

### Current isolated-restore candidate

The WSL host currently has about 902 GB free on its Linux filesystem, Docker
client/server 29.6.2, Compose 5.3.1, GPG and OpenSSL. It is therefore the
smallest independent restore lab for the first Gate without opening MariaDB on
the NAS or buying a service. Owner readback reports a 2,686,976-byte logical
database footprint across 20 tables, with the largest table at 1,638,400 bytes,
so this lab has ample capacity. The implemented path accepts a NAS dump only
when consistent read-only inventories immediately before and after it match,
verifies its SSH-transfer digest, creates an authenticated manifest, encrypts
the off-NAS bundle, and restores it into an exact-digest disposable MariaDB
bound only to WSL localhost. Owner execution created backup
`pre-cutover-20260828T155308Z-9349` from deployed source
`7c2764a1a16492ec1620079c8211b47287b1b3fd`: the dump is 792,678 bytes, its
bundle SHA-256 is `d2321993a1858ec053c614bf6aecb212012f2dd25db59ff2fd49ed42056f418d`,
and both legacy containers remained running. This is a consistent NAS-local
backup plus temporary owner-readable plaintext export. Authenticated SSH
transfer matched the sidecar, and WSL created a mode-0600 AES-256 GPG bundle;
streamed decrypt readback reproduced the exact bundle SHA-256. The dump then
restored into pinned MariaDB digest
`be981e4113326ada8d6004174dd09eeaefc03094037f811182a52d4f2e737350`
on `127.0.0.1`, with exact schema/content inventory PASS and measured RTO
1.680 seconds. This closes the first isolated off-device restore Gate for this
backup. It is not a recurring 3-2-1 or off-site backup; the encryption keys are
still on the same WSL host. Hyper Backup to another NAS/object/cloud
destination, protected key separation and owner-approved plaintext/lab cleanup
remain operational follow-ups. After owner cleanup authorization, both WSL lab
containers and their data volumes were removed and verified absent; WSL
plaintext bundle/work files were unlinked after preserving the mode-0600
encrypted bundle, authenticated manifest and restore result. Owner interactive
SSH subsequently deleted and verified absence of both exact NAS owner-home
plaintext export files. The root-only NAS backup is intentionally retained.

### First exact-main deployment attempt

Exact-main run `33199155624` built and attested both immutable backend images,
created the signed release bundle, joined Tailscale and passed restricted SSH
setup. The NAS wrapper then failed closed before migration or cutover with
`MariaDB volume is held by another running project; stop it during first
adoption`. The legacy API/DB were not removed and no new-stack readiness is
claimed. Issue #190 records the owner maintenance Gate: retain the existing
containers and backup, stop exactly the two legacy containers, rerun the
admitted deployment, then require exact source/status, loopback/public
readiness, migration, MQTT and rollback evidence.

The still-running legacy Backend reports process liveness for build `7c2764a1`
but `/ready` is HTTP 503 solely because `legacy_prearm_retired=false`; database,
schema, MQTT, runtime secrets, control/admin authentication, ACL management and
build identity checks are true. The exact-identity correlation was previously
proved, but changing the legacy lookup flag remains an explicit owner/runtime
cutover decision rather than an automatic CI side effect.

Exact run `33246998513` later reached the API readiness Gate after DB health
and migration `up 007`. The bounded failure evidence showed a running API
process and repeated MQTT `ConnectionRefusedError`; owner readback then proved
the legacy API endpoint is `tworimpa.synology.me:4883`, while the generated
`runtime.env` retained only the host and production Compose forced `8883`.
The failed partial project was removed without deleting external volumes or
attempting DB rollback, and the retained legacy pair is running again. The
source correction must copy and validate the legacy non-1883 port through
bootstrap, verifier, wrapper and Compose before another maintenance window.

## 12. Primary references

- [Synology Container Manager projects](https://kb.synology.com/en-us/DSM/help/ContainerManager/docker_project)
- [Synology Hyper Backup](https://kb.synology.com/en-global/DSM/help/HyperBackup/BackupApp_desc)
- [Synology 3-2-1 backup guidance](https://kb.synology.com/en-global/DSM/help/DSM/Tutorial/backup_backup)
- [Tailscale on Synology NAS](https://tailscale.com/kb/1074/connect-to-your-nas/)
- [Tailscale GitHub Action](https://tailscale.com/docs/integrations/github/github-action)
- [GitHub: publishing Docker images](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)
- [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [GitHub secure use and self-hosted runner risks](https://docs.github.com/en/actions/reference/security/secure-use)
- [Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)
- [Docker Compose secrets reference](https://docs.docker.com/reference/compose-file/secrets/)
