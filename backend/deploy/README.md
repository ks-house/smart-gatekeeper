# Synology backend CI deployment

This directory implements the private deployment path for the production
backend:

1. the protected backend workflow tests the exact `main` commit;
2. Buildx publishes `linux/amd64` API and DB images to GHCR;
3. the workflow records the immutable registry digests and signs a release
   descriptor inside a four-file bundle;
4. a GitHub-hosted runner joins the tailnet as an ephemeral tagged node;
5. a restricted SSH key can call only `apply` or `status` on the NAS;
6. the runner prefixes the signed bundle with a versioned GHCR authentication
   envelope derived from its short-lived `github.token`;
7. the root-owned wrapper keeps that authentication only in its root-only
   per-attempt temporary directory, verifies the signature, hashes, repositories,
   digests, schema, local volumes and secret files before it pulls anything;
8. the wrapper starts the DB, runs the backup-first migration, starts the API,
   and records success only after loopback and public `/ready` both pass.

The workflow does not send runtime credentials to the NAS. Runtime secrets
remain as root-readable files under the NAS deployment directory. The GHCR
credential is transport-only, is never added to the signed release artifact or
NAS persistent Docker configuration, and is removed on every success or failure.

## Files

- `create_release_bundle.py`: CI-side exact-digest descriptor and signature
  builder.
- `bootstrap_legacy_synology.sh`: one-time, fail-closed migration of the
  observed legacy container environment into NAS-local secret files, state and
  bind-backed volumes without stopping either legacy container.
- `verify_legacy_synology.sh`: read-only post-bootstrap permission, volume,
  running-container and aggregate DB/ACL verifier; it never prints secret
  values or tenant/credential/Target identifiers.
- `capture_legacy_inventory.py` plus `create_legacy_backup.sh`: identifier-free,
  read-only inventory and transaction-consistent logical dump. The backup is
  accepted only when required-table inventories immediately before and after
  the dump are byte-identical.
- `prepare_backup_in_wsl.py`: SSH-transfer digest check, authenticated backup
  manifest creation and AES-256 GPG encryption on the off-NAS WSL host.
- `restore_backup_in_wsl.py`: disposable localhost-only MariaDB restore using
  the repository's exact image digest, followed by table/schema/content
  inventory and RTO verification.
- `sgk_backend_deploy.sh`: root NAS verifier and deployment executor.
- `sgk_backend_ssh_dispatch.sh`: forced-command bridge for the unprivileged
  SSH deployment account.
- `runtime.env.example`: non-secret NAS runtime identifiers and exact volume
  names.
- `../compose.production.yml` plus `../compose.synology.yml`: hardened base and
  NAS file-secret/loopback overlay.

## Hard gates before the first deployment

Do not start the first deployment until all of these are true:

- an off-NAS backup has been restored successfully into an isolated MariaDB;
- the exact existing MariaDB volume or bind path has been identified from
  `docker inspect`; it must never be guessed;
- the old API and DB container names, images, mounts and restart procedure have
  been recorded;
- a change window has been accepted for stopping the old API and DB before the
  new Compose project opens the same DB volume;
- the DSM reverse proxy still targets `http://127.0.0.1:8000` and the public
  `/ready` URL has a valid certificate;
- the repository's trusted-workflow policy rotation for the workflow change
  has been separately reviewed and admitted;
- the GitHub `production` Environment requires an owner reviewer.

The wrapper never performs a blind DB restore or down-migration. A migration or
readiness failure is a stop-and-review condition. If an apply attempt has
already materialized the new Compose project, the wrapper removes only that
partial project with `down --remove-orphans`; it never adds `--volumes`, so the
external MariaDB, API-state, APK and migration-backup volumes remain intact.

### DS423+ CPU-controller compatibility

DSM 7.3 on the observed DS423+ kernel does not expose the CPU CFS controller
required by Docker's nonzero `NanoCPUs` field. The portable production Compose
keeps its `0.5` migration and `1.0` API CPU limits for capable Linux hosts. The
Synology overlay sets those two fields to zero so the merged NAS configuration
omits `cpus` and container creation does not fail after the DB has started.
Memory and PID limits, dropped capabilities, read-only filesystems and
`no-new-privileges` remain enforced.

## 1. Inventory the current containers and volumes

Run on the NAS with owner-approved sudo. These commands are read-only:

```bash
sudo docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
sudo docker inspect CURRENT_DB_CONTAINER \
  --format '{{range .Mounts}}{{println .Type .Name .Source .Destination}}{{end}}'
sudo docker inspect CURRENT_API_CONTAINER \
  --format '{{range .Mounts}}{{println .Type .Name .Source .Destination}}{{end}}'
sudo docker volume ls
```

The mount whose destination is `/var/lib/mysql` becomes
`MARIADB_DATA_VOLUME`. If it is a Docker named volume, use that exact name. If
it is a bind mount, create an explicitly named bind-backed volume only after
verifying the exact device path:

```bash
sudo docker volume create --driver local \
  --opt type=none --opt o=bind --opt device=/EXACT/EXISTING/MARIADB/PATH \
  sgk-existing-mariadb
sudo docker volume inspect sgk-existing-mariadb
```

Use the same bind-backed-volume pattern when APK artifacts or migration backups
must remain in a Hyper Backup-visible `/volume1/...` directory. Never point two
running MariaDB containers at the same data directory.

### Current DS423+ adoption map (owner inventory, 2026-08-29)

The current personal project is `smart_gatekeeper` and the first-adoption map
is now partially fixed:

| New runtime field | Observed current state |
|---|---|
| `MARIADB_DATA_VOLUME` | `smart_gatekeeper_mariadb_data` — existing named volume, preserve exactly |
| `DB_RUNTIME_USER` | `gatekeeper_user` — confirmed from the running API, preserve exactly |
| `APK_ARTIFACTS_VOLUME` | current bind source `/volume1/docker/smartbox_ota/gatekeeper_apk`; create a named bind-backed external volume pointing to this exact path |
| `API_STATE_VOLUME` | no current `/var/lib/smart-gatekeeper` mount; preserve the confirmed 135-byte `/app/target_config.json` (SHA-256 `c5668365bd130ec42c7f49aafc53491b1a6ad3a3eb4858f3215b83de3505ece9`) before creating the new volume |
| `MIGRATION_BACKUPS_VOLUME` | create a bind-backed volume under the root-owned deployment path after off-NAS backup policy is fixed |

The legacy DB's SQL bind mounts under `/docker-entrypoint-initdb.d` are
initialization inputs, not the persistent database. They are not copied into the
new project; the custom DB image plus backup-first migration runner replaces
them. The old `smart_gatekeeper` API and DB must both be stopped before the new
`smart-gatekeeper-production` project opens the preserved DB volume.

The checked-in bootstrap script automates only the non-cutover preparation for
this exact observed layout. Review it, copy it to the NAS through an already
trusted path, and run it while both legacy containers are still running:

DSM's interactive SSH endpoint may reject modern `scp` because OpenSSH now
uses the SFTP subsystem by default while this NAS exposes SFTP on a separate
port. In that case stream the exact file over the authenticated interactive SSH
channel and verify its digest before execution:

```bash
ssh -T -p 4422 noty00@tworimpa.synology.me \
  'umask 077; cat > /tmp/sgk-bootstrap-legacy.sh && chmod 700 /tmp/sgk-bootstrap-legacy.sh && sha256sum /tmp/sgk-bootstrap-legacy.sh' \
  < backend/deploy/bootstrap_legacy_synology.sh
```

Do not disable host-key verification or weaken SSH algorithms to suppress a
post-quantum negotiation warning. That warning is independent of an SFTP
subsystem rejection and remains a NAS OpenSSH upgrade/hardening item.

```bash
sudo /tmp/sgk-bootstrap-legacy.sh \
  --public-ready-url https://tworimpa.synology.me:4442/ready
```

It verifies the legacy project/container/mount identities, confirms the API and
MariaDB runtime passwords match in memory, copies the MQTT CA and the exact
target-config bytes, creates three bind-backed external volumes, and writes
root-only secret files plus `runtime.env`. It never prints secret values, opens
the MariaDB files, or stops/restarts containers. Existing destinations are
accepted only when byte-identical; a mismatch is a hard stop. Its successful
result is layout preparation, not a backup, restore, cutover or deployment.
DSM may reset `PATH` for `sudo bash`; the helper resolves Docker only from the
current executable path or the fixed Container Manager/Docker package paths and
never downloads or substitutes a Docker client.
The script is compatible with DSM Bash 4.4 strict-unset behavior: derived local
variables are assigned only after their source locals have been initialized.

After a successful bootstrap, transfer `verify_legacy_synology.sh` through the
same authenticated exact-file channel and run it with `sudo`. It is read-only:
it verifies root-only file contracts, exact bind-volume devices, unchanged
running legacy containers, target-config digest and aggregate DB/ACL counts.
It deliberately does not print runtime values or any tenant, credential, door
or Target identifier. The final identity correlation runs inside the existing
API container and emits booleans only: configured personal tenant/door/Target,
active credential/grant, latest snapshot and exact applied ACK must all match.

### Create and prove the first off-NAS backup

Transfer both backup helpers through the authenticated SSH channel, compare the
reported SHA-256 values with local `sha256sum`, then run from the DSM owner's
home directory:

```bash
cd ~
sudo /tmp/sgk-create-legacy-backup.sh \
  --inventory-script /tmp/sgk-capture-legacy-inventory.py \
  --export-dir "$(pwd -P)" \
  --export-owner "$(id -un)"
```

The command does not stop/restart containers or mutate SQL. It performs a
read-only consistent inventory, a `mariadb-dump --single-transaction`, and a
second inventory. Any required-table change during the interval is a hard
failure and no export is accepted; simply retry later. A successful command
keeps a root-only NAS copy and creates a temporary mode-`0600` owner export for
authenticated transfer. This export is compressed plaintext and is not yet the
accepted off-NAS backup.

In WSL, use `umask 077`, stream the exact bundle and sidecar named by the NAS
result over SSH, and put them in a private Linux-filesystem directory. Then run:

```bash
.venv/bin/python backend/deploy/prepare_backup_in_wsl.py \
  --bundle /ABSOLUTE/PRIVATE/PATH/pre-cutover-TIMESTAMP-PID.tar.gz \
  --sidecar /ABSOLUTE/PRIVATE/PATH/pre-cutover-TIMESTAMP-PID.tar.gz.sha256 \
  --work-dir /ABSOLUTE/PRIVATE/PATH/work \
  --key-dir /ABSOLUTE/PRIVATE/PATH/keys
```

The helper validates the transport digest and exact archive members, creates
mode-`0600` manifest/encryption/restore secrets without overwriting existing
keys, authenticates the manifest against the repository schema identity, and
writes a GPG AES-256 encrypted bundle. Keep the key directory separately
protected; encryption without retained keys is not recoverable.

Use the paths printed by that command for the isolated restore:

```bash
.venv/bin/python backend/deploy/restore_backup_in_wsl.py \
  --dump /ABSOLUTE/PRIVATE/PATH/work/BACKUP_ID/database.sql \
  --manifest /ABSOLUTE/PRIVATE/PATH/work/BACKUP_ID/backup-manifest.json \
  --manifest-key-file /ABSOLUTE/PRIVATE/PATH/keys/backup-manifest-hmac.key \
  --root-password-file /ABSOLUTE/PRIVATE/PATH/keys/restore-mariadb-root-password.key \
  --result-output /ABSOLUTE/PRIVATE/PATH/work/BACKUP_ID/restore-result.json
```

The restore DB binds only an ephemeral `127.0.0.1` port. The harness first
requires an empty database, imports the real dump, checks required tables,
foreign-key invariants and exact schema/content hashes, and measures import plus
verification RTO. It intentionally preserves the disposable container and
volume for owner inspection. Removing the lab and plaintext files is a separate
destructive cleanup decision after the PASS result and encrypted-copy readback.

## 2. Create release and SSH identities

Generate two independent keys on a trusted workstation. Do not print private
keys or add them to the repository:

```bash
umask 077
mkdir -p "$HOME/.config/smart-gatekeeper-deploy"
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 \
  -out "$HOME/.config/smart-gatekeeper-deploy/release-signing.pem"
openssl pkey \
  -in "$HOME/.config/smart-gatekeeper-deploy/release-signing.pem" \
  -pubout \
  -out "$HOME/.config/smart-gatekeeper-deploy/release-signing-public.pem"
ssh-keygen -t ed25519 -a 100 \
  -f "$HOME/.config/smart-gatekeeper-deploy/nas-deploy-ed25519" \
  -C smart-gatekeeper-github-deploy
```

Store the release private key and SSH private key only as GitHub `production`
Environment secrets. Copy only the release public key and deploy SSH public key
to the NAS through an already trusted administration path.

## 3. Install the root-owned NAS endpoint

Create a dedicated DSM user such as `github-nas-deploy`. It must not be an
administrator and must not join the Docker group. First verify that the exact
DSM/OpenSSH configuration admits that non-admin account for a forced command;
some DSM configurations restrict SSH login to administrators. If it does, do
not broaden SSH policy just for CI. Instead attach a separate forced deployment
key to the existing owner account with the same exact sudoers restrictions, or
run a separately reviewed private SSH endpoint. In either case the CI key must
remain forced-command-only and must never inherit interactive administrator or
Docker-group access. When the owner-account fallback is selected, substitute
that exact account in both sudoers lines, the forced-SSH test and
`NAS_DEPLOY_USER`; do not grant NOPASSWD access to any additional command. Then
install the two scripts, public signing key, runtime file and secret directory:

```bash
sudo install -d -o root -g root -m 711 \
  /volume1/docker/smart-gatekeeper-backend
sudo install -d -o root -g root -m 755 \
  /volume1/docker/smart-gatekeeper-backend/bin
sudo install -d -o root -g root -m 700 \
  /volume1/docker/smart-gatekeeper-backend/{trust,secrets,releases,incoming}
sudo install -o root -g root -m 755 sgk_backend_deploy.sh \
  /volume1/docker/smart-gatekeeper-backend/bin/sgk_backend_deploy.sh
sudo install -o root -g root -m 755 sgk_backend_ssh_dispatch.sh \
  /volume1/docker/smart-gatekeeper-backend/bin/sgk_backend_ssh_dispatch.sh
sudo install -o root -g root -m 644 release-signing-public.pem \
  /volume1/docker/smart-gatekeeper-backend/trust/release-signing-public.pem
sudo install -o root -g root -m 600 runtime.env \
  /volume1/docker/smart-gatekeeper-backend/runtime.env
```

Mode `0711` on the deployment base grants path traversal without directory
listing, and mode `0755` on `bin` permits the forced SSH account to execute only
the root-owned dispatcher selected by its `authorized_keys` entry. Keep
`trust`, `secrets`, `releases`, `incoming`, migration backups and runtime files
root-only; never apply these traversal modes recursively.

DSM may reset `PATH` for the forced command's `sudo -n` process. The wrapper
therefore resolves Docker only from the executable Container Manager/legacy
Docker package paths, `/usr/local/bin`, or an executable discovered in the
current PATH. Do not widen sudo `secure_path`, create a Docker symlink, or add
the deploy account to the Docker group.

Copy `runtime.env.example` to `runtime.env`, replace every placeholder and use
the exact external volume names found in step 1. `SGK_SECRET_DIR` must remain:

```text
/volume1/docker/smart-gatekeeper-backend/secrets
```

Create these non-empty files with mode `600`, owned by root:

```text
db_root_password
db_password
mqtt_password
mqtt_ca.pem
api_key
ops_hmac_key
command_signing_scalar
admin_identities.json
personal_admin_password
acl_enrollment_auth.json
acl_legacy_ref_hmac_key
acl_admin_api_key
acl_target_auth.json
acl_signing_scalar
```

Reuse confirmed current production values through a protected migration
procedure. Do not derive, echo or replace them from CI. Validate permissions
without reading contents:

```bash
for file in /volume1/docker/smart-gatekeeper-backend/secrets/*; do
  sudo stat -c '%n %U:%G %a %s-bytes' "$file"
done
```

Do not install a long-lived GHCR PAT or root Docker login on the NAS. The
protected deployment job has `packages: read` and streams only its short-lived
repository-scoped `github.token` in the `SGK-GHCR-AUTH-V1` envelope immediately
before the signed bundle. The wrapper writes the encoded Docker auth value only
under its root-only per-attempt directory and removes it through the common
cleanup trap. The CI deploy SSH key remains a separate transport credential.

## 4. Restrict sudo and SSH

Create `/etc/sudoers.d/smart-gatekeeper-backend-deploy` with the exact DSM user
and these two exact commands, then validate it with `visudo -cf`:

```sudoers
github-nas-deploy ALL=(root) NOPASSWD: /volume1/docker/smart-gatekeeper-backend/bin/sgk_backend_deploy.sh apply
github-nas-deploy ALL=(root) NOPASSWD: /volume1/docker/smart-gatekeeper-backend/bin/sgk_backend_deploy.sh status
```

The deploy user's `authorized_keys` entry must force the dispatcher and disable
interactive/forwarding features:

```text
restrict,command="/volume1/docker/smart-gatekeeper-backend/bin/sgk_backend_ssh_dispatch.sh" ssh-ed25519 REPLACE_WITH_DEPLOY_PUBLIC_KEY smart-gatekeeper-github-deploy
```

Test from the tailnet before GitHub is enabled:

```bash
ssh -p 4422 github-nas-deploy@NAS_TAILSCALE_NAME status
ssh -p 4422 github-nas-deploy@NAS_TAILSCALE_NAME 'sh -c id'
```

The first command should return `status=not-deployed`; the second must fail.
Port `4422` is the currently reported DSM SSH port, but confirm it over the NAS
Tailscale interface rather than relying on the public router forward.

## 5. Configure Tailscale and GitHub

Create a Tailscale workload-identity/OIDC client limited to the tag
`tag:sgk-github-deploy`. Tailnet policy must allow that tag to reach only this
NAS on TCP `4422`; it does not need DSM UI, the Docker socket, DB, MQTT or public
API ports.

Collect the NAS SSH host key through a trusted LAN/Tailscale path and compare
its fingerprint with the NAS-local host public key before storing it. Runtime
`ssh-keyscan` is intentionally not used by CI.

Configure the GitHub `production` Environment:

| Type | Name | Value |
|---|---|---|
| secret | `NAS_BACKEND_RELEASE_SIGNING_KEY_PEM` | P-256 release private key PEM |
| secret | `NAS_DEPLOY_SSH_PRIVATE_KEY` | dedicated Ed25519 private key |
| secret | `NAS_DEPLOY_KNOWN_HOSTS` | pinned NAS host-key line for the tailnet hostname/port |
| secret | `TS_OIDC_CLIENT_ID` | Tailscale workload identity client ID |
| secret | `TS_OIDC_AUDIENCE` | exact configured OIDC audience |
| variable | `NAS_TAILSCALE_HOST` | MagicDNS name or stable tailnet address |
| variable | `NAS_DEPLOY_PORT` | confirmed tailnet SSH port, normally `4422` here |
| variable | `NAS_DEPLOY_USER` | exact forced-command DSM account; use the owner fallback only when DSM blocks the dedicated non-admin account |
| variable | `NAS_PUBLIC_API_URL` | existing public API origin, for Environment UI |

Require an owner reviewer on `production`. The workflow uses exact-commit
action pins, exact image digests, strict host-key checking and a non-cancelled
deployment concurrency group.

Before approving any deployment, run the workflow's manual
`nas_private_status_preflight` job from `main`. It obtains an ephemeral
`tag:sgk-github-deploy` identity through OIDC, uses the pinned NAS host key and
invokes only the forced `status` command. It accepts exactly one
`status=not-deployed` or `status=deployed` line and uploads the complete status
readback as `nas-private-status-<sha>-attempt-<attempt>`. This manual path has no
checkout, release signing, image publication or `apply` step. A successful run
proves the tagged GitHub runner can reach the restricted SSH endpoint; it does
not deploy or change the NAS.

## 6. First adoption and later deployments

For the first adoption only, use an owner-approved maintenance window:

1. finish and verify the off-NAS backup/isolated restore;
2. pass the manual `nas_private_status_preflight` from exact `main` and retain
   its status artifact;
3. record old container images, mounts, environment and restart commands;
4. stop the old API and old DB so neither port `8000` nor the MariaDB data
   directory has two owners;
5. approve the `production` GitHub deployment;
6. require `status=deployed`, the exact `source_sha`, and matching `status`
   readback in the workflow artifact;
7. verify public `/ready`, app/backend behavior, MQTT connectivity and logs;
8. keep old images and the pre-migration backup until the accepted rollback
   window closes.

### 2026-08-29 live first-adoption window

The owner recorded legacy `gatekeeper-api` (`smart_gatekeeper-api`) and
`gatekeeper-db` (`mariadb:10.11`) as running, then stopped exactly those two
containers without deleting either container or any volume. Exact-main manual
run `33234620284` at `d9ecc87e04fc2b0e57cc892e549b02ddce26184a`
subsequently passed the protected Tailscale OIDC, pinned host-key and forced
status path with retained `status=not-deployed`. The next admitted backend
`main` run must either complete `status=deployed` plus matching status readback
or fail closed; until that evidence exists, recovery is still starting the two
recorded legacy containers.

Feature-main run `33240731351` later authenticated to GHCR and pulled the exact
API digest `36c777a9011c0cf91e770728a797bd91879da8dc174a59d01f88677317a2aa0e`
and DB digest `4ec45e3de3a6ce14814af951f7dab8b0bda738d33b4e6b9426a71c774590834d`.
The new DB container started, but DSM rejected the following service before
migration with `NanoCPUs can not be set`. The installed wrapper correctly did
not attempt a DB rollback, but that version did not yet remove the partial
Compose project. Restore the retained legacy pair before retrying and do not
delete the shared MariaDB volume. The source correction described above is not
a deployed result until its protected policy, CI, root-owned wrapper install
and a new approved run all pass.

After adoption, an admitted `main` backend change automatically builds and
publishes immutable images. Deployment still pauses at the protected
`production` Environment reviewer. A green deployment proves backend image,
migration and readiness results only; it does not prove mobile install, Target
OTA, BLE, relay or physical-door behavior.

## Local validation

```bash
python -m unittest backend.tests.test_nas_backend_deploy -v
python scripts/ops_commercial_gate.py contract
docker compose -f backend/compose.production.yml \
  -f backend/compose.synology.yml config --quiet
```

The final Compose command also requires the non-secret runtime variables and
dummy exact image digests shown in the CI workflow.
