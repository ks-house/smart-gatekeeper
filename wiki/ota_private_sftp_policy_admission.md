# Private OTA SFTP policy admission -2026-10-17

Reviewed source: [PR463](https://github.com/ks-house/smart-gatekeeper/pull/463),
immutable feature commit cb7372989605e04c0ec2b4342f382c48d46ec327.

Keep the same23 protected paths, seven-workflow namespace, empty local-action
namespace, trusted validator and all18 unaffected digests. Admit exactly five
changed input hashes as one persistent baseline: the Backend status workflow,
personal mobile and Target workflows, OTA test workflow and OTA contract gate.
The feature source keeps public transport default and adds a strict opt-in
Tailscale/pin/permissions/consumer extension plus a manual read-only preflight.

The independent policy change executes no candidate code in the trusted check.
The normal inert-byte check still uses its base policy; the reviewed feature must
merge-connect this admission before its five hashes are accepted. Policy tests
allow exactly predecessor or admitted bytes for those five inputs during this
transition. Mixed bundles and unauthorized sources remain rejected.

Local feature validation:149 OTA/publisher tests,29 Backend/NAS contracts and
OTA contract PASS. This admission is not OIDC authorization, a transport switch,
SFTP authentication, publication, NAS firewall activation or device acceptance.
The owner's backup deferral461 remains in force.
