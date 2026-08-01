# Cross-layer access/update event schema v1

> 상태: Wave 0 계약 확정
> 적용 대상: Android, ESP32-C6 Target, Backend, collector
> 추적: GitHub issue [#15](https://github.com/ks-house/smart-gatekeeper/issues/15), OTA P0 [#23](https://github.com/ks-house/smart-gatekeeper/issues/23)
> 실행 계약: [`observability/`](../observability/README.md)

## 1. 목적과 범위

한 번의 출입을 Android scan wake부터 GATT proof, Target ACL/ARMED, sensor, relay OFF까지
하나의 `session_id`로 추적한다. 같은 envelope를 mobile update와 Target OTA에도 사용해
artifact 확인부터 install, 새 boot/app first-run health, valid mark 또는 rollback까지 하나의
update session으로 판정한다.

이 문서는 schema와 합격 판정의 단일 진실 공급원이다. 런타임 emitter와 저장소 연결은
#17~#20의 구현 범위지만, 그 구현은 여기의 v1 fixture와 parser를 그대로 통과해야 한다.

## 2. 버전 계약과 파일

| 파일 | 역할 |
|---|---|
| [`event_schema_v1.json`](../observability/event_schema_v1.json) | envelope 구조, 타입, 허용 속성 |
| [`event_codes_v1.json`](../observability/event_codes_v1.json) | 고정 `event_code`와 허용 stage/outcome/reason 조합 |
| [`event_parser.py`](../observability/event_parser.py) | 검증, replay dedupe, partial order, I7/I9 합격 판정 |
| [`access_success_v1.jsonl`](../observability/fixtures/access_success_v1.jsonl) | 정상 local GATT 출입 timeline |
| [`manual_remote_access_success_v1.jsonl`](../observability/fixtures/manual_remote_access_success_v1.jsonl) | 인증된 모바일 앱 버튼 기반 수동 개방 timeline |
| [`target_ota_success_v1.jsonl`](../observability/fixtures/target_ota_success_v1.jsonl) | boot 전후 Target OTA timeline |

`schema_version`은 문자열 `1.0`이다. v1 producer는 v1 필드를 삭제하거나 의미를 바꾸지
않는다. 새 optional field와 code 추가는 catalog/fixture/test를 함께 갱신하고, breaking
change는 새 major schema로 낸다. Collector는 알 수 없는 major를 원문과 분리해 quarantine
하고 출입 또는 OTA 성공 판정에 사용하지 않는다. N/N-1 동안 consumer는 현재 major와
직전 major를 읽되 producer는 협의된 한 버전만 emit한다.

## 3. 공통 envelope

| 필드 | 규칙 |
|---|---|
| `event_id` | producer가 CSPRNG로 만든 lowercase UUIDv4. 동일 payload replay의 idempotency key |
| `session_id` | 출입 또는 update를 시작한 owner가 한 번 만든 lowercase UUIDv4 |
| `session_kind` | `access` 또는 `update`; 한 session에서 변경 금지 |
| `source_component` | `android`, `target`, `backend`, `collector` |
| `source_instance_id` | site-scoped HMAC 등 불투명 식별자. MAC, tenant/device 원문 금지 |
| `source_boot_id` | process/OS/MCU boot마다 새 값. sequence namespace |
| `sequence` | `(source_instance_id, source_boot_id)` 안에서 emit 직전에 증가하는 uint64 (`0..2^64-1`) |
| `attempt` | 같은 session의 transport/install 재시도 번호. 1부터 증가 |
| `event_code` | catalog에 등록된 고정 code |
| `stage` | catalog가 event별로 고정한 lifecycle stage |
| `outcome` | `STARTED/PROGRESS/SUCCEEDED/DENIED/FAILED/TIMED_OUT/CANCELLED` |
| `reason_code` | catalog가 event별로 허용한 고정 reason. 자유 텍스트 대체 금지 |
| `clock` | wall clock, monotonic clock, 동기화 품질 |
| `target` | HMAC 등 불투명 `target_ref`와 알려진 `boot_id`; Target emitter는 자기 boot와 일치 |
| `causation_event_id` | 직접 원인 event. 계층 간 강한 ordering edge |
| `attributes` | schema whitelist에 있는 비민감 scalar만 사용 |
| `update` | update session에서 필수인 component/version/digest/confirmation |

자유 텍스트 진단은 canonical event 밖의 별도 local debug sink에서만 허용한다. 운영 합격,
경보, 통계와 사용자 표시 문구 선택은 반드시 `event_code + reason_code`로 결정한다.

## 4. session, boot, sequence 규칙

### 4.1 Access session

1. OS wake/presence callback을 소유한 Android native worker가 `session_id`를 만든다.
2. 같은 physical presence의 중복 callback은 기존 active session으로 병합하고 새 ID를 만들지
   않는다. backoff 뒤 실제 새 인증 attempt만 같은 session의 `attempt`를 증가시킨다.
3. Android가 시작하지 않는 manual remote path는 Backend가, 완전 offline Target-local path는
   Target이 UUIDv4를 만든다.
4. GATT proof, MQTT legacy arm 등 모든 protocol request/response에 `session_id`를 전달한다.
5. 모든 session은 정확히 하나의 terminal event로 끝난다. 성공은
   `ACCESS_SESSION_COMPLETED/ACCESS_GRANTED`, 나머지는
   `ACCESS_SESSION_TERMINATED/<fixed reason>`이다.

UUIDv4는 wall clock에 의존하지 않으므로 RTC가 틀리거나 Target이 재부팅돼도 같은 ID가 다시
생성되지 않는다. MAC, timestamp, 증가 counter만 조합해 session ID를 만들면 안 된다.

### 4.2 Boot와 sequence

- `source_boot_id`는 producer process 또는 MCU boot마다 새로 만든다. Android service 재생성,
  Backend worker restart도 새 boot namespace다.
- Target의 현재 16자리 `DiagnosticsManager::bootId()`는 v1 `boot_id` 형식을 만족한다. 다만
  `target_id`는 eFuse MAC 원문이므로 collector에서 site-scoped HMAC `target_ref`로 바꾸고 원문을
  canonical event에 복사하지 않는다.
- `sequence`는 NVS에 매 event마다 쓰지 않고 boot-local RAM에서 증가한다. wrap 전에 새 boot
  namespace를 열며, queue flush/retry에서도 원래 값을 보존한다. 음수와 `2^64` 이상은 schema와
  parser가 모두 거부한다.
- `(source_instance_id, source_boot_id, sequence)`가 같은 두 event는 동일 `event_id`와 동일
  canonical payload여야 한다. 동일 event replay는 dedupe하고 다른 payload는 corruption으로
  거부한다.
- Target reset이 active access 중 발생하면 RTC/NVS breadcrumb의 prior session을 읽어 새 boot에서
  `ACCESS_SESSION_TERMINATED/RESET_DURING_SESSION`을 emit한다. `prior_target_boot_id`를 포함하고
  relay boot-default OFF를 먼저 보장한다. terminal의 직접 cause는 직전 Target event여야 하고,
  `prior_target_boot_id`는 그 event의 boot와 같아야 하며, terminal emitter는 같은 `target_ref`의
  새 boot여야 한다. reset 뒤 기존 session을 성공으로 이어 붙이지 않는다.

## 5. 시간과 offline ordering

`clock.wall_time`은 UTC RFC3339 `Z` 또는 `null`, `clock.monotonic_ms`는 boot-local uint64
(`0..2^64-1`)다.
SNTP/OS clock을 신뢰할 수 있을 때만 `quality=SYNCED`와 `uncertainty_ms`를 기록한다. Target처럼
wall clock을 초기화하지 않은 producer는 `UNSYNCED`와 `wall_time=null`을 사용한다.

정렬 우선순위는 다음과 같다.

1. 같은 producer boot: `sequence`
2. 다른 producer/boot: `causation_event_id` DAG edge
3. 둘 다 `SYNCED`: wall time과 uncertainty를 보조 표시
4. 위 정보가 없으면 동시/순서 미상으로 유지

MQTT reconnect, mobile upload, Backend ingest의 `received_at`은 보존·지연 측정용 metadata일 뿐
event time이 아니다. Offline queue는 event를 생성할 때 ID/boot/sequence/clock/cause를 확정하고
flush 중 바꾸지 않는다. at-least-once 전송은 `event_id`로 dedupe한다. Collector는 서로 다른
unsynced producer event에 임의의 total order를 부여하지 않는다. Reference parser의 `order`
명령은 causal DAG를 지키는 결정적 표시 순서를 만들지만, tie-break는 인과 의미가 아니다.
`validate_stream` 자체가 `causation_event_id`와 같은 producer boot의 sequence edge를 합친 graph의
cycle을 거부하므로, `order`를 호출하지 않는 ingest 경로도 순환 인과를 수용하지 않는다.

## 6. 고정 event/reason code

정확한 허용 조합은 [`event_codes_v1.json`](../observability/event_codes_v1.json)이 authoritative하다.
주요 terminal reason 분류는 다음과 같다.

| 구간 | 대표 reason |
|---|---|
| wake | `WAKE_OS_BLOCKED`, `PERMISSION_DENIED`, `BLUETOOTH_DISABLED`, `FORCE_STOPPED`, `BATTERY_RESTRICTED` |
| GATT | `GATT_CONNECT_FAILED`, `GATT_TIMEOUT`, `GATT_DISCONNECTED` |
| proof | `SIGNATURE_INVALID`, `PROOF_EXPIRED`, `NONCE_REPLAYED`, `MALFORMED_PROOF` |
| ACL | `ACL_NOT_FOUND`, `ACL_REVOKED`, `ACL_EXPIRED`, `ACL_STALE`, `CREDENTIAL_INACTIVE` |
| Target FSM | `TARGET_BUSY`, `TARGET_NOT_IDLE`, `OTA_BUSY`, `ARM_TIMEOUT`, `RESET_DURING_SESSION` |
| sensor/relay | `SENSOR_TIMEOUT`, `SENSOR_INVALID`, `SENSOR_IO_ERROR`, `RELAY_CONTROL_ERROR`, `RELAY_FAILSAFE_CUTOFF` |
| legacy Backend | `API_UNAUTHORIZED`, `BACKEND_UNAVAILABLE`, `MQTT_PUBLISH_FAILED`, `TARGET_OFFLINE` |
| OTA artifact | `MANIFEST_INVALID`, `ARTIFACT_HASH_MISMATCH`, `SIGNING_IDENTITY_MISMATCH`, `BOARD_MISMATCH` |
| OTA install/health | `INSTALL_FAILED`, `USER_DENIED_INSTALL`, `BOOT_HEALTH_TIMEOUT`, `BOOT_HEALTH_FAILED`, `ROLLBACK_FAILED` |

예외 문자열, HTTP body, crypto library 오류 문자열은 reason code가 아니다. 새 원인이 필요하면
기존 code에 억지로 넣지 말고 catalog, schema test, migration 문서를 같은 PR에서 추가한다.

## 7. 개인정보와 secret 정책

Canonical event에 기록하지 않는다.

- tenant 이름/ID/동호수/전화번호, BLE MAC, Android device ID, eFuse MAC 원문
- API key, password, bearer token, Wi-Fi/MQTT credential
- private key, shared secret, challenge nonce, proof/signature 원문
- MQTT raw payload, HTTP response body, stack trace의 request data
- query parameter가 붙은 artifact/download URL

허용하는 식별자는 목적·site별 key로 HMAC한 `source_instance_id`, `target_ref`,
`credential_ref`뿐이다. key rotation 시 cross-key lookup table은 제한된 Backend 보안 저장소에만
두고 event에는 넣지 않는다. OTA `artifact_sha256`은 artifact 상관관계와 무결성 증거이므로
허용하지만 URL, signature, signing private material은 금지한다. 운영 보존 기간과 접근 권한은
Backend 정책에서 정하되 삭제 후에도 집계 통계만 남긴다.

Update session에서 manifest 확인 전 `artifact_sha256`은 `null`일 수 있다. 최초 non-null digest가
확정되면 manifest, download, verified artifact, installed image, 새 boot/health, valid mark와 rollback
event는 모두 같은 값을 보존하며 terminal failure도 이미 알려진 digest를 지우지 않는다. 서로 다른
digest 또는 확정 뒤 누락은 artifact/install 상관관계 실패로 fail-closed 처리하고 OTA 성공·rollback
완료 판정에 사용하지 않는다.

Reference parser는 금지 field name, raw MAC/전화번호, PEM private key/Bearer token,
query-bearing URL을 fail-closed로 거부한다. 이는 완전한 DLP가 아니므로 producer whitelist도
반드시 적용한다.

## 8. Sample timeline

### 8.1 정상 local access

동일 `session_id`의 최소 합격 chain이다.

```text
ACCESS_SESSION_STARTED
→ ACCESS_WAKE_DETECTED
→ ACCESS_GATT_CONNECT_STARTED
→ ACCESS_GATT_CONNECTED
→ ACCESS_PROOF_REQUESTED
→ ACCESS_PROOF_VERIFIED
→ ACCESS_ACL_ACCEPTED
→ ACCESS_ARMED
→ ACCESS_SENSOR_DETECTED
→ ACCESS_RELAY_ON
→ ACCESS_RELAY_OFF
→ ACCESS_SESSION_COMPLETED / ACCESS_GRANTED
```

실제 Android synced clock과 Target unsynced monotonic clock이 섞인 예시는
[`access_success_v1.jsonl`](../observability/fixtures/access_success_v1.jsonl)에 있다.

### 8.2 인증된 모바일 앱 수동 개방

Epic #13의 사용자 확인 불변조건에 따라 앱의 명시적 `문 열기` 버튼 경로는 hands-free
`local_gatt`/`legacy_mqtt`와 별도의 `manual_remote` session으로 유지한다. 최소 합격 chain은
다음과 같고, 이 path에는 wake/GATT/arm/sensor 기반 hands-free activation event를 섞지 않는다.

```text
ACCESS_SESSION_STARTED                         (path=manual_remote)
→ ACCESS_MANUAL_OPEN_REQUESTED                 (MANUAL_BUTTON_PRESSED)
→ ACCESS_MANUAL_OPEN_AUTHORIZED                (MANUAL_OPEN_AUTHORIZED)
→ ACCESS_MANUAL_OPEN_RECEIVED                  (MANUAL_OPEN_RECEIVED)
→ ACCESS_RELAY_ON
→ ACCESS_RELAY_OFF
→ ACCESS_SESSION_COMPLETED / ACCESS_GRANTED
```

요청 event는 인증된 모바일 앱의 명시적 버튼 동작을, authorized event는 Backend의 현재
credential 승인 확인을, received event는 Target의 수동 command 수신을 각각 증명한다. 정상
예시는 [`manual_remote_access_success_v1.jsonl`](../observability/fixtures/manual_remote_access_success_v1.jsonl)에
있다.

### 8.3 Target OTA

같은 update `session_id`가 old boot에서 new boot로 이어진다.

```text
UPDATE_SESSION_STARTED
→ UPDATE_MANIFEST_CHECK_STARTED
→ UPDATE_MANIFEST_VERIFIED
→ UPDATE_DOWNLOAD_STARTED/PROGRESS
→ UPDATE_ARTIFACT_VERIFIED
→ UPDATE_INSTALL_STARTED/INSTALLED
→ UPDATE_REBOOT_REQUESTED              (old boot_id)
→ UPDATE_BOOT_CONFIRMED                (new boot_id, expected version)
→ UPDATE_HEALTH_CONFIRMED
→ UPDATE_MARKED_VALID
→ UPDATE_SESSION_COMPLETED / UPDATE_HEALTH_CONFIRMED
```

`artifact_sha256`, `current_version`, `target_version`, `attempt`, confirmation을 매 event에
보존한다. upload, MQTT PUBACK, download 100%, flash 완료만으로 terminal success를 만들지 않는다.
예시는 [`target_ota_success_v1.jsonl`](../observability/fixtures/target_ota_success_v1.jsonl)에 있다.

### 8.4 Target OTA rollback

Rollback 완료는 trigger/confirm 두 event만으로 성립하지 않는다. 최초 session event의
`current_version`을 이전 정상 버전으로 고정하고 다음 causal chain 전체를 요구한다.

```text
UPDATE_SESSION_STARTED                       (previous version recorded)
→ UPDATE_ROLLBACK_STARTED                    (failed candidate boot/version)
→ UPDATE_ROLLBACK_PREVIOUS_INSTALL_CONFIRMED (previous version, INSTALLED)
→ UPDATE_ROLLBACK_PREVIOUS_BOOT_CONFIRMED    (new recovery boot, BOOTED)
→ UPDATE_ROLLBACK_PREVIOUS_HEALTH_CONFIRMED  (same recovery boot, HEALTH_CONFIRMED)
→ UPDATE_ROLLBACK_CONFIRMED                  (same recovery boot, ROLLED_BACK)
→ UPDATE_SESSION_COMPLETED / ROLLBACK_COMPLETED
```

Target evidence는 모두 같은 `target_ref`와 하나의 새 recovery boot에서 emit되고, 각 event의
`current_version`은 기록된 이전 버전과 일치해야 한다. `artifact_sha256`은 실패 candidate와의
상관관계를 잃지 않도록 session 전체에서 그대로 보존한다. 정상 예시는
[`target_ota_rollback_success_v1.jsonl`](../observability/fixtures/target_ota_rollback_success_v1.jsonl)에
있다.

## 9. 기존 코드와 migration mapping

| 현재 신호 | v1 mapping | 전환 시 주의 |
|---|---|---|
| Android Target packet/RSSI eligible | `ACCESS_SESSION_STARTED`, `ACCESS_WAKE_DETECTED` | RSSI는 기본 event에 저장하지 않고 필요 시 별도 제한 telemetry 사용 |
| Android `/door/prearm` POST | `ACCESS_BACKEND_REQUESTED/AUTHORIZATION_REQUESTED` | request에 `session_id`, `event_id` 전달 |
| Android HTTP 401 | `ACCESS_BACKEND_REJECTED/API_UNAUTHORIZED` 후 terminal | response body/공통 API key 기록 금지 |
| Android HTTP 403 | `ACCESS_BACKEND_REJECTED/CREDENTIAL_INACTIVE` 후 terminal | tenant 이름/동호수 기록 금지 |
| Android timeout/통신 오류 | terminal `BACKEND_UNAVAILABLE` | exception, URL query 원문 금지 |
| 모바일 앱 `문 열기` 버튼 | `ACCESS_MANUAL_OPEN_REQUESTED/MANUAL_BUTTON_PRESSED` | hands-free wake/pre-arm과 별도 `manual_remote` session 생성 |
| Backend `/door/open` 승인 | `ACCESS_MANUAL_OPEN_AUTHORIZED/MANUAL_OPEN_AUTHORIZED` | 등록·활성 credential 확인 후에만 emit; 사용자 원문 금지 |
| Target `force_open` 수신 | `ACCESS_MANUAL_OPEN_RECEIVED/MANUAL_OPEN_RECEIVED` | 이어지는 relay ON/OFF와 같은 session/cause chain 유지 |
| Backend `[PREARM]` 요청 | Android event의 cause를 가진 `ACCESS_BACKEND_REQUESTED` | 현재 UUID/device/RSSI/name 로그는 privacy 위반이므로 제거/HMAC 전환 |
| Backend 등록·승인 확인 | `ACCESS_BACKEND_AUTHORIZED/BACKEND_ALLOW` | tenant row 원문 대신 `credential_ref` |
| Backend MQTT publish 성공/실패 | `ACCESS_ARM_PUBLISHED/MQTT_ARM_PUBLISHED` 또는 `ACCESS_ARM_DELIVERY_FAILED/MQTT_PUBLISH_FAILED` | MQTT arm payload에 `session_id` 전달, raw payload 로그 금지 |
| DB `access_logs.is_success/failure_reason` | terminal `outcome/reason_code`에서 projection | expand 단계에서 schema/event/session/code column 또는 append-only event table 추가; 기존 자유 텍스트를 새 code로 추측 변환하지 않음 |
| Target `mqtt_arm`, `pre_armed` | `ACCESS_ARM_RECEIVED/ARM_RECEIVED`, `ACCESS_ARMED/ARM_ACCEPTED` | 현재 payload의 사용자 이름 제거 |
| Target `arm_rejected`, `arm_rejected_not_idle` | `ACCESS_ARM_REJECTED/TARGET_NOT_IDLE` 후 terminal | busy와 OTA busy는 별도 reason |
| Target `arm_expired` | `ACCESS_SENSOR_FAILED/SENSOR_TIMEOUT` 후 terminal `ARM_TIMEOUT` | terminal 누락 금지 |
| Target `door_open` | `ACCESS_SENSOR_DETECTED`, 이어서 `ACCESS_RELAY_ON` | 하나의 자유 텍스트 event를 두 물리 단계로 분리 |
| Target `door_close` timer/FSM | `ACCESS_RELAY_OFF/RELAY_HOLD_COMPLETE` 또는 `RELAY_FAILSAFE_CUTOFF` | 이어서 session terminal emit |
| Target retained `[DIAG] boot_id` | `source_boot_id`와 `target.boot_id` | eFuse `target_id`는 HMAC `target_ref`로 전환 |
| Target `time=millis()` | `clock.monotonic_ms`, `UNSYNCED`, wall time null | collector 수신 시각으로 덮어쓰지 않음 |
| MQTT `smart-gatekeeper/event {event,detail,time,...}` | v1 envelope를 새 versioned topic 또는 content type으로 publish | `detail`은 canonical 판정에서 제거하고 event/reason code로 대체; dual-write 기간 뒤 legacy topic retire |
| Target `ota_check/download/failed` | `UPDATE_*` event와 고정 OTA reason | firmware URL/version.json 원문 로그 제거 |
| Mobile UpdateChecker check/download/OpenFilex | manifest/download/install-start event | installer 호출은 install 성공이 아님; 새 app first-run health가 terminal success |

전환은 dual-write로 시작한다. v1 event를 먼저 저장한 뒤 기존 text/MQTT event를 임시로
병행하고 parser 검증률과 미분류율을 관측한다. I7/I9가 v1을 합격 근거로 사용한 뒤에만 legacy
free-text 판정을 제거한다. Schema migration은 Backend DB의 expand→migrate→contract 순서를
따르며 N/N-1 consumer 기간을 둔다.

## 10. I7/I9 합격 판정

### I7 Target local auth/FSM

- 성공 local session은 §8.1 필수 chain을 같은 `session_id`와 causal order로 가진다.
- session당 `ACCESS_RELAY_ON`은 최대 1회이며 정확히 한 `ACCESS_RELAY_OFF`가 대응한다.
- 거부/timeout/reset은 정확히 한 terminal event와 catalog의 고정 reason을 가진다.
- Target boot가 바뀐 access는 성공 처리하지 않고 새 boot에서
  `RESET_DURING_SESSION + prior_target_boot_id`로 종료한다. terminal은 직전 Target event를 직접
  가리키며 그 event의 boot를 prior 값으로 기록하고 같은 Target의 새 boot가 emit한다.
- Backend/MQTT offline queue를 재전송해도 event ID, boot, sequence, cause가 변하지 않는다.
- proof/ACL 실패 session에 relay event가 존재하면 즉시 불합격이다.
- 인증된 모바일 앱의 explicit button-driven `manual_remote` path는 manual request→Backend
  authorization→Target command receipt→relay ON/OFF chain을 요구하고 hands-free wake/GATT/arm/sensor
  event와 혼합되면 불합격이다.

### I9 E2E/fault injection

- 각 matrix case는 기대 terminal `event_code/reason_code`를 test assertion으로 명시한다.
- 유효 credential 100회는 서로 다른 session ID, terminal success 100개, relay ON/OFF 1:1이어야
  한다. event 누락이나 unknown reason은 성공률 분모에서 제외하지 않고 실패로 센다.
- latency는 causal stage pair의 같은 synced clock 또는 같은 producer monotonic clock에서만
  계산한다. unsynced cross-device wall time을 빼지 않는다.
- duplicate delivery는 dedupe한 뒤 계산하고 sequence conflict는 데이터 corruption으로 실패한다.
- 모든 거부/fault가 fixed reason으로 분류되지 않으면 rollout/legacy retirement를 막는다.

### OTA #23 release gate

- Target success는 verified artifact→inactive install→planned reboot→new boot/version→health→valid
  mark 전체가 같은 update session에 있어야 한다.
- Mobile success는 verified APK→package install→new app first-run health가 같은 session에 있어야
  한다. installer UI 호출만으로 성공하지 않는다.
- rollback success는 `UPDATE_ROLLBACK_STARTED`, 이전 버전 install→boot→health의 개별 확인,
  `UPDATE_ROLLBACK_CONFIRMED`, terminal `ROLLBACK_COMPLETED`를 하나의 causal chain으로 요구한다.
- Update session에서 최초로 확정된 `artifact_sha256`은 immutable하다. manifest와 installed image,
  boot/health 또는 failure terminal의 digest가 다르거나 사라지면 fail-closed한다.
- 각 retry는 `attempt`를 증가시키며 target version과 artifact digest를 검증한다. 새 release를
  시도하면 새 session을 만든다.
- OTA secret/private material은 어느 event에도 남지 않는다.

## 11. Reference parser 사용

Repository root에서 실행한다.

```powershell
python observability/event_parser.py validate observability/fixtures/access_success_v1.jsonl observability/fixtures/manual_remote_access_success_v1.jsonl observability/fixtures/target_ota_success_v1.jsonl observability/fixtures/target_ota_rollback_success_v1.jsonl
python observability/event_parser.py evaluate observability/fixtures/access_success_v1.jsonl observability/fixtures/manual_remote_access_success_v1.jsonl observability/fixtures/target_ota_success_v1.jsonl observability/fixtures/target_ota_rollback_success_v1.jsonl
python -m unittest discover -s observability/tests -v
```

테스트는 정상 hands-free/manual access와 OTA, offline 역순 도착, exact replay dedupe, sequence conflict, unknown code,
privacy 위반, boot 변경, terminal 누락, health confirmation 누락과 함께 digest 불일치, rollback 증거
누락, 잘못된 reset prior/new boot 관계, uint64 overflow, causation cycle의 negative fixture를 검증한다.

## 12. OTA 영향 판정

이 Wave 0 변경은 runtime firmware/mobile/backend, partition, update trigger, artifact 또는 credential
storage를 수정하지 않는다. 따라서 현재 mobile/Target OTA reachability와 rollback 상태를
약화하지 않는다. 대신 이후 구현이 install/boot/health/rollback 완료를 잘못 성공 처리하지
않도록 고정 schema와 executable gate를 추가한다. 실제 periodic HTTPS, local AP recovery,
Target health valid mark, mobile artifact 검증의 구현과 실기기 fault injection은 #23 범위로 남는다.
