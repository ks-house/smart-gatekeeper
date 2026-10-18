# Manual MQTT priority during a local automatic sensor wait

Tracks [issue470](https://github.com/ks-house/smart-gatekeeper/issues/470).
Diagnosis: [access_incident_2026_10_18.md](access_incident_2026_10_18.md).
Stage: merged, privately published, installed/VALID and owner-confirmed manual door use.
The specific ARMED preemption case remains field-unobserved.

## Authority and transport

MqttIngressWorker leases the existing established PubSubClient/TLS socket,
excluding connect, status-write, normal receive and OTA owners. One receive pass
copies a bounded frame. Its callback cannot authorize, write replay state,
apply ACL/config, reboot, start OTA or operate the relay. Main keeps progressing
the sensor/FSM/relay timer during a blocked read or reply write. The receiver
runs below loopTask priority so it does not preempt pulseIn sampling. Watchdog, heap
reserve and largest-block checks guard task creation.

Only main applies the existing exact namespace, schema, signature, target/boot,
clock, TTL and durable replay admission. A fresh manual_remote may supersede a
local authenticated ARMED sensor wait. GATT's recursive control lock covers
validating/reserving the manual lifecycle identity, retiring the automatic
lifecycle as existing SESSION_SUPERSEDED, sealing its sensor window and
dispatching the effect. Freshness is
rechecked inside this lock. Invalid/expired/duplicate/NVS-failed inputs cannot
cancel the automatic wait or produce an extra effect.

AUTH_PENDING, RELAY_HOLD, COOLDOWN, OTA, pending GATT ingress/output or an active
legacy signed-MQTT lifecycle reject the priority effect. Rejected commands are
durably retired rather than resurrected after returning idle. A frame received
in a critical phase keeps its critical dispatch semantics after the phase ends.
The normal idle signed-command path and N/N-1 terminal vocabulary stay intact.

Critical application ACKs are immutable worker writes; an uncertain write stops
further reads on that stream. Idle ACK flushing uses reply-only mode, leaving
new idle requests to normal receive. If idle task allocation fails, use the
existing serialized idle writer so an unsendable ACK cannot starve receive. Transport ACK, Target software effect and
physical door movement remain distinct.

## Bounds and recovery

Use one1536-byte payload slot and bounded topic/reply buffers, one6KB task and
the same socket, not a second TLS connection or8KB ACL queue. Only a deferred
ACL refresh flag is retained: idle exact-topic re-subscription requests the
broker's latest retained ACL, then normal signature/watermark validation and
application ACK proceed. Oversized command frames cannot be authorized.
Polling uses unsigned elapsed intervals across millis wrap and long idle gaps.

Sensor thresholds/qualification, ECHO/GPIO, relay polarity, hold/cooldown,
automatic acceptance and OTA dual-slot/health/rollback policy are unchanged.
Existing sensor NO_ECHO/FAULT is not made healthy or diagnosed as hardware
failure by this fix.

## Validation boundary

- Actual production C++ security/FSM regressions cover forged/expired/clock,
  NVS failure, nonmanual, fresh manual, duplicate, active relay/cooldown,
  no later resurrection, legacy ARM rejection and crash-before-completion.
- A real blocked-thread transport fixture covers independent control progress,
  exclusive adoption, immutable replies, ACL-sized/truncated input, partial
  writes, reply-only mode, watchdog/allocation failure and timer wrap.
-490 root tests PASS with14 environment skips; latest focused34 tests PASS with
  one broker-integration skip. OTA contract and42 trusted policy tests PASS.
- ESP32-C6 default compilation passes with the public credential-free fixture.
  A local lab experiment confirms enabled GATT compilation and preprocessor1.
  The repository lab flag-order issue remains separately documented in
  [env_setup.md](env_setup.md); its attempted bundled input-pin update was
  rejected by automatic approval review without details and was removed.
- All reviewed build inputs and OTA validator bytes remain unchanged. Lab
  artifacts are not release/installation evidence. Hosted release compilation,
  exact installed version/boot health and actual manual/physical use remain
  independent gates. Do not use a live opening as an unattended regression.


## 2026-10-18 installed acceptance

[PR472](https://github.com/ks-house/smart-gatekeeper/pull/472) merged as
3edc4b42a9f288e8c26fed7c065431dd1f3c6018 after required checks passed.
[Release39111255559](https://github.com/ks-house/smart-gatekeeper/actions/runs/39111255559)
built exact-main with protected personal runtime inputs, joined the dedicated
private publisher network, atomically promoted signed/encrypted artifacts and
verified the exact pointer/content over HTTPS. Previous valid content was
retained. Public local build fixtures were not published.

One owner-authorized signed ota_check requested the repair update; its broker
and application acknowledgments were kept separate from install evidence.
Firmware2.1.552+main.g3edc4b4 subsequently reported a new boot and VALID image.
Three verified health samples showed IDLE/relay OFF, BLE ready, no OTA error,
and an empty/nonstalled access-evidence queue. Backend readiness passed12 checks.

The owner then confirmed actual manual door opening worked. One verified
ACCESS_SIGNED_MANUAL_COMPLETED / ACCESS_GRANTED / SUCCEEDED event corroborates
that use. This post-install event window contains no automatic ARM or
SESSION_SUPERSEDED: owner confirmation proves manual use, not a field exercise
of busy-ARM preemption. That case has isolated production-component coverage
and remains part of the broader physical acceptance gates.

Automatic sensor qualification/NO_ECHO/FAULT root cause remains unresolved;
no sensor threshold, GPIO or relay timing was changed. No unattended door
command or forced reboot was sent. Backup461 remains deferred, and the NAS
firewall stays at its original disabled baseline.
