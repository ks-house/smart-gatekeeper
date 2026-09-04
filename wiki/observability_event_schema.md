# Cross-layer access/update event schema v1

> 상태: Wave 0 계약 확정 + 인증된 access evidence 1.1 source candidate
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
5. 모든 session은 정확히 하나의 terminal event로 끝난다. Local GATT 성공/종료는
   `ACCESS_SESSION_COMPLETED|TERMINATED`, signed MQTT arm/manual은 MAC 입력에 경로까지
   결합하기 위해 `ACCESS_SIGNED_ARM_*` 또는 `ACCESS_SIGNED_MANUAL_*`를 사용한다. 성공
   reason은 `ACCESS_GRANTED`, 종료 reason은 catalog의 fixed code만 허용한다.

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
| Target FSM | `TARGET_BUSY`, `TARGET_NOT_IDLE`, `OTA_BUSY`, `ARM_TIMEOUT`, `SESSION_SUPERSEDED`, `RESET_DURING_SESSION` |
| sensor/relay | `SENSOR_TIMEOUT`, `SENSOR_INVALID`, `SENSOR_IO_ERROR`, `RELAY_CONTROL_ERROR`, `RELAY_FAILSAFE_CUTOFF` |
| legacy Backend | `API_UNAUTHORIZED`, `BACKEND_UNAVAILABLE`, `MQTT_PUBLISH_FAILED`, `TARGET_OFFLINE` |
| OTA artifact | `MANIFEST_INVALID`, `ARTIFACT_HASH_MISMATCH`, `SIGNING_IDENTITY_MISMATCH`, `BOARD_MISMATCH` |
| OTA install/health | `INSTALL_FAILED`, `USER_DENIED_INSTALL`, `BOOT_HEALTH_TIMEOUT`, `BOOT_HEALTH_FAILED`, `ROLLBACK_FAILED` |

`SESSION_SUPERSEDED`는 구형/N-1 Target이 이미 발행한 event를 Backend가 계속 해석하기
위한 `ACCESS_SESSION_TERMINATED/FAILED` 호환 reason으로만 남긴다. 현재 Target은 미인증
`ClientHello`로 verified `ARMED` session을 교체하거나 이 reason을 발행하지 않는다.
`SUCCEEDED` 조합이나 sensor/relay 완료로 승격할 수 없고, 역사 event는 관리자에
교체 종료로 표시한다.

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

## 13. Backend 수신 이력과 관리자 판정

Schema 011부터 Backend는 기존 `access_logs.is_success`와 Target이 발행하는 canonical access
event를 분리해 보존한다. Additive schema 012는 같은 history에 actor/integrity 필드와 signed status
high-water/terminal summary를 더한다. 기존 테이블은 모바일 원격 요청 등 과거 projection을 유지하고,
`access_event_history`는 다음 Target 단계를 append-only row로 저장한다.

- BLE GATT 연결과 proof 검증/거부
- ACL 거부, `ARMED` 진입, 초음파 threshold 감지
- relay ON/OFF와 failsafe 차단
- session 정상 완료 또는 고정 reason code의 종료

수집기는 configured Target의 정확한
`gatekeeper/v1/targets/<target_id>/canonical-event` topic만 읽는다. retained message, 8 KiB 초과,
중복 JSON key, catalog 밖 event/stage/outcome/reason 조합, 잘못된 UUID/boot/sequence/attribute는
저장하지 않는다. MQTT callback은 bounded queue에만 넣고 DB I/O는 별도 worker에서 수행한다.
`event_id` 및 configured stable Target ID + boot + sequence를 함께 unique 처리하며, 완전히 같은
replay만 idempotent하게 인정하고 충돌은 generic warning으로 남긴다. Stable Target ID는 DB의
security correlation에만 쓰고 API에서는 제거하며, 별도 HMAC collector/session ref만 표시한다.
BLE 주소, raw credential/proof와 주민 이름은 immutable evidence table에 저장하지 않는다.

관리자 화면의 판정 경계는 다음과 같다.

| 화면 이벤트 | 확인 가능한 사실 | 확인할 수 없는 사실 |
|---|---|---|
| `ACCESS_PROOF_VERIFIED` | Target에서 active ACL·credential·permission과 서명 proof 검증이 모두 성공함 | 아직 `ARMED`, sensor, relay 성공은 아님 |
| `ACCESS_ACL_REJECTED` / proof reject | 표시된 고정 reason으로 인증·권한 단계가 거부됨 | 이벤트가 없다는 사실만으로 동일 실패를 추론할 수 없음 |
| `ACCESS_ARMED` | Target FSM이 sensor 감지 대기에 진입함 | 사람이 감지됐거나 문이 열렸다는 뜻은 아님 |
| `ACCESS_SENSOR_DETECTED` | Target threshold 조건이 충족됨 | 현재 펌웨어 payload에는 실제 거리 값이 없어 화면은 `-`일 수 있음 |
| `ACCESS_RELAY_ON/OFF` | Target software가 relay GPIO 동작 단계를 수행함 | 도어 접점·문짝의 물리 개방 확인은 아님 |
| `ACCESS_SESSION_COMPLETED` | Target software access chain이 정상 종료됨 | 별도 door contact가 없는 현재 배선에서 물리 개방 성공은 아님 |
| `ACCESS_SIGNED_ARM_COMPLETED/TERMINATED` | signed MQTT 출입 준비 세션의 Target terminal이 영속 큐와 Backend DB에 도달함 | 문짝 이동과 MQTT 요청자의 실명은 이 이벤트만으로 확인하지 않음 |
| `ACCESS_SIGNED_MANUAL_COMPLETED/TERMINATED` | signed MQTT 수동 개방 세션의 relay lifecycle terminal이 영속 큐와 Backend DB에 도달함 | 별도 door contact가 없어 물리 문짝 이동은 확인하지 않음 |
| legacy `MOBILE_REMOTE` success | Backend가 signed MQTT 전송을 접수함 | Target 수신·relay·물리 개방 성공은 아님 |

Target canonical topic은 현재 QoS 0이며 offline queue도 bounded이므로 이 화면은 **수신 이벤트
타임라인**이다. 이벤트가 빠졌을 때 성공 또는 실패를 확정하지 않는다. Target은 현재
`distance_mm`를 canonical attributes에 넣지 않고 명시적인 sensor I/O failure event도 발행하지
않는다. 다만 `ARMED` 뒤 `ACCESS_SESSION_TERMINATED/ARM_TIMEOUT`이 수신되면 그 세션에서 제한
시간 내 sensor threshold가 충족되지 않았다는 것은 확인할 수 있다. 거리 원문과 sensor fault를
추가하려면 Target schema, 개인정보·크기 제한, OTA 비회귀를 별도 변경으로 검토한다.

Backend readiness의 `access_event_collector`는 모든 configured canonical event와 authenticated
status topic의 MQTT SUBACK이 허용됐고 두 writer가 유효하며 마지막 저장 시도가 실패 상태가 아님을
뜻한다. 구독 거부, disconnect, queue overflow 또는 저장 실패는 `/ready`를 503으로 만든다. 이것도
실제 access event나 물리 문 개방을 만들었다는 뜻은 아니므로 배포 acceptance에서는 별도의 live
signed ingest를 확인한다. 명시적 `ACCESS_SIGNED_STATUS_READINESS_REQUIRED=true` cutover 뒤에는
authenticated status collector가 현재 MQTT 연결에서 HMAC 검증과 DB 저장을 통과한 Target status를
최소 한 건 받기 전까지 준비되지 않는다. 이전 연결에서 늦게 끝난 저장 결과는 새 연결의 증거가 될 수
없고, 잘못된 MAC 하나는 writer health를 오염시키지 않지만 유효 status가 계속 없으면 `/ready`는
503을 유지한다. Cutover 전 기본 `false`는 Backend N / Target N-1 독립 배포·rollback을 위해 SUBACK와
writer health만 요구한다. 이 Gate는 Target build key와 NAS keyring 불일치를 cutover 이후 구독 성공으로
오판하지 않기 위한 것이며 HA projection broker ACL의 실제 publish/readback은 별도다.
DB의 `received_at`은 UTC로 저장·`Z`가 붙은 ISO-8601로 반환하고, 관리자
“오늘” 집계는 KST(UTC+09:00) 경계에서 trusted rows와 legacy unsigned rows를 분리한다.

## 14. 인증된 access actor와 terminal 상태 projection

이 절의 Target MQTT `schema_version=1.1`은 §2의 portable observability schema `1.0`을
재정의하는 새 major가 아니다. 기존 event 필드를 유지하면서 운영 수신 경로에 아래 인증 필드를
추가한 source candidate다.

- Target은 Local GATT proof가 성공한 뒤에만
  `HMAC(key, door_id || session_id || credential_id)`의 domain-separated 96-bit digest를
  `c_<key-id>_<digest>` 형식의 `credential_ref`로 만든다. 원본 credential ID, 이름, 호수,
  proof와 shared key는 MQTT 또는 immutable history에 기록하지 않는다.
- 각 event는 topic Target ID, door, boot ID/count, event/session/sequence, code/stage/outcome/reason,
  monotonic time, optional actor ref와 허용 attribute를 포함하는 고정 binary canonical input의
  HMAC tag를 `auth`에 싣는다. Backend는 configured exact Target topic과 key ID를 함께 검증하고
  `integrity_status=verified`만 신규 신뢰 이력으로 저장한다. 구형 unsigned `1.0` row는 과거
  표시용으로만 분리하며 신규 live 신뢰 이력이나 readiness 근거로 승격하지 않는다.
- 관리자 read-side는 stable Target ID로 정확한 door를 찾은 뒤 현재 credential 후보를 다시
  HMAC해 **유일하게 한 건이 일치할 때만** 이름·호수를 표시한다. 계정 삭제, key 미보유,
  door 불일치, 0건/복수 일치는 모두 `확인 불가`로 남고 시각 근접성으로 사용자를 추측하지 않는다.
  DB/API는 raw `session_id` 대신 별도 opaque `session_ref`를 반환한다.

Target 주기 `/status`도 event와 다른 domain의 HMAC으로 보호한다. 인증 입력은 stable Target/door,
boot ID/count, 단조 증가 `access_status_revision`, FSM state, relay command/pin과 최신 terminal
session/sequence/code/reason/actor ref/phase mask를 포함한다. Backend는 stable Target ID별 DB
high-water를 원자적으로 전진시키며 stale boot, revision 역행, 동일 revision의 다른 payload를
거부한다. 정확한 replay는 파생 boot row를 복구할 수 있지만 live freshness를 갱신하지 않는다.

Target의 GATT protocol event와 proof 이후 local lifecycle event는 같은 boot-local global sequence
high-water를 공유하고 ProtocolCore/NimBLE와 loopTask lifecycle 접근은 같은 recursive task mutex로
직렬화한다. 다른 미인증 session이 끼어들면 global source position은 전진하지만, 현재
검증된 session의 causal parent는 그 session의 마지막 event로 별도 유지한다. 따라서 interleaved
connect/reject가 기존 session의 sequence를 중복시키거나 causal parent가 될 수 없다. Terminal phase
accumulator도 `ACCESS_PROOF_VERIFIED`에서만 시작·교체되고, 정확히 같은 session의 terminal만 최신
status summary를 갱신한다. Verified A가 `ARMED`이면 B의 `ClientHello`는 proof/challenge 전에
busy로 끝나며, B의 actorless connect/reject/terminal이 A의 actor, phase accumulator, deadline,
causal parent를 바꾸거나 A의 terminal status summary를 덮을 수 없다. B event가 global sequence
high-water를 올리더라도 A의 다음 lifecycle event는 고유한 새 source position과 A의 직전
causal sequence를 유지한다.

Protocol session이 시작되기 전 raw BLE link는 canonical `session_id`가 없다. 이 상태의 단순
disconnect, malformed frame 또는 queue overflow는 transport 결과로만 닫고 zero-session
`ACCESS_*` event/terminal을 만들지 않는다. 그렇지 않으면 표현 불가능한 record가 FIFO head를
막고 뒤의 verified evidence까지 정지시킬 수 있다. 반대로 authenticated action이 이미 commit된
`Completed` session의 duplicate/trailing frame은 `EXPIRED_OR_REPLAY` transport 결과만 반환하며,
동일 action을 다시 실행하거나 실패 terminal을 합성하거나 physical lifecycle actor를 지우지 않는다.

Terminal phase bit는 다음처럼 고정한다.

| Bit | 확인된 Target software 단계 |
|---|---|
| `0x01` | credential proof verified |
| `0x02` | FSM `ARMED` |
| `0x04` | ultrasonic threshold detected |
| `0x08` | relay command ON |
| `0x10` | relay command OFF |
| `0x20` | relay failsafe path observed |

정상 esp-timer cutoff와 `TargetAccessFsm::tick()`의 1초 hold 완료는 모두 routine
`RELAY_HOLD_COMPLETE`로 끝난다. 이 둘이 실행되지 못하고 별도 elapsed guard가 hold+grace를 넘긴
경우만 late failsafe다. 그 경로는 signed relay-OFF에 `RELAY_FAILSAFE_CUTOFF`, terminal에
`ACCESS_SESSION_TERMINATED/FAILED/RELAY_CONTROL_ERROR`, phase summary에 bit `0x20`을 남긴다.

완료 성공 profile은 경로별 exact mask로 고정한다: Local GATT sensor `0x1f`, Local GATT manual
`0x19`, signed MQTT arm+sensor `0x1e`, signed MQTT `manual_remote` `0x18`. 이 네 값이 아니거나
`0x20`이 있으면 `ACCESS_SESSION_COMPLETED` 문자열만으로 성공으로 집계하지 않는다. Individual QoS 0 event가 유실됐더라도 같은 boot의 서명된 terminal
요약은 별도 immutable summary로 보존할 수 있다. 최신 terminal status 요약은 여전히
**동일 boot RAM best-effort**지만, canonical terminal은 callback이 성공을 반환하기 전에 restart-safe
ordered checkpoint를 통과한다. 먼저 이전 volatile FIFO를 oldest-first로 기존 NVS queue 뒤에 append하고,
그 다음 terminal을 NVS에 기록한다. NVS가 terminal까지 수용하지 못하면 terminal을 reserved RAM tail에
붙인 뒤 그 terminal을 포함한 남은 FIFO 전체를 checksum-bound generation의 RTC_NOINIT A/B journal에
저장한 경우에만 terminal을 수락한다. Inactive slot에 records/checksum을 쓴 뒤 magic을 마지막으로
commit하므로 replacement 도중 reset되면 이전 valid generation이 복원된다. 따라서 MQTT socket I/O를
control path에 넣지 않으면서 software reset 뒤에도 원래 boot/count/sequence의 terminal 재수집을
시도한다. RTC journal은 cold power loss 내구성이 아니며 queue가
포화되면 기존 `queue_overflow` gap 정책이 손실 범위를 명시하므로, 무한 단절을 무손실이라고 주장하지 않는다.
어느 경우에도 software terminal은 physical door 이동을 추정하는 근거가 아니다.

Schema 013에서 Backend canonical worker는 HMAC 검증된 access-history 행과 HA projection outbox 행을
한 DB transaction으로 commit한다. 별도 HA outbox worker가 commit된 oldest row만
`event.smart_gatekeeper_01_access_terminal_event` 입력 topic으로 QoS 1/non-retained 발행하고 broker
local publish completion과 Backend 자신의 exact non-retained `(topic, payload)` broker-routed echo를 모두
확인한 뒤에만 `published_at`을 기록한다. Paho 1.6.1이 negative PUBACK reason을 충분히 노출하지 않는
한계를 broker route receipt와 Backend read ACL로 보완한다. Retained echo, 다른 topic 또는 단 한 byte라도
다른 payload는 완료 증거가 아니다. API/broker가 중간에 재시작되거나 receipt가 없으면 미완료 row를 같은
event marker로 재시도한다. 따라서 DB commit 뒤 HA route 전 crash의 영구 누락은 막지만, route receipt 뒤
DB mark 전 crash에는 동일 marker의 중복 전달이 가능한 **at-least-once** 계약이다. 동일 canonical event
replay는 outbox identity를 재사용하며 새 pending row를 만들지 않는다.
Worker는 성공한 CONNACK뿐 아니라 자신의 exact receipt topic SUBACK까지 받은 세대에서만 publish한다.
SUBACK 거부/로컬 subscribe 실패는 1초에서 30초까지 제한된 backoff로 같은 연결에 재구독하고, Paho
`QUEUE_SIZE`는 연결 손실로 오인하지 않고 같은 세대에서 backoff 재시도한다. `NO_CONN`은 새 CONNACK까지
발행을 막으므로 장기 단절 중 같은 row가 Paho offline queue에 반복 누적되지 않는다.

여기서 `published_at`은 이름과 달리 **Backend publish + broker self-route 완료**까지만 뜻한다. Home
Assistant consumer가 그 순간 연결·구독·허가되어 Recorder에 기록했다는 acknowledgement는 MQTT event
entity에 없으므로 HA Activity 자체는 여전히 consumer 관점 best-effort다. 대신 기존 `[Gatekeeper] 최근
출입 결과` sensor의 privacy-safe verified-status를 retained state로 유지해 HA 재접속 뒤 최신 marker는
복구한다. Activity event 자체는 과거 event 재발화를 막기 위해 non-retained다. 현재 discovery/device
identity는 personal-production `COMMAND_TARGET_ID` 하나만 소유하므로 ACL에 등록된 보조 Target event는
HA outbox에 넣지 않는다. 다중 Target/다중 Backend replica는 별도 device identity와 leader/row-claim
계약 전까지 지원하지 않는다.

Backend 모바일 projection도 signed terminal phase에 `0x20`이 하나라도 있으면 다른 정상 phase bit와
관계없이 `complete`가 아닌 실패 `terminated`로 분류한다. 이 실패 terminal 자체만으로 다음 인증을
허용하지 않으며, 동일 actor/session/boot의 fresh signed `IDLE`, relay command OFF와 configured OFF
pin level까지 확인된 뒤에만 `next_auth_ready=true`를 반환한다. 관리자 terminal summary도 같은
failsafe 비트를 성공에서 제외한다.

모바일은 native action-1 `SUCCEEDED`가 반환한 정확한 lowercase UUIDv4 Target session에 대해서만
AndroidKeyStore credential로 고정 80-byte `SGKASR01` read proof를 서명한다. Backend는 active
credential과 exact door grant를 확인한 뒤 그 session과 actor ref가 일치하는 서명 event/status만
반환한다. 전역 Target 상태를 다른 session에 결합하지 않는다. 앱은 4초 간격, 최대 120초의 bounded
one-shot polling으로 `armed → relay_active → cooldown → complete/terminated`를 표시한다.
`다음 인증 가능`은 동일 actor/session/boot의 terminal, fresh `IDLE`, relay command OFF와 configured
OFF pin level이 모두 확인된 경우에만 참이다. 이 표시는 scanner를 자동 재시작하거나 새 인증을
자동 발행하지 않는다. 각 poll의 새 proof nonce는 서명 검증 직후 durable
`mobile_credential_control_nonces` ledger에 `access_session_read_v1`으로 소비되므로 동일 proof replay는
거부된다.

이 단계 목록은 실시간 delivery 계약이 아니다. Target는 access-critical 동안 모든 MQTT/TLS를
보류한다. IDLE 뒤에는 모바일 exact-session poll이 audit backlog에 막히지 않도록 최신 signed
terminal/IDLE status를 먼저 시도하고 boot/config snapshot을 처리한다. 그 뒤 audit write는 update당
총 한 record로 제한한다. Durable NVS FIFO가 있으면 그 front 한 건을 처리하고 즉시 반환하며, NVS가
비었을 때만 volatile FIFO front 한 건을 처리한다. 따라서 앱은 중간
`sensor_detected`/`relay_active`/`cooldown`을 관찰할 수도 있지만, 4초 polling 경계에서는 `armed`에서
곧바로 최종 `complete`로 건너뛸 수 있다. 보장되는 사용자 의미는 exact-session terminal과 fresh
IDLE을 함께 확인한 뒤의 `다음 인증 가능`이다.

Target의 일반 event producer는 access-critical callback/FSM에서 TLS를 호출하지 않고 bounded outbox에
복사한다. Signed MQTT terminal도 위 ordered NVS/RTC checkpoint만 수행하며 MQTT socket은 호출하지 않는다.
DNS는 generation-bound callback으로 loop task가 관리하고, TCP/TLS/MQTT handshake는 secure client와
PubSubClient를 단독 소유하는 bounded worker 하나만 실행한다. Loop task는 worker 종료 전 그 객체를
읽거나 쓰지 않고 request ID와 Wi-Fi link generation이 모두 현재인 결과만 채택한다. Access 진입이나
link 변경이 요청한 취소 뒤 늦게 끝난 결과는 stale로 닫고, worker와 loop의 45초 WDT는 hard stall을
fail-closed한다. OTA도 이 worker가 끝나기 전에는 별도 TLS를 시작하지 않는다. Backend에서도 Paho callback은
bounded queue만 채우고 event/status DB I/O와 HA outbox delivery는 worker가 수행한다. Target publisher의
QoS 0 전달 한계, 유한 NVS/RAM queue overflow 가능성과 broker principal
인증은 별개다. 따라서 production에서는 Target/Backend/Home Assistant principal의 exact topic ACL을
설치하고 anonymous/cross-principal publish·subscribe 거부를 확인해야 한다.

미인증 GATT ingress는 최대 10초만 access-critical gate를 소유한다. 그 시간을 넘으면 transport를
disconnect하고 unverified state를 IDLE로 정리한 뒤 네트워크를 즉시 재개하며 Target은 재부팅하지 않는다.
짧은 non-critical gap도 네트워크는 재개하지만, 30초 연속 quiet가 되기 전에는 같은 unverified lease
epoch를 유지해 connect/disconnect churn이 10초 예산을 반복 갱신하지 못하게 한다. Verified action
generation이 생기면 별도의 85초 physical lease를 시작한다. 이 verified lease가 만료되는 비정상 경로도
socket을 호출하지 않는다. Relay를 fail-closed OFF로 정리하고 Local GATT와 signed MQTT lifecycle에
`INTERNAL_ERROR` terminal 및 일반 `access_critical_timeout` breadcrumb를 만든 뒤 ordered NVS/RTC
checkpoint를 시도한다. 그 다음에만 controlled restart하며 persistence degradation은 boot/status 진단에
남긴다.

GATT `RESULT` indication은 authenticated action commit 뒤의 transport 확인일 뿐 이미 시작된 Target
FSM을 취소하지 않는다. RESULT subscription 누락, indication 실패 또는 confirmation timeout이 action
commit 뒤 발생하면 protocol transport만 reset하고 verified actor/lifecycle context는 FSM terminal까지
유지한다. 따라서 이 실패가 가짜 `ACCESS_SESSION_TERMINATED`를 만들거나 이후 sensor/relay event를
actorless로 바꿔서는 안 된다. Commit 전 output failure만 protocol session을 실패 terminal로 닫는다.

현재 signed status는 boot당 최신 terminal 한 건만 보유한다. 현재 Target에서는 A가
`ARMED`인 동안 B가 인증되지 않으므로 A의 summary를 B가 덮는 경로가 없다. 단,
구형/N-1 이력에서 A의 `SESSION_SUPERSEDED` event 직후 B terminal이 latest summary를 덮은
경우를 위해 Backend 호환 fallback은 유지한다. Backend는 A의 exact actor-bound signed
terminated event와 같은 boot/count의 fresh Target-global `IDLE`/relay OFF/configured OFF pin을
제한적으로 결합해 A를 `terminated`와 `다음 인증 가능`으로 수렴시킨다. 이 fallback은
A의 성공 phase를 합성하거나 B의 중간 상태를 A에게 노출하지 않는다. failsafe terminal은
`IDLE` 전에도 즉시 `terminated`로 표시하지만, `다음 인증 가능`은 fresh `IDLE`/OFF가
확인되기 전까지 계속 false다.

Target 설정은 pre-arm 1~60초와 cooldown 1~10초로 boot/NVS/MQTT/Web 진입점에서 clamp되고 relay hold는
1초다. Verified `ARMED`부터 cooldown 종료까지는 새 인증을 모두 거부하므로 세션 교체가
deferral을 늘리는 경로가 없다. Pre-proof는 두 번의 5초 auth window를 합친 10초 unverified lease이고,
검증된 전체 정상 상한은 그 10초와 60초 arm, 1초 hold, 250ms failsafe grace, 10초 cooldown을 합친
81.25초다. 따라서 verified hard lease 85초보다 짧고, 그 lease는 90.25초 access-status grace보다
먼저 fail-closed한다. MQTT keepalive는 120초다. HA command는
기존 15초 freshness를 계속 요구하고, 연결 entity만 90.25초 signed-status watchdog을 사용해 정상
ARMED 중 false offline을 피한다. 이 grace는 broker 연결 자체를 새로 증명하거나 stale command를
허용하지 않는다.

Durable event queue가 포화되면 가장 오래된 두 record를 버린 범위를 `queue_overflow` transport
diagnostic으로 남긴다. 이 gap은 access event UUID/HMAC을 합성하지 않는 schema-v1 noncanonical
record이며 legacy diagnostic topic으로 발행·제거된 뒤 다음 signed event가 계속 진행되어야 한다.
따라서 gap 자체는 proof, sensor, relay 또는 physical door 결과가 아니고, 그 구간의 audit evidence가
유실됐다는 경고만 뜻한다. 재부팅 복구는 durable meta의 물리 ring head/tail slot을 RAM에서도 그대로
유지한다. 일부 record를 pop한 뒤 tail이 wrap된 상태에서 반복 재부팅하더라도 이미 제거한 event를
재생하거나 wrapped tail event를 누락해서는 안 된다.

Home Assistant의 access state는 Backend가 MAC-covered 필드만 allow-list한
`gatekeeper/v1/ha-bridge/<target_id>/verified-status`를 사용한다. IP, RSSI, 거리, heap과 설정 같은
raw diagnostics는 기존 Target `/status`에서 계속 읽을 수 있지만 broker ACL 뒤의 진단 표시일 뿐
인증·relay readiness 근거가 아니다. Source change, key provisioning 또는 retained discovery만으로
ACL 설치, NAS/HA 배포, phone/Target 설치나 실제 문 결과를 주장하지 않는다.

Target의 access-critical 구간에는 MQTT socket 작업을 다시 넣지 않는다. 완료 후 가장 먼저 flush되는
signed terminal/IDLE status의 `source_boot_count`와 `last_terminal_event_sequence`를 Backend가 검증하고
`<boot_count>-<sequence>` 비식별 표식으로 투영한다. HA `last_access_event` sensor는 결과와 이 표식을
state로 사용하므로 반복 성공이 같은 `IDLE`로 끝나도 한 세션당 한 번 Activity가 전진한다. 주기 status가
같은 terminal summary를 반복해도 state는 같아 추가 이력을 만들지 않는다. Session UUID, credential/actor
ref, reason과 HMAC tag는 HA projection에서 계속 제외한다. Canonical event와 관리자 이력은 별도 감사
경로이며, schema 013 HA transaction outbox는 DB에 도달한 event의 broker-route projection을 재시도한다.
이 sensor/outbox 어느 쪽도 Target→broker QoS 0 구간의 누락을 합성하거나 물리 문 열림을 증명하지 않는다.

Signed MQTT command는 callback에서 terminal event를 송신하지 않는다. 인증·replay 검증이 끝난 command의
session UUID와 mode만 RAM에 보존하고 FSM event callback이 phase bit를 더한다. Relay OFF 뒤 terminal
sequence와 summary를 완성하고 path-specific canonical terminal은 older volatile records 뒤의 ordered
checkpoint로 수락한다. NVS append가 막히면 reserved RAM tail과 전체 remaining-FIFO RTC A/B journal
generation을 함께 요구한다. 새 generation은 inactive slot의 checksum과 magic-last commit이 끝나기 전까지
이전 valid slot을 훼손하지 않는다. 복원한 generation은 즉시 지우지 않고, 그 generation이 나타내는 front
records가 실제 MQTT publish 또는 NVS migration으로 하나씩 제거되어 마지막 record가 확인될 때만 journal을
지운다. 중간 일부만 NVS로 이동한 뒤 다시 실패하면 현재 head부터 exact remaining FIFO를 inactive slot의
다음 generation으로 교체한다. 따라서 repeated soft reset은
at-least-once duplicate를 만들 수 있지만 terminal을 조용히 잃어서는 안 된다. 실제 signed event/status
publish는 IDLE safe-state의 loop-task owner가 수행한다. 단, NVS/RTC/RAM은 bounded이고 RTC는 cold power
loss 저장소가 아니며 Target publish QoS 0에는 Backend application ACK가 없으므로 무한 outage나 broker가
수락한 뒤 subscriber에 전달하지 못한 구간까지 절대 무손실로 주장하지 않는다.

`evidence_persistence_failed` breadcrumb는 event journal과 별개로 연속 software reset에 carry된다. Retained
boot diagnostics publish가 성공한 경우에만 previous-boot failure를 acknowledge/clear한다. 그 publish 전에
같은 boot에서 새 persistence failure가 발생했다면 새 latch는 유지되어 다음 reset으로 넘어가므로, 과거
경고의 전송 성공이 현재 boot의 새 failure를 지우지 않는다.

Signed reboot도 command callback에서 `ESP.restart()`를 호출하지 않는다. Callback은 command completion과
application ACK를 처리하고 reboot pending만 남긴다. Inbound QoS 1 PUBACK을 보낼 수 있도록
`client.loop()`가 반환한 뒤 main이 GATT admission을 busy로 잠그고 callback work를 drain하며, unverified
ingress만 bounded abort한 다음 verified physical session이 없음을 다시 확인한다. Verified action이
경쟁에서 이겼으면 그 terminal까지 reboot를 보류하고, 안전 상태에서는 위 NVS/RTC evidence checkpoint와
planned-restart breadcrumb를 남긴 뒤 재부팅한다.

HA relay binary sensor는 entity-registry 호환을 위해 historical object/unique ID의 `door_binary`를
유지하지만 표시명은 `[Gatekeeper] 릴레이 구동 상태`이고 door `device_class`는 없다. ON은 검증된
`RELAY_HOLD` projection일 뿐 독립 contact sensor나 물리 문짝 이동 증거가 아니다.

N/N-1 rollout은 새 Backend가 요구하는 key를 먼저 양쪽 release environment와 NAS keyring에
동일하게 provision한 뒤, **Target N을 먼저 설치·reboot·health 확인하고 Backend N, mobile N 순으로**
전진한다. Target N-1로 rollback하면 기존 출입/OTA는 유지되지만 actor/terminal evidence는
unavailable로 안전하게 degrade하며 `complete`를 합성하지 않는다. Backend N-1은 새 signed 필드를
출입 성공으로 오해하지 않아야 하고, 368-byte durable event ABI와 이전 reader 호환 overlay는
Target rollback 경로를 보존한다.

마지막으로 `ACCESS_SENSOR_DETECTED`, relay ON/OFF, terminal summary와 모바일 `다음 인증 가능`은
Target sensor/FSM/GPIO 결과다. 현재 설치에는 독립 door-contact sensor가 없으므로 문짝 이동이나
물리 개방 완료를 확인하지 못한다.
