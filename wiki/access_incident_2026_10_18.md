# Access incident review —2026-10-18

Status: read-only diagnosis. Follow-up [issue470](https://github.com/ks-house/smart-gatekeeper/issues/470); related
[426](https://github.com/ks-house/smart-gatekeeper/issues/426),
[51](https://github.com/ks-house/smart-gatekeeper/issues/51) and
[50](https://github.com/ks-house/smart-gatekeeper/issues/50).

## Confirmed evidence

The owner reports failed automatic recognition and the Smart Key application's
manual open. The existing diagnostic token, independent access/health histories,
incident-time mobile snapshots and bounded read-only NAS database/HTTP logs are
used; no owner log export or induced opening is requested.

The same diagnostic phone credential accounts for the automatic session and both
manual proofs. This is a credential correlation, not a claim about a person's
identity. The phone reports about2.038s to ARM (unverified phone wall clock).
Verified Target events independently establish GATT/proof/ARM and ARM_TIMEOUT.

The matched signed sensor window lasts60,028ms:468 samples,118 valid,350 timeouts,
8 in-range at800mm, blocked samples0. Exact-window unsigned qualification reports
max near streak2, candidates0, triggers0. These establish the missing sensor
qualification, not physical arrival or a hardware/electrical root cause.

Both manual HTTP requests return200 and record broker acceptance. Target signed
manual completion monotonic positions are1.381s and12.655s after the automatic
timeout, within the same boot. A separate signed RELAY_HOLD sample reports
relay_commanded_on=true and pin level0. No contact/load/door-motion observer is
available, so physical success remains unconfirmed despite these records.

Full fixed-window health paging returns120 rows in one boot; the largest
observed sample gap is36.437s. This is sampled coverage, not continuous
network proof. The relevant historical snapshot preserves manual context that
the latest snapshot's short lifecycle list no longer contains. Cumulative mobile
loss counters do not measure loss in this incident. Recent reports from other
phones are not used as proof of this phone's success.

## Source-confirmed delay mechanism

Installed firmware2.1.525+main.ga63ca41, exact sourcea63ca41:

- src/main.cpp isAccessPathCritical includes ARMED, RELAY_HOLD and COOLDOWN.
- Its main loop calls MqttManager::update only outside that critical path.
- MqttManager::deferForAccessCritical sends prepared immutable status in a
  worker, explicitly excluding receive callbacks, ACL mutation and actuators.
- Pending signed commands are authorized/dispatched only once receive processing
  resumes. Thus broker ACK while ARMED is not an immediate Target action.

This confirms a software mechanism consistent with the delayed manual records.
Do not equate the compressed Backend receipt sequence with event occurrence:
the Target events use their own boot-monotonic clocks, and the mobile and server
clock domains remain separate. Sensor wiring, ECHO protection, relay contacts and
door mechanics are not diagnosed from NO_ECHO/FAULT or a GPIO report alone.

## Current state and next work

Backend readiness passes all12 checks; fresh Target health remains same boot,
IDLE with relay commanded OFF and audit queue depth0/gap=false/stalled=false.
A fresh post-review sample still reports unsigned sensor NO_ECHO/clearance FAULT
with the last valid sample about51s earlier. Do not call automatic opening
healthy or infer a hardware fault from this snapshot. Current RF reception and
physical door operation remain unproven.
The new issue tracks a safe explicit manual-priority/rejection policy and honest
delivery stages, with isolated busy-state/TTL/replay/OTA regressions before any
behavior change. No such fix or deployment is claimed by this review.

Private evidence retains original clocks, identity correlation, records and
query bounds under a0700 local directory; public source contains no operational
timestamps, raw phone/Target/session identifiers, credentials or log dumps.
No door/relay command, reboot, OTA, service/NAS change, sensor threshold/FSM edit,
or deferred backup461 action was performed.


## Owner-authorized correction

The owner subsequently requested a fix. See
[manual_open_priority.md](manual_open_priority.md) for the copy-only receive
worker and fresh signed-manual priority over a local automatic sensor wait.
The original evidence remains historical. Source/tests do not by themselves
prove installation, a healthy sensor or physical door motion.


## Post-fix manual acceptance

[PR472](https://github.com/ks-house/smart-gatekeeper/pull/472) is merged and
firmware2.1.552+main.g3edc4b4 is installed with a new boot, VALID image and
verified healthy readiness samples. The owner confirms manual door opening is
normal; a signed manual completion corroborates that use. See
[manual_open_priority.md](manual_open_priority.md) for publication/install proof.
This does not retroactively prove the original incident's physical outcome.
The post-install window contains no automatic ARM/superseded event, so field
preemption and automatic sensor qualification remain separate unclosed gates.
