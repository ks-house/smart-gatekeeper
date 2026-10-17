> Current operating acceptance: [2026-10-17 follow-up results](followup_acceptance_2026_10_17.md). Earlier pending checkpoints below are historical.

# Home Assistant availability and lifecycle observer

## Contract

Issue441's previous HA stop is not retrospectively assigned a cause. The recorder
marks its earlier run unclean; preserved pre-recovery states end2026-10-10T10:19:18Z.
Container Manager retains successful starts and later controlled stops with exit0,
but no corresponding original die/OOM record in the bounded available archives.
NAS boot is2026-10-13T09:38:59Z. Missing stop evidence cannot prove a particular
crash, actor or reboot cause.

HA's installed unless-stopped policy remains read back on the same image/container.
The owner requests remaining recurrence/alert work. The separate root observer
never starts/stops HA, Docker or a device; it only observes and alerts the owner.

## Observation

The fixed configuration binds the actual HA container ID/image, HTTPS origin
https://tworimpa.synology.me:4123/ and NAS owner noty00. Every30 seconds the observer
checks container running/exit/OOM/restart metadata, HTTP200, a real TLS WebSocket101
handshake and the first HA auth_required frame. It verifies certificate CA/hostname,
WebSocket Accept identity and frame/header/deadline bounds.

On the NAS, the public origin uses local transport with original public SNI/Host.
That proves HA/nginx/TLS ingress, not WAN reachability. Independent WSL probes use
the real external route. A NAS-hosted observer also cannot notify while the NAS
itself is powered off; it is intended to detect an unavailable HA on a running NAS.

Finite Docker events queries bind one container, explicit since/until and allowed
lifecycle actions. Only action/time/exit/signal survive; labels/environment values
are discarded. No Docker log endpoint or tail-all query is used. Missing lifecycle
observation also creates a failure instead of silently claiming complete evidence.

## Evidence and alerts

Root-private0600 JSONL and state persist on volume1 under
/volume1/smart-gatekeeper-operations-private/ha-health (directory0700).
Rotate observation files at about1MB and retain five backups. Persist notification
intent before invoking the notifier; retry failed delivery, and retain bounded
queue/overflow counts and transition evidence. Only the current incident's state
and non-secret container/health metadata are recorded.

Two consecutive failures open an incident; two consecutive healthy checks recover
it. Fixed argv invokes Synology synodsmnotify for the exact owner noty00, with an
incident/phase tag. No administrator group, email, phone or external recipient is
selected. A zero notifier result proves NAS notification acceptance; UI readback
or delivery evidence is required before claiming the owner-visible route verified.

Installation captures reviewed source/config and the fixed systemd unit, preserves
old files and state, validates systemd configuration and same-image health before
enabling only this observer. Failed installation restores those observer files
and previous enable/running state. It does not edit HA credentials, broker/OTA/SSH
policy or restart the HA service.

## Validation

Twelve regressions cover real local TLS/WebSocket exchange, wrong hostname/
untrusted CA/invalid Accept/non-HA payload rejection, TLS bypass refusal, privacy/
owner/config bounds, durable failure/retry/recovery ordering, collection failure,
persist-before-notify, journal rotation and symlink refusal. Backend439/14 explicit
opt-in skips PASS. Actual NAS candidate observes HTTP200/WebSocket101/auth_required
and current container metadata with no errors. It sends no notification and does
not yet install a production service.

Service installation, owner-visible test alarm/recovery and persistent repeated
healthy samples remain operating acceptance gates. Do not close441 from source/CI.

## DSM7 native notification format

Actual owner route testing establishes that DSM7 rejects arbitrary title/body
strings. Use the installed generic desktop mail-string key
DSMSupportFormCustomMessage and its documented custom-variable JSON mechanism,
with exactly %CUSTOM_MSG%. No vendor text/notification settings or package are
modified. The actual native call returns0 and the logged-in owner DSM notification
list displays the labeled Smart Gatekeeper diagnostic message. Full observer
failure/recovery path acceptance is still required after this source update.

[Synology native notification interface](https://help.synology.com/developer-guide/resource_acquisition/sysnotify.html).
