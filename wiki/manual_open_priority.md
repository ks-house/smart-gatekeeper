# Manual MQTT priority during a local automatic sensor wait

Tracks [issue470](https://github.com/ks-house/smart-gatekeeper/issues/470).
Diagnosis: [access_incident_2026_10_18.md](access_incident_2026_10_18.md).
Stage: implementation and isolated validation; installation/field use are separate.

## Authority and transport

MqttIngressWorker leases the existing established PubSubClient/TLS socket,
excluding connect, status-write, normal receive and OTA owners. One receive pass
copies a bounded frame. Its callback cannot authorize, write replay state,
apply ACL/config, reboot, start OTA or operate the relay. Main keeps progressing
the sensor/FSM/relay timer during a blocked read or reply write. Watchdog, heap
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
