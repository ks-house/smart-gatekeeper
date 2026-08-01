# security_protocol.md — Device key·BLE proof·signed ACL v1 규격

> 상태: **Wave 0 규격 동결 후보**
> 작성일: 2026-08-01
> 추적: [GitHub issue #16](https://github.com/ks-house/smart-gatekeeper/issues/16)
> OTA 상위 계약: [ota_reliability_contract.md](ota_reliability_contract.md)

## 1. 범위와 보안 목표

이 문서는 Android Keystore의 기기별 P-256 키, ESP32-C6의 로컬 challenge-response,
Backend가 서명한 ACL snapshot 사이의 공통 계약을 고정한다. 고정 iBeacon UUID, BLE MAC,
임의 `device_id`, 공통 API key는 발견·migration lookup에만 사용할 수 있으며 문을 여는 최종
자격이 아니다.

필수 보안 속성은 다음과 같다.

- private key는 Android Keystore 밖으로 export하거나 Backend/Target에 전송하지 않는다.
- proof는 한 `door_id`, `session_id`, `nonce`, `target_boot_id`, 짧은 expiry와 협상 결과에 묶인다.
- Target은 session을 성공 여부와 무관하게 단일 사용으로 소비하고 relay 전환 전에 소비 상태를
  확정한다.
- ACL은 신뢰 anchor로 검증한 서명, 단조 증가 버전, lease, protocol floor를 모두 통과한 뒤에만
  원자적으로 활성화한다.
- stale ACL, protocol downgrade, 캡처 proof replay, reset을 이용한 lease 연장을 fail-closed 한다.
- 인증 버전 불일치가 Android update manager나 Target periodic HTTPS/MQTT/local recovery OTA를
  막지 않는다.

이 v1 proof가 인증하는 것은 **등록 private key의 실시간 possession**이다. 현재 하드웨어와 BLE
GATT 왕복만으로 phone과 문 사이의 물리적 근접성이나 relay resistance를 증명하지 않는다. 문 앞의
real Target과 피해자 phone 사이를 deadline 안에 투명 중계하는 wormhole은 fresh proof를 얻으므로
nonce/session/boot binding을 통과한다. 따라서 hands-free production 배포는 §4.4의 `RELAY-G`를
별도로 통과해야 한다.

DoS, BLE radio jamming, 휴대폰 OS가 이미 완전히 장악된 경우, Backend ACL signing key 자체의
탈취는 이 프로토콜만으로 없앨 수 없다. 각각 rate limit/운영 fallback, Android 무결성 신호,
signing key 격리·교체 절차로 위험을 줄인다.

## 2. 공통 타입과 암호 primitive

| 항목 | v1 계약 |
|---|---|
| 정수 | unsigned, **network byte order(big-endian)**, 임의 padding 없음 |
| 식별자 | UUID 문자열이 아니라 16-byte RFC 4122 network-order 값 |
| 해시 | SHA-256 |
| 기기 서명 | ECDSA P-256(`secp256r1`) + SHA-256 |
| ACL 서명 | ECDSA P-256 + SHA-256, 기기 키와 별도 Backend signing key |
| 공개키 | SEC1 uncompressed 65 bytes: `0x04 || X(32) || Y(32)` |
| wire signature | IEEE P1363 `r(32) || s(32)`, 총 64 bytes, **low-S만 허용** |
| 문자열 | canonical signing input에는 가변 문자열을 넣지 않음 |
| 최대 재조립 message | 2,048 bytes |

수신기는 길이, 정수 범위, P-256 curve point, `1 <= r < n`, `1 <= s <= n/2`, trailing
byte 부재를 검사한다. 고정 길이 필드가 아니거나 high-S signature이면 같은 수학적 서명이라도
`MALFORMED`로 거부한다.

Android의 `Signature.getInstance("SHA256withECDSA")` 결과는 ASN.1 DER이다. Android 구현은
DER를 strict parse한 뒤 `r`, `s`를 각각 32-byte big-endian으로 left-pad하고, `s > n/2`이면
`n-s`로 바꾼 뒤 raw64로 전송한다. Target과 Backend는 raw64만 받으며 DER/raw 자동 감지는 하지
않는다. 서명 대상은 아래 canonical bytes 전체이고 SHA-256을 **한 번** 적용한다.

## 3. Android Keystore 자격 lifecycle

### 3.1 생성

앱은 사용자/tenant별 자격마다 alias
`sgk.device.p256.v1.<credential_id>`를 사용한다. 아직 Backend가 `credential_id`를 발급하지
않은 초기 등록은 random enrollment alias로 만들고 승인 응답 뒤 같은 key entry에 매핑을 저장한다.

키 생성 조건은 다음과 같다.

```kotlin
KeyPairGenerator.getInstance(
  KeyProperties.KEY_ALGORITHM_EC,
  "AndroidKeyStore",
).apply {
  initialize(
    KeyGenParameterSpec.Builder(
      alias,
      KeyProperties.PURPOSE_SIGN,
    )
      .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
      .setDigests(KeyProperties.DIGEST_SHA256)
      .setUserAuthenticationRequired(false)
      .build()
  )
}.generateKeyPair()
```

- 자동 출입 PoC는 화면이 잠긴 상태의 무인 서명이 필요하므로
  `setUserAuthenticationRequired(false)`를 명시한다. 이는 편의 결정이지 보안 강화가 아니다.
- StrongBox가 있으면 먼저 요청할 수 있지만 미지원/자원 부족이면 TEE-backed Android Keystore로
  재생성한다. StrongBox 존재를 출입 필수조건으로 만들지 않는다.
- `KeyInfo.securityLevel`, public key, 생성 시각, app build, attestation 결과를 민감하지 않은
  metadata로 기록할 수 있다. attestation은 risk signal이며 key possession proof를 대체하지 않는다.
- private key bytes, DER signature, nonce, proof canonical bytes는 analytics/crash report에 넣지 않는다.
- 앱 backup/restore로 alias metadata만 복원해서는 안 된다. Keystore entry가 없으면 기존
  credential을 자동 재사용하지 않고 새 enrollment를 시작한다.

### 3.2 enrollment

1. 사용자가 정상 HTTPS 로그인과 tenant 선택을 완료한다.
2. Backend가 32-byte CSPRNG enrollment nonce와 16-byte `enrollment_id`, 5분 expiry를 발급한다.
3. Android가 새 P-256 key를 만들고 public SEC1 key를 추출한다.
4. Android는 `SGKENR01 || version(u16) || tenant_id(16) || enrollment_id(16) ||
   nonce(32) || public_key(65)`를 같은 private key로 서명한다.
5. Backend는 로그인 주체, nonce 단일 사용/expiry, public key curve, proof-of-possession을 검증하고
   random 16-byte `credential_id`를 발급한다. 관리자 승인 전 상태는 `PENDING`이다.
6. 승인 후 다음 signed ACL에 `ACTIVE` entry가 들어가고 Target ACK가 관측되어야 로컬 출입을
   ready로 표시한다.

Backend가 받는 것은 public key와 서명뿐이다. private key export를 요구하는 API/디버그 경로,
공통 device secret fallback, 고정 `device_id`만으로 승인하는 migration은 금지한다. 같은 public
key를 다른 활성 credential에 중복 등록하지 않는다.

### 3.3 rotation·삭제·무효화

- 정상 rotation은 **새 키 enroll → 관리자 승인 → ACL activation ACK → 구 키 revoke** 순서다.
  두 키 overlap은 최대 24시간이며 같은 휴대폰이라는 이유로 구 키 회수를 생략하지 않는다.
- Keystore entry가 없거나 `KeyPermanentlyInvalidatedException`, provider 오류가 발생하면 local
  shared secret으로 내려가지 않고 `REENROLL_REQUIRED`로 중단한다.
- logout만으로 키를 지우지 않는다. tenant credential 삭제/기기 양도/앱 계정 제거 확인 시
  Backend revoke가 성공한 뒤 local alias를 삭제한다. revoke 요청이 실패하면 alias를 quarantine하고
  재시도한다.
- 앱 upgrade/rollback은 alias와 credential mapping을 보존한다. 새 앱이 이전 alias를 파괴적으로
  rename하거나 key algorithm을 즉시 교체하면 안 된다.

### 3.4 분실 휴대폰과 revoke SLA

user-auth 없는 키는 잠금 해제된 분실 휴대폰, 악성 accessibility, 앱 프로세스 탈취에 노출된다.
사용자/관리자 신고가 들어오면 Backend DB revoke는 즉시 완료하고 ACL을 새 버전으로 발행한다.

| 경로 | 목표 |
|---|---|
| online Target MQTT push + ACK | 60초 이내 |
| periodic HTTPS ACL pull | 최대 60초 interval |
| offline Target 기본 노출 상한 | 기본 lease 900초 |
| 운영 승인 가능한 절대 lease 상한 | 3,600초; 초과 snapshot은 Target가 거부 |

따라서 완전 offline 문에서의 최악 revoke 지연은 활성 snapshot의 남은 lease이며 최대 1시간이다.
가용성을 위해 이를 늘리려면 별도 threat review와 운영 승인이 필요하다. lease가 끝나면 자동 출입은
fail-closed하고 관리자 local recovery를 사용한다.

## 4. BLE GATT transport와 version negotiation

### 4.1 characteristic

| 용도 | UUID suffix | 속성 |
|---|---|---|
| Auth service | `9f4d1000-7d9e-4fb1-9c54-6f4d53474b31` | primary service |
| Hello/control | `9f4d1001-7d9e-4fb1-9c54-6f4d53474b31` | write + indicate |
| Challenge | `9f4d1002-7d9e-4fb1-9c54-6f4d53474b31` | read + indicate |
| Proof | `9f4d1003-7d9e-4fb1-9c54-6f4d53474b31` | write |
| Result | `9f4d1004-7d9e-4fb1-9c54-6f4d53474b31` | indicate |

Service UUID와 advertisement는 발견자이지 자격이 아니다. BLE Secure Connections link encryption은
privacy/DoS 완화를 위한 defense-in-depth로 사용할 수 있지만 app-layer proof 검증을 생략할 근거가
아니다.

### 4.2 MTU 독립 framing

모든 characteristic message는 negotiated ATT_MTU에서 아래 10-byte header로 fragment한다.
Bluetooth LE default ATT_MTU 23에서도 동작해야 하며 큰 MTU 성공을 가정하지 않는다.

| offset | size | field |
|---:|---:|---|
| 0 | 2 | magic ASCII `SG` |
| 2 | 1 | framing version, v1=`1` |
| 3 | 1 | message type |
| 4 | 2 | message_id |
| 6 | 1 | fragment_index, zero based |
| 7 | 1 | fragment_count, 1..255 |
| 8 | 2 | total_message_length, 1..2048 |
| 10 | N | fragment bytes |

한 ATT value의 data capacity는 `ATT_MTU - 3 - 10`이다. v1 message type은
`0x01 CLIENT_HELLO`, `0x02 TARGET_HELLO`, `0x10 CHALLENGE`, `0x11 PROOF`,
`0x12 RESULT`, `0x7f ERROR`다.

Target은 연결당 한 reassembly buffer와 동시에 한 `message_id`만 허용한다. index가 연속 증가하지
않거나 header가 fragment 사이에 달라지거나, 중복 fragment 내용이 다르거나, 누적 길이가 선언을
넘으면 즉시 buffer/session을 지운다. proof write는 2초 안에 완성되어야 한다. indication은 ACK 뒤
다음 fragment를 보내며 무제한 notify queue를 만들지 않는다.

### 4.3 Hello canonical payload

`CLIENT_HELLO`는 다음 16 bytes다.

```text
protocol_min u16 | protocol_max u16 |
framing_min u8 | framing_max u8 | max_rx_message u16 |
capabilities u32 | mobile_build u32
```

`TARGET_HELLO`는 다음 20 bytes다.

```text
selected_protocol u16 | target_protocol_min u16 | target_protocol_max u16 |
selected_framing u8 | status u8 | max_rx_message u16 |
capabilities u32 | firmware_build u32 | security_floor u16
```

선택 알고리즘은
`highest(min(client_max,target_max))` 중
`version >= max(client_min,target_min,security_floor)`인 값이다. 없으면
`UNSUPPORTED_VERSION`이며 auth service만 닫는다. `security_floor`는 firmware에 내장한 floor와
활성 signed ACL의 `min_protocol` 중 큰 값이다.

정상 N/N-1 fallback은 허용하되 모든 지원 버전이 같은 replay/door binding/ACL 검증 보안 속성을
유지해야 한다. 취약 버전 sunset은 floor를 올려 수행한다. 과거 연결에서 v2를 썼다는 local cache만으로
정상 rollback된 N-1 앱의 v1을 막지 않는다. 대신 양 peer의 현재 범위, signed floor, 아래 transcript
binding을 매 연결 다시 확인한다.

`negotiation_hash = SHA256(CLIENT_HELLO payload || TARGET_HELLO payload)`이며 challenge와 proof에
묶인다. hello 변조는 proof input을 바꾸거나 client security floor 검증에서 거부된다.

### 4.4 실시간 relay/wormhole 경계와 배포 Gate

공격자가 문 앞 proxy로 real Target의 hello/challenge를 받고 피해자 phone 근처 proxy로 그대로
전달한 뒤, phone의 fresh proof를 real Target에 5초 안에 돌려주면 v1 검증은 성공한다. 이는 캡처된
과거 proof의 replay가 아니며 `door_id`, `session_id`, `nonce`, `target_boot_id`, expiry가 모두
정상이다. Target static key를 phone에 pin하거나 BLE Secure Connections를 켜도 bit-for-bit tunnel을
종단하지 않는 한 이 transparent relay 자체는 막지 못한다.

다음 항목은 relay resistance로 인정하지 않는다.

- RSSI threshold, advertisement TX power, 연결 latency/5초 timeout만 사용
- BLE MAC/service UUID/device ID pinning
- Target signature 또는 mutual authentication만 추가하고 거리 제한 channel binding은 없음
- relay 장비를 시험하지 않은 일반 E2E 성공

production unlock은 기본 비활성이며 문별로 다음 중 **한 경로**를 release record에 선택해야 한다.

1. **Relay-resistant 경로:** 검증된 distance-bounding/UWB 또는 측정 가능한 상한을 제공하는 전용
   relay-resistant hardware transaction을 proof에 channel-bind한다. 두 proxy 공격이 정책 거리 밖에서
   거부된 실기기 증거가 필요하다. 일반 BLE/NFC의 nominal range만으로 이 분류를 부여하지 않는다.
2. **Interactive 완화:** 매 proof에 Android biometric/device credential과 명시적 door 확인을
   요구하거나 사용자가 해당 문 reader를 직접 tap하도록 하고 보안 책임자가 잔여
   social-engineering/NFC·BLE relay 위험을 승인한다. 이는 silent hands-free relay를 줄일 뿐
   cryptographic proximity 보장은 아니다.
3. **명시적 비근접성 수용:** 보안 책임자가 지정한 low-consequence door에만 possession-only임을
   서면 수용하고, 감사/이상 동시 세션 탐지/즉시 disable/rollback을 운영한다. 주거 외부 출입문,
   고가 자산, 안전·법규 경계에는 이 예외를 사용할 수 없다.

production enable 판정은 아래 세 Gate를 순서와 무관하게 **모두** 만족해야 한다. 한 Gate 객체나 필수
필드가 없거나 `false`이고, evidence 식별자가 비어 있고, 관측값·선택 경로·실행 횟수가 서로 맞지 않으면
fail-closed 한다. `relay_resistant_channel=true`를 포함한 capability/feature flag 하나만으로는 어떤 Gate도
대체하거나 우회할 수 없다.

| Gate | release record의 필수 증거 | fail-closed 조건 |
|---|---|---|
| `RELAY-G0` | 검토 완료한 threat model, 두 proxy byte-exact 시험 완료, 계산한 wormhole 결과와 일치하는 expected/observed 결과, 비어 있지 않은 `evidence_id`, **risk-owner 승인** | 객체/필드 누락, review/test/승인 false, expected 또는 observed 불일치 |
| `RELAY-G1` | `relay_resistant_channel`/`interactive_user_presence`/`low_consequence_acceptance` 중 하나의 `selected_path`, 실제 활성 control, 같은 경로를 지목하는 evidence와 비어 있지 않은 `evidence_id` | 경로 미선택·unknown, control false, capability와 경로 불일치, evidence 경로 불일치 |
| `RELAY-G2` | G1과 동일한 `selected_path`, `regression_complete=true`, **연속 100회 이상 전부 성공한 실기기 운용 결과**, OTA rollback 확인, 비어 있지 않은 `evidence_id` | 객체/필드 누락, 100회 미만, 일부 실패, G1 경로 불일치, rollback false |

따라서 `production_enabled = RELAY-G0.valid AND RELAY-G1.valid AND RELAY-G2.valid`다. G0의
risk-owner 승인은 relay-resistant 경로에도 예외 없이 필요하다. 현재 hands-free v1은 vector상 wormhole이
성공하고 세 Gate가 모두 없으므로 배포가 거부된다. interactive 또는 low-consequence 수용 경로는 G0/G2를
통과해도 cryptographic proximity를 제공하지 않는다는 잔여 위험을 release record에 유지한다.

## 5. Challenge와 proof canonical bytes

### 5.1 Challenge

Target은 연결마다 hardware CSPRNG로 16-byte `session_id`, 32-byte `nonce`를 새로 만든다.
`target_boot_id`도 매 boot마다 CSPRNG 16 bytes로 만들고 RAM에만 둔다. all-zero, 중복 RNG 결과는
fatal auth disable 상태로 처리한다.

`CHALLENGE` canonical payload는 정확히 138 bytes다.

| offset | size | field |
|---:|---:|---|
| 0 | 8 | ASCII `SGKCHAL1` |
| 8 | 2 | selected protocol_version |
| 10 | 16 | door_id |
| 26 | 16 | session_id |
| 42 | 32 | nonce |
| 74 | 16 | target_boot_id |
| 90 | 8 | expiry_monotonic_ms |
| 98 | 8 | active acl_version |
| 106 | 32 | negotiation_hash |

`expiry_monotonic_ms`는 Target boot monotonic clock의 절대 deadline이다. 기본 challenge 수명은
5초, 최대 10초다. Android wall clock과 비교하지 않고 Target만 판정한다. Target reset은 boot ID와
monotonic domain을 바꾸므로 이전 challenge/proof를 전부 무효화한다.

### 5.2 Proof signing input과 wire payload

Android가 `SHA256withECDSA`로 서명하는 bytes는 정확히 61 bytes다.

| offset | size | field |
|---:|---:|---|
| 0 | 8 | ASCII `SGKPRF01` |
| 8 | 32 | SHA256(CHALLENGE canonical payload 138 bytes) |
| 40 | 16 | credential_id |
| 56 | 1 | action, v1 open=`1` |
| 57 | 4 | client_capabilities |

`PROOF` wire payload는 별도로 다음 103 bytes다.

```text
protocol_version u16 | session_id 16 | credential_id 16 |
action u8 | client_capabilities u32 | signature_raw64 64
```

Target은 wire field로 현재 session을 찾은 뒤, 자신이 보관한 challenge canonical payload와 wire의
credential/action/capabilities로 signing input을 재구성한다. Android가 보낸 challenge hash나
canonical blob을 신뢰하지 않는다.

### 5.3 검증 순서와 단일 사용

Target은 다음 순서를 유지한다.

1. frame/길이/정수/signature encoding을 strict parse한다.
2. 현재 연결의 `protocol_version`, `session_id`, boot ID, deadline을 확인한다.
3. session을 `ISSUED → VERIFYING/CONSUMED`로 CAS 전환한다. 이후 어떤 실패도 같은 session 재시도를
   허용하지 않는다.
4. active ACL signature/lease/version과 credential status/time/protocol/OPEN permission을 확인한다.
5. canonical input을 재구성해 P-256 signature를 constant-time library API로 검증한다.
6. Target FSM이 IDLE일 때만 `ARMED`로 전환한다. relay는 기존 sensor/one-shot interlock 뒤에만 켠다.

동시에 최대 한 auth session만 허용하고 credential/connection 실패율을 rate limit한다. signature
실패 상세를 BLE peer에게 구분해 주지 않아 credential enumeration oracle을 줄인다.

`RESULT` payload는
`protocol_version u16 | session_id 16 | reason u16 | retry_after_ms u32 |
active_acl_version u64`(32 bytes)다. 공개 reason은 다음으로 고정한다.

| code | 이름 |
|---:|---|
| 0 | OK |
| 1 | UNSUPPORTED_VERSION |
| 2 | MALFORMED |
| 3 | SESSION_INVALID |
| 4 | EXPIRED_OR_REPLAY |
| 5 | ACL_UNAVAILABLE |
| 6 | CREDENTIAL_DENIED |
| 7 | PROOF_INVALID |
| 8 | BUSY |
| 9 | RATE_LIMITED |
| 10 | INTERNAL_FAIL_CLOSED |

## 6. Signed ACL snapshot과 offline lease

### 6.1 Canonical signed bytes

ACL signer는 운영 API/TLS/OTA signing key와 분리하고 HSM/KMS 또는 최소한 별도 offline secret으로
보호한다. Target firmware에는 허용된 public signing key ID와 public key만 넣는다.

ACL canonical header는 72 bytes다.

| offset | size | field |
|---:|---:|---|
| 0 | 8 | ASCII `SGKACL01` |
| 8 | 2 | schema_version=`1` |
| 10 | 16 | door_id |
| 26 | 8 | acl_version |
| 34 | 8 | issued_at_epoch_s |
| 42 | 8 | not_before_epoch_s |
| 50 | 8 | expires_at_epoch_s |
| 58 | 4 | lease_duration_s |
| 62 | 2 | min_protocol |
| 64 | 2 | max_protocol |
| 66 | 4 | signing_key_id |
| 70 | 2 | entry_count |

각 entry는 `credential_id` 오름차순, 중복 없이 106 bytes다.

```text
credential_id 16 | public_key_sec1 65 | status u8 |
permissions u32 | not_before_epoch_s u64 | not_after_epoch_s u64 |
min_protocol u16 | max_protocol u16
```

`status`: `0=REVOKED`, `1=ACTIVE`; `permissions` bit0은 OPEN이며 v1의 known mask는
`0x00000001`이다. 다음 semantic 조건을 canonical encoding과 Target 수신 검증 양쪽에서 같은
`MALFORMED`로 거부한다.

- `schema_version != 1`, `acl_version < 1`, lease가 1..3,600초 밖인 snapshot
- `issued_at <= not_before < expires_at` 또는 `1 <= min_protocol <= max_protocol`을 위반한 header
- unknown status 또는 known mask 밖 permission bit
- `entry.not_before < entry.not_after` 위반
- `snapshot.min_protocol <= entry.min_protocol <= entry.max_protocol <= snapshot.max_protocol` 위반
- SEC1 길이/prefix/좌표 범위/P-256 curve equation을 통과하지 못한 public key
- 정렬되지 않거나 중복된 credential, 64개 초과 entry

서명은
`SHA256withECDSA(72-byte header || sorted entries)`의 low-S raw64이며 envelope에 별도 첨부한다.

ACL은 door별 authoritative snapshot이다. snapshot에 없는 credential은 denied다. revoked tombstone은
감사/점진 동기화를 위해 들어갈 수 있지만 절대 authorize하지 않는다.

### 6.2 검증과 atomic activation

1. 최대 크기와 schema를 검사하고 `door_id`, trust anchor, signature를 검증한다.
2. `acl_version > effective_high_watermark`만 새 후보로 받는다. 같은 version+같은 digest는
   idempotent ACK만 하며 lease를 다시 시작하지 않는다. 같은 version+다른 digest는 signer/backend
   충돌로 fail-closed한다.
3. time/lease/protocol/entry semantic validation을 전부 완료한다.
4. inactive NVS slot에 blob, signature, digest, metadata CRC를 쓰고 commit한다.
5. read-back 후 다시 signature/digest를 검증한다.
6. 이전 record와 다른 NVS key에 다음 **단일 activation generation blob**을 한 번에 쓴다.

   ```text
   magic | record_schema | generation | active_slot |
   acl_version | acl_digest | high_watermark(=acl_version) | CRC
   ```

7. blob commit/read-back/CRC가 성공한 뒤에만 runtime active를 새 slot으로 바꾸고 ACK한다. active
   pointer와 high-watermark를 별도 commit하지 않는다. 두 generation key를 번갈아 써서 마지막
   정상 record를 보존한다.

candidate slot write 뒤 generation record 전에 crash하면 새 snapshot은 아직 활성화되지 않은 것으로
간주하고 이전 record를 쓴다. generation record가 torn이면 CRC-invalid record를 무시한다. record가
durable해진 뒤 crash하면 그 record 안의 pointer와 high-watermark가 함께 새 version이다.

boot recovery는 ACL download/subscribe/auth service보다 먼저 다음을 수행한다.

1. 두 activation record의 magic/schema/CRC/generation을 검사한다. CRC-valid record의 version은
   참조 slot이 손상됐더라도 anti-rollback floor 계산에는 포함한다.
2. `effective_high_watermark = max(all valid record versions, valid legacy active snapshot version,
   persisted legacy high_watermark)`로 계산한다.
3. 과거 split layout에서 `legacy active > legacy high-watermark`이면 repaired generation/floor를
   **candidate 비교 전에 영구 commit**한다. 반대로 watermark가 active보다 앞서면 과거 active를
   authorize하지 않고 fail-closed한다.
4. 가장 높은 valid generation이 가리키는 slot의 digest/signature/semantic과 record version을
   검증한다. 이 slot이 손상되거나 version이 effective floor보다 낮으면 이전 slot으로 권한 rollback하지
   않고 fail-closed + 새 compatible snapshot fetch를 수행한다.
5. 이후 모든 candidate 비교는 runtime/persisted 단일 값이 아니라 위 effective floor를 사용한다.

전원 차단 시 이전 active snapshot과 credential blob을 덮어쓰지 않는다. 단, 더 높은 version을 한 번
활성화한 뒤 과거 ACL로 **보안 rollback**해서는 안 된다. 새 active가 손상되면 이전 snapshot으로
권한을 복구하지 말고 fail-closed + network/local recovery로 새 snapshot을 받는다. 이전 slot은
forensic/복구 자료일 뿐 authorize source가 아니다.

공통 crash vector는 candidate slot 전/후, torn record, record commit 직후, committed slot 손상,
legacy pointer-first와 watermark-first 경계를 모두 고정한다. 예를 들어 legacy `active=v43,
watermark=v41`은 boot에서 effective=43을 먼저 영구 복구하므로 signed v42를 거부한다.

### 6.3 lease와 부정확한 clock

- `lease_duration_s` 기본 900, hard max 3,600이다.
- trusted UTC가 있으면 `not_before <= now < expires_at`과
  `deadline = min(receipt_monotonic + lease_duration, expires_at 대응 monotonic)`를 모두 적용한다.
- UTC가 없으면 **현재 boot에서 방금 서명 검증해 받은 새 version**만
  `receipt_monotonic + lease_duration`까지 쓸 수 있다. cached snapshot은 reboot 후 활성화하지 않는다.
- equal-version replay는 receipt/deadline을 갱신하지 않는다. Backend는 새 lease를 줄 때 반드시 새
  `acl_version`을 발행한다.
- wall clock이 허용 오차보다 뒤로 점프하면 ACL을 fail-closed한다. 앞으로 점프하면 조기 expiry는
  허용하되 만료를 되돌리지 않는다.
- reset/power cycle 뒤 trusted UTC를 복구하지 못하면 새 signed snapshot을 받기 전 자동 출입은
  비활성이다. reset으로 offline lease를 무한 연장하는 것보다 가용성 저하를 택한다.

revocation은 MQTT push와 periodic HTTPS pull 두 경로로 배포하고 둘 다 같은 signed artifact와 atomic
engine을 사용한다. broker payload 자체나 MQTT retained 순서만 신뢰하지 않는다.

### 6.4 ACL signing key rotation

Target trust store는 current와 previous ACL signer public key를 N/N-1 rollout 기간 함께 가진다.
새 signing key는 **Target OTA 배포/health 확인 → Backend dual-sign 또는 이전 signer로 새 key 승인 →
새 signer 사용 → rollback window 종료 후 구 signer 제거** 순서다. rollback firmware가 모르는 signer로만
ACL을 발행하지 않는다. signing key compromise 시 protocol version floor만 올려서는 해결되지 않으며
별도 emergency firmware/trust-anchor rotation이 필요하다.

## 7. Threat model과 판정

| 위협 | 차단 규칙 | 잔여 위험/운영 대응 |
|---|---|---|
| 캡처 proof 재전송 | session/nonce 단일 사용, 5초 expiry | radio DoS는 rate limit |
| 다른 door/session 재사용 | door/session/nonce가 challenge hash로 서명됨 | 없음(키 미탈취 가정) |
| Target reset 뒤 replay | 매 boot random boot ID, RAM session 폐기 | RNG health 실패 시 auth disable |
| signature malleability | strict raw64 + low-S | library regression을 vector로 차단 |
| BLE MITM downgrade | highest common, 양쪽 floor, hello transcript binding | 안전한 N-1 자체는 공격자가 유도 가능하므로 N-1도 같은 보안 속성 유지 |
| stale/reordered ACL | signed monotonic version + persisted high-watermark | NVS 손상 시 fail-closed |
| equal ACL replay로 lease 연장 | 같은 version은 deadline 갱신 금지 | Backend가 lease마다 version 증가 |
| clock rollback/power cycle | monotonic deadline, reboot 시 untrusted cached ACL 금지 | offline reset 뒤 자동 출입 불가 |
| revoked/lost phone | 60초 sync, 15분 기본/1시간 hard lease | lease 동안 user-auth 없는 키 악용 가능 |
| BLE MAC/UUID/device_id 복제 | 복제 값만으로 proof 생성 불가 | presence spam과 wormhole의 phone-side 유인 endpoint로 사용 가능 |
| malformed/oversized fragment | 2,048-byte cap, one buffer, strict sequence | connection-level DoS rate limit |
| ACL signer 탈취 | 별도 key 격리, trust-anchor rotation | emergency firmware rollout 필요 |
| Android 앱/OS 장악 | hardware-backed key, revoke, 짧은 lease | sign API를 호출할 수 있는 완전 장악은 방지 못함 |
| 실시간 BLE relay/wormhole | v1 nonce/session/boot는 fresh 중계 proof를 거부하지 못함 | possession만 인증; §4.4 RELAY-G 전 production 기본 비활성 |
| OTA rollback | protocol/ACL schema N/N-1, credential 보존 | 호환 snapshot 없으면 auth fail-closed, OTA는 계속 가능 |

## 8. OTA·N/N-1·rollback 불변조건

1. Target auth GATT task/ACL parser 실패는 periodic HTTPS, MQTT OTA command, 인증된 local wireless
   recovery task를 종료하거나 lock하지 않는다. OTA service/partition/state machine은 별도다.
2. Android credential worker 실패/버전 mismatch는 update discovery/download/install UI와 manager를
   차단하지 않는다. update 접근에 유효 ACL이나 BLE session을 요구하지 않는다.
3. 각 release는 current `N`과 previous `N-1` protocol을 지원하고 shared canonical vector를 통과한다.
   지원 종료는 signed floor와 앱 최소 버전을 rollout한 후 별도 release에서 한다.
4. Android upgrade/rollback은 Keystore alias를 보존한다. Target OTA는 active ACL/high-watermark를
   copy-on-write로 보존하고 health confirmation 전 irreversible schema migration을 commit하지 않는다.
5. 새 ACL schema는 rollback image가 읽을 수 있는 backward-compatible encoding 또는 dual snapshot을
   제공한다. rollback image가 현재 high-watermark ACL을 검증할 수 없으면 과거 ACL로 내려가지 않고
   fail-closed + compatible snapshot fetch를 수행한다.
6. Backend는 expand→migrate→contract 순서로 N/N-1 enrollment/ACL fields를 병행한다.
7. auth negotiation 실패 result와 OTA health/rollback telemetry는 서로 다른 reason domain을 사용한다.

공통 vector의 `N_N`, `mobile_N_target_N_minus_1`, `mobile_N_minus_1_target_N`,
`rollback_to_N_minus_1`, `downgrade_below_floor`, `no_overlap`이 release-blocking 최소 matrix다.
v2 자체의 wire schema를 이 문서가 미리 정의하는 것은 아니며 해당 case는 selection algorithm의
미래 N/N-1 동작을 고정한다.

## 9. Secret·privacy 비로그 정책

다음 값은 production log, analytics, crash report, MQTT event, GitHub Actions output에 원문을 남기지
않는다.

- Android private key 또는 export 시도 결과
- ACL signing private key, `GITHUB_TOKEN`, API/MQTT/Wi-Fi credential
- enrollment/challenge nonce, proof canonical bytes, raw/DER signature
- 전체 public key, ACL snapshot body, stable device identifier와 사용자 PII의 결합

허용되는 auth log는 `event_id`, protocol/schema version, ACL version, 공개 reason code,
Target boot ID/session ID의 비가역 HMAC 또는 앞 8 hex가 아닌 keyed correlation token, latency,
firmware/app build다. 운영 환경에서 raw vector dump debug flag를 금지한다. 테스트 fixture scalar는
`protocol/test_vectors/`의 공개·비운영 값이라고 명시하며 어떤 운영 자격에도 재사용하지 않는다.

## 10. 공통 canonical vector와 자동 검증

세 구현 트랙은 [v1.json](../protocol/test_vectors/v1.json)을 같은 source of truth로 사용한다.

- Android: field encoder 결과, DER→low-S raw64 변환, Keystore 생성 signature의 Target verification을
  비교한다.
- ESP32-C6: 동일 bytes를 만들고 mbedTLS P-256 verify, fragment reassembly, session replay state를
  검증한다.
- Backend: enrollment public key와 ACL signer가 같은 canonical ACL bytes/raw64를 생성·검증한다.

repo의 stdlib-only verifier는 committed canonical hex/hash, RFC 6979 fixture signature, P-256 verify,
high-S/wrong-key/mutation 거부, default MTU 23의 14-fragment framing, N/N-1 selection을 검증한다.
또한 6개 ACL activation crash boundary, 8개 strict ACL semantic rejection, 16개 relay/deployment
policy case를 같은 JSON에서 실행한다. relay case는 G0/G1/G2 각각의 누락·false·evidence 불일치,
risk-owner 승인 없음, G2 100회 미달, 단일 relay-resistant flag 우회를 negative vector로 고정한다.
hands-free v1 transparent wormhole은 `wormhole_succeeds=true`, `deployment_allowed=false`가 정답이며
이 결과를 green CI가 숨기지 않는다.

```powershell
python protocol/tools/verify_vectors.py
python -m unittest discover -s protocol/tests -v
```

CI는 `.github/workflows/protocol.yml`에서 같은 명령을 실행한다. 실제 Android/ESP32/Backend 구현 PR은
자체 unit test에서 이 JSON을 직접 읽거나 JSON에서 생성한 fixture를 사용하고, 생성 fixture가 JSON과
동일한지 이 verifier로 먼저 확인해야 한다. fixture 수정은 세 트랙 review와 protocol version 판단 없이
허용하지 않는다.

현재 vector가 고정하는 핵심 값은 다음과 같다.

| artifact | SHA-256/결과 |
|---|---|
| challenge canonical 138 bytes | `7cebae229af25267c8ae244cdb476a48a692feb81477cbc7f36e110e993bd464` |
| proof input 61 bytes | `7ea891a2a7270357f691240d0cc95cad3bfa4d8a9c48882a53482c809feadcae` |
| ACL canonical 178 bytes | `cc7010e328c5e5e89f5facf30fec10971e925cb34b8984245d623cb84544cea5` |
| ATT_MTU 23 challenge framing | 14 fragments, exact frame hex는 JSON 참조 |

## 11. 구현 release gate

- Android: non-export key, enrollment possession proof, missing/invalidated key 재등록, DER strict parser,
  low-S raw64, secret redaction 시험
- Target: RNG/boot ID, 5초 single-use session, strict reassembly, ACL atomic/high-watermark, clock/reset,
  signature/floor/FSM 검증, generation record의 각 write/commit 경계 power-cut, 100회
  GATT+Wi-Fi/MQTT/OTA coexistence
- Backend: unique public key, 관리자 승인/revoke, 60초 dual-path sync, monotonic snapshot, signing key
  격리, ACK/audit, expand-migrate-contract
- 공통: positive vector, proof replay/cross-door/cross-session/cross-boot/high-S/malformed/stale ACL/
  clock rollback/N/N-1/rollback/no-overlap, ACL semantic negative/crash recovery 자동 시험
- Relay: threat-model review·두 proxy wormhole 결과·risk-owner 승인(`RELAY-G0`), evidence와 일치하는
  relay-resistant/interactive/명시적 low-consequence 경로(`RELAY-G1`), 같은 경로의 100회 전 성공
  실기기 운용·OTA rollback regression(`RELAY-G2`)을 모두 통과하지 않으면 production unlock 비활성
- OTA: mobile install과 Target install→reboot→health confirmation, 기존 APK/bootable slot/credential/ACL
  보존을 [OTA 계약](ota_reliability_contract.md)의 G0~G3에서 확인

## 12. 근거 문서

- [Android Keystore system](https://developer.android.com/privacy-and-security/keystore)
- [KeyGenParameterSpec.Builder API](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder)
- [NIST FIPS 186-5 Digital Signature Standard](https://csrc.nist.gov/pubs/fips/186-5/final)
- [Bluetooth Core Specification — GATT/ATT_MTU](https://www.bluetooth.com/specifications/specs/core-specification/)
- [Bluetooth Channel Sounding — secure distance bounding and relay countermeasure](https://www.bluetooth.com/learn-about-bluetooth/feature-enhancements/channel-sounding/)
- [ESP-IDF ESP32-C6 security overview](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c6/security/security.html)
