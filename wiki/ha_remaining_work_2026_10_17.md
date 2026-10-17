# HA and SmartBox remaining acceptance2026-10-17

## Scope and completion gates

Owner requests completion of the three remaining follow-ups after authenticated
broker cutover: Gatekeeper447 event JSON,441 HA recurrence evidence/alarms and
SmartBox7 deployed OTA diagnostic failure/recovery. Keep their operating gates
open until each is verified; source/CI, actual install and physical movement
are distinct.

##447 event discovery

Existing event discovery extracts event_type to a bare string, although the
publisher already emits a four-field privacy-safe JSON object. Remove the scalar
template so HA's default path parses the whole object; no event types, topics,
identity, attributes, QoS or private projection are changed.

Two regressions use actual signed terminal fixtures, the real parser/projector
and advertised discovery. The combined configuration/payload test fails on the
old template; success/termination across both signed paths retain the exact four
privacy fields. Malformed event metadata produces no outgoing projection.

Required operating acceptance: normal Backend rollout, read-only corrected
retained discovery, then natural nonretained event accepted by the HA entity.
No synthetic production access event or real actuator command.

Official [MQTT Event contract](https://www.home-assistant.io/integrations/event.mqtt/)
requires a JSON event object after any value-template transformation.

##441 recurrence and alert acceptance

Actual restart policy unless-stopped and HTTPS/WebSocket were already accepted.
Collect preserved stop metadata/logs before assigning a cause. If historical
evidence was not retained, record the evidence limit and install durable bounded
lifecycle/health observations rather than inventing a diagnosis. Verify HTTP and
TLS WebSocket checks and an existing owner-visible alarm route without a production
HA shutdown or NAS reboot.

## SmartBox7 diagnostic acceptance

Existing installed e0323a0 includes bounded phase/attempt/error fields. Derive a
bounded reversible failure test from the actual updater and protected OTA origin;
preserve TLS/authentication, current image, partitions and relay isolation.
Require deployed failure fields and subsequent successful no-update check.
Do not substitute unit tests alone for this device acceptance.

## Validation checkpoint

Backend427 tests pass with14 explicit opt-in skips; OTA contract suite78 passes.
The first local full run found only an unavailable Docker Desktop WSL stub.
Ubuntu CLI29.1.3 and Compose2.40.3 were extracted into private user storage from
SHA-verified distribution packages; session-only PATH and private client config
allow actual Linux Compose rendering without installing/starting a daemon or
changing Windows/global PATH. Full Backend run then passes.

Signed isolated callback job591d1063 uses installed HA2026.8.1/imageb80c4cee.
All four real Backend-projected payloads are accepted by HA's actual callback and
default value renderer. Six malformed cases cause no accepted event; HA's array
input raises ValueError (not a gracefully handled parse warning). Retained replay
is ignored; the original scalar template rejects all four valid payloads.
The helper runs in a separate Python process with temporary HomeAssistant state,
without starting it, MQTT subscription/publication or changing production state.

HA recorder evidence shows previous run9 closed_incorrect=1 and first recovery
run starts2026-10-16T02:49:24Z. NAS boot time2026-10-13T09:38:59Z excludes a NAS
reboot at that recovery, but does not identify the HA termination cause.
