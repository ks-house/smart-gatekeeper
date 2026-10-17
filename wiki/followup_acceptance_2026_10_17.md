# 2026-10-17 remaining follow-up operating acceptance

The three follow-ups identified at goal start are accepted: Gatekeeper447,
Gatekeeper441 and SmartBox7. Signed audit b4f54ae13eea4e6da6cf6447ce26d7f1 binds
the current operating evidence below. Source/CI, runtime and physical proof remain
separate.

## HA447 event JSON

PR455 b2bcada passes Backend39006628363/OTA39006628358/trusted39006628381,
merged64b5c2f8. Normal approved Backend39006782137 succeeds, including immutable
images/evidence and NAS deployment. Actual API build remains64b5c2f8 with all
readiness checks; current main also contains standalone NAS operator changes.

Corrected retained discovery has no scalar value_template and preserves the
existing event types, QoS, state/attributes topic and identity. Actual installed
HA2026.8.1 callback/renderer accepts four real projected fixtures in isolation.

Independent persisted production evidence:
- A naturally generated ACCESS_SESSION_TERMINATED event is integrity_status=verified.
- Its privacy marker911-152 outbox row is created2026-10-17T05:49:02.495Z, published
  once at05:49:02.572Z, with pending outbox count0. Database UTC offset is0.
- HA records the same marker/event_type=terminated and actual event timestamp
 05:49:02.555Z. Earlier pre-fix records remain unknown with no event_type.
- No synthetic production access event or outbox reset/replay was injected.

The bounded live observer started19 seconds after that event and correctly reports
no event in its later window. Its historical receipt is not relabelled successful;
the independent recorder/outbox/integrity join is the acceptance proof.
A terminated event is not successful physical passage or a particular phone's
success.

## HA441 recurrence evidence and owner alarm

Restart policy unless-stopped is read back; original HA image/container/start and
private account configuration are preserved. Standalone service
smart-gatekeeper-ha-health is enabled/active, with persistent private Btrfs evidence.
The current reviewed monitor is SHA94705f01f5bc1ad7674cca77b0c7ea6d1b6eda0dd6c118cd409dcce221fc8826.
Audit shows175 healthy samples, zero current failures and no queued notifications.
Independent external WSL HTTP200/TLS WebSocket101/auth_required also pass.

PR45673f6b2c passes Backend39007794214/OTA39007794212/trusted39007794229,
merged8d4bcc64. DSM7 native-notification correction PR4572fa311c passes
Backend39009335683/OTA39009335629/trusted39009335520, merged23b2b529.
Source-only Backend39007952806/39009770460 are cancelled, without a second API rollout.

Actual owner-only test fb0ff5bf creates failure then recovery through persisted
intent and the installed notifier. The logged-in owner DSM history independently
shows both labeled notices at15:26:08/09 KST. The real HA is not stopped for this
test. DSM7 uses its installed generic desktop mail key and custom-variable JSON;
no vendor resource, recipient group or email setting is changed.

Installer adaptation to measured systemd219 uses separate enable/start and
property=value parsing; initial unsupported-option failures restore only observer
files. No HA interruption or new SSH permission.

Preserved recorder/log archives identify an unclean earlier run and bound available
history; they cannot establish the original termination cause. Do not turn current
exit0/OOMfalse into a historical cause. Future bounded lifecycle/health evidence is
now retained. NAS reboot/failure injection, whole-NAS outage alerts and continuous
external WAN monitoring remain outside this acceptance.

## SmartBox7 deployed diagnostic failure and recovery

PR15/source9e46d4e passes hosted39010352192 Python/native/C6 and merges2c148e19.
Redundant main39011920146 is cancelled; no new firmware publication is required.
Installed version stays0.1.0-ge0323a0, protected artifact SHA
333e23df00876b5464689a9a7dda93b0492989e4055c97c9814878a50d200fd3.

Native isolated nginx52 cases prove authentication, exact peer/account/path,
server-clock expiry, methods and header stripping. Source helpers have four Python
contract regressions, native13 and placeholder C6 PASS.

Actual same-version admission ea897694 first checks the artifact/version/credentials,
requires real local trace self-records, observes one no-update device request and
measures its original HTTP peer. MQTT's broker-visible private address is not
substituted for the OTA HTTP peer. Trace logs use a separate root/http traversal and
write-only location; signing/control directories are not weakened. Retry HEADs until
the reloaded nginx workers actually produce both records. Exact trace files are cleaned.

Signed operating test357864821 accepts:
| Observation | Attempts | State/phase | HTTP | millis | FSM |
|---|---:|---|---:|---:|---|
| Before | 2 | UP_TO_DATE/VERSION | 200 | 32421139 | IDLE |
| Injected manifest failure | 3 | FAILED/VERSION | 404 | 32451213 | IDLE |
| Recovery | 4 | UP_TO_DATE/VERSION | 200 | 32511362 | IDLE |

The temporary rewrite is scoped to one measured peer/OTA account/version path,
at most120 server-clock seconds; normal auth/access/proxy phases remain.
An independent watchdog is armed. Both includes are removed, original stable
guard hashes preserved and Backend readiness passes. Both test commands are
trigger_ota, QoS1/nonretained. No actuator command; no firmware phase or observed
reboot. Uptime continuity is software evidence, not physical lid/electrical proof.

## Additional finding requiring a separate owner decision

NAS reports an existing Gmail OAuth refresh error; a separate Synology-account
email route is enabled but email delivery was not verified. New [issue458](https://github.com/ks-house/smart-gatekeeper/issues/458)
tracks this extra finding. The owner has been asked whether to restore that Gmail
path. No Google login, token change, email-setting mutation or external test mail
is performed without that decision. Verified DSM desktop delivery is not email
delivery proof. The original three issue gates do not silently certify this channel.

Additional general NAS settings authority is only2026-10-17. Physical/electrical/OEM
and other project release gates are not closed by these software operating results.
