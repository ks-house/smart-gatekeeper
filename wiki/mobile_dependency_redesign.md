# 모바일 의존성 축소 재설계 분석

> 분석일: 2026-08-01
> 상태: **설계 제안 — 현재 구현을 변경하거나 확정 아키텍처로 대체하지 않음**
> 범위: 화면 OFF BLE 감지부터 문 개방까지의 모바일·Backend·Target 책임 재분배

## 1. 결론

현재 문제의 본질은 모바일 앱의 개별 버그 하나가 아니라 **모바일 앱이 출입의 필수
제어 경로에서 너무 많은 직렬 책임을 지는 구조**다. 앱은 단순 자격 증명이 아니라
다음을 모두 성공시켜야 한다.

```text
프로세스/foreground service 생존
→ 권한·Bluetooth·위치·알림·배터리/OEM 정책 충족
→ native BLE scan과 Flutter stream/IPC 생존
→ UUID/RSSI/EMA/화면 상태/쿨다운 판정
→ 인터넷·DNS·TLS·REST 성공
→ Backend DB 승인·MQTT PUBACK
→ Target ARM·초음파·relay
```

직렬 관문은 하나만 실패해도 전체 출입이 실패한다. 최근 수정들은 IPC와 scan의 개별
결함을 줄였지만, Android/OEM이 관리하는 프로세스 생존과 무선 스캔 시점을 앱이
보장할 수 없다는 구조적 한계는 제거하지 못했다.

권장 방향은 **“모바일을 더 확실히 깨우는 앱”이 아니라 “모바일 백그라운드 실행이
없어도 출입하는 문 중심(door-centric) 구조”**다.

- 문 앞 센서와 Door Controller가 출입 세션과 물리 상태를 소유한다.
- 인증은 Door Controller가 로컬 캐시된 자격으로 검증한다.
- NAS/Backend/MQTT는 권한 동기화·회수·감사 로그를 담당하되 정상 출입의 실시간
  필수 경로에서 빠진다.
- 모바일 앱은 등록·자격 발급·상태 표시·원격 관리만 맡는다.
- 스마트폰 자격은 **NFC/Wallet의 명시적 tap**을 기본으로 하고, 자동 hands-free가
  필요하면 스마트폰이 아니라 **전용 BLE fob**을 주 채널로 둔다.
- 스마트폰 BLE hands-free는 편의 채널로만 유지하고 NFC/fob 같은 독립 fallback을
  반드시 둔다.

**스마트폰만 사용**, **완전 자동**, **화면 OFF/강제 종료/OEM 무관 보장**을 동시에
만족시키는 일반 앱 구조는 현실적으로 없다. 세 조건을 모두 요구하면 모바일 OS가
제어하는 백그라운드 실행을 다시 필수 경로에 넣게 된다.

## 2. 첨부 화면에서 확인되는 사실

15:13:19~15:14:09 콘솔에는 다음 패턴이 보인다.

- `foreground service IPC 포트 등록 완료`가 반복된다.
- `ranging 구독 재생성 완료 (신호 무수신 자동 복구)`가 약 10초 간격으로 반복된다.
- 같은 구간에 `Target ranging 패킷 수신`, 화면 OFF 패킷 수신, Pre-arm 시작/응답,
  HTTP 오류는 보이지 않는다.
- 화면의 Target Tx 설정은 `-6 dBm`이고, ToF/초음파 기준은 `80 cm`, Pre-arm은
  `60 s`, Target relay cooldown은 `5 s`다.

현재 코드에서 `신호 무수신 자동 복구`는 마지막 유효 RSSI가 6초 넘게 갱신되지 않을
때 발생한다. `native callback 무수신 자동 복구`와는 다른 분기다. 따라서 이 화면은
다음처럼 해석해야 한다.

### 확인 가능한 것

1. UI 로그 경로는 적어도 해당 메시지를 받을 정도로 연결돼 있다.
2. Dart timer와 ranging 재구독 로직은 실행 중이다.
3. 이전 어느 시점에는 유효 RSSI가 있었지만, 캡처 구간에는 Target UUID와 일치하는
   유효 패킷/RSSI가 계속 들어오지 않았다.
4. `_processBeacon()`에서 패킷을 처리해야 Pre-arm API가 호출되므로, 이 구간에는 API
   이전 BLE 수신 단계가 우선 의심된다.

### 이 화면만으로 확정할 수 없는 것

- AltBeacon native callback 자체가 모두 멈췄는지: 빈 ranging callback은 살아 있을
  수 있다.
- Target이 광고를 중단했는지, Android/OEM이 필터 결과를 주지 않았는지, 인체 차폐나
  `-6 dBm` 저출력 때문에 패킷이 소실됐는지.
- 다른 시각에 API 요청이 발생했거나 Backend가 응답하지 않았는지.

`-6 dBm`은 현재 선택지 중 가장 낮은 발신 출력이다. 이것이 단독 원인이라고 단정할
수는 없지만 화면 OFF·주머니 인체 차폐와 결합하면 RF margin을 줄이는 조건이므로,
앱 wake/API 문제와 분리해 시험해야 한다.

## 3. 현재 모바일 책임과 실패 표면

| 모바일 책임 | 현재 구현 | 실패하면 보이는 현상 | 구조적 문제 |
|---|---|---|---|
| 실행 생존 | foreground-service Flutter engine/isolate | 알림·heartbeat·scan 소실 | force-stop, Active Apps 중지, OEM 정책은 앱이 복구 불가 |
| 권한/OS 상태 | 위치 항상 허용, BLE, GPS, 알림, 배터리 예외 | 서비스 시작 차단 또는 0건 scan | 사용자/OEM 설정이 정상 출입의 필수 조건 |
| native 연동 | AltBeacon fork, Flutter EventChannel | subscription은 있으나 callback/RSSI 정지 | plugin·engine·notifier·OS scanner가 직렬 결합 |
| UI IPC | receive port와 service `SendPort` | 실제 동작과 Debug 화면 불일치 | 과거 package-replace 선실행과 null port로 로그 유실 |
| 근접 판정 | UUID, RSSI EMA, 8 dB hysteresis | 패킷을 받아도 API 미호출 | 주머니·자세·기종별 RSSI를 권한 판정에 사용 |
| 화면 상태 예외 | 화면 OFF에서 RSSI 임시 우회 | 원거리에서도 Pre-arm 가능 | 진단 편의를 위해 보안/근접 의미가 달라짐 |
| 재시도/중복 제어 | cooldown, in-flight guard | 정상 패킷인데 요청 생략 또는 반복 arm | 출입 세션 경계를 모바일 시간이 소유 |
| 신원 제시 | 로컬 random `device_id` | DB 등록값이면 승인 | device ID 자체에 소유 증명이 없음 |
| 서버 통신 | REST 4초 timeout, API key | 통신 오류/401/403/503 | 인터넷과 Backend가 문 앞 실시간 경로에 존재 |
| 설정 일관성 | Backend remote config + 로컬 override | 앱/Target 임계값 불일치 | 출입 정책의 단일 소유자가 없음 |

모바일이 이 모든 책임을 수행한 뒤에도 Backend, DB, broker, Target Wi-Fi/MQTT, 센서,
relay가 추가로 성공해야 한다. 앱만 보강해서는 전체 시스템의 직렬 실패 표면을 충분히
줄일 수 없다.

## 4. 지금까지 드러난 문제를 구조별로 재분류

### 4.1 모바일 생애주기·관측 문제

- foreground service 상태바 알림 미표시와 실제 서비스 실행 여부가 구분되지 않았다.
- service 시작 뒤 receive port를 등록해 초기 `SendPort`가 null이면 이벤트·에러·진단
  IPC가 조용히 유실됐다.
- package-replace 자동 실행이 UI보다 먼저 service를 시작해 null port 상태를 계속
  보존할 수 있었다.
- 앱/알림창 복귀마다 service를 재시작해 scanner 초기화가 반복되는 경로가 있었다.
- Debug UI가 비어 있다는 사실이 service 미실행 증거인지 IPC 유실인지 구분되지 않아
  진단 자체가 blind spot이었다.

이 항목들은 수정됐거나 완화됐지만, 출입 기능과 진단 UI가 두 Flutter engine/isolate,
native plugin, Android service 생애주기에 걸쳐 있다는 복잡성은 남아 있다.

### 4.2 BLE 수신·근접 판정 문제

- 과거에는 monitoring enter가 ranging 시작의 단일 관문이어서 화면 OFF enter 누락 시
  RSSI와 API가 모두 영구 정지할 수 있었다.
- monitoring과 ranging 병렬화 뒤에도 ranging 신호/콜백 무수신 watchdog이 반복해서
  subscription을 재생성한다.
- region OUTSIDE와 실제 ranging 패킷이 충돌해 상태 표시가 모순된 적이 있다.
- RSSI는 화면 상태보다 휴대폰 자세, 주머니, 신체 차폐, 기종 안테나와 Tx 출력에 크게
  영향을 받는다.
- 화면 OFF 임시 RSSI 우회는 패킷 수신 진단에는 유용하지만 장기 근접 판정 정책으로
  사용할 수 없다.
- Target iBeacon UUID byte order/stack은 raw advertisement 실측 전까지 완전히 닫히지
  않은 P0 항목이다.

첨부 로그는 이 계층이 여전히 가장 먼저 끊기는 현장 증거다.

### 4.3 API·Backend·MQTT 문제

- 공개 Backend가 503/upstream connection refused였던 운영 장애가 관측됐다.
- 앱이 `mqtt_published=true`를 받아도 이는 broker PUBACK까지이며 Target의 ARM 수신과
  상태 전환 ACK가 아니다.
- correlation/session ID가 없어 한 API 요청과 Target `pre_armed`/`arm_rejected`를
  정확히 연결하지 못한다.
- Backend가 설정 broker 외 후보 주소를 순회해 Target이 없는 broker의 PUBACK을 성공으로
  오인할 여지가 있다.
- 서버·DB·인터넷 장애는 화면 ON/OFF와 무관하게 자동 출입을 막는다.

### 4.4 출입 세션 소유권 문제

- 모바일 cooldown이 끝난 뒤 강한 RSSI가 계속되면 같은 사람에게 Pre-arm 요청을 다시
  보낼 수 있었다.
- Target이 과거에는 ARMED/COOLDOWN에서도 ARM을 받아 상태를 덮어쓰고, 이전 초음파
  표본을 다음 세션에서 재사용할 수 있었다.
- Target을 `IDLE`에서만 ARM 수락하도록 수정해 상태 전이는 보강했지만, IDLE 복귀 뒤의
  같은 사람/같은 접근을 새 세션으로 보는 문제는 남는다.

출입 세션과 anti-passback은 모바일 cooldown이 아니라 문 앞 센서와 relay 상태를 아는
Door Controller가 소유해야 한다.

### 4.5 인증·보안 문제

- 고정 iBeacon UUID는 복제 가능한 위치 힌트이며 자격 증명이 아니다.
- 앱이 보내는 random `device_id`는 단순 문자열이다. 등록된 값을 아는 클라이언트가
  그 기기의 실제 소유자임을 증명하는 challenge-response가 없다.
- `GATEKEEPER_API_KEY`는 빌드에 공통 주입되는 shared key이고, 서버에서 미설정이면
  pre-arm API가 키 없이 열린다.
- 따라서 “고정 UUID + 등록 device_id + 선택적 공통 API key”는 replay/spoofing을
  완전히 차단하는 사용자별 암호 자격으로 볼 수 없다.

재설계에서는 **presence와 authentication을 분리**해야 한다. 센서는 누군가 왔다는
사실만 만들고, 문은 nonce 기반 사용자별 암호 증명이 있어야 열린다.

## 5. 후보 아키텍처 비교

| 후보 | 모바일 백그라운드 의존 | 자동 통과 | Android/iOS 범용성 | 추가 하드웨어 | 판정 |
|---|---:|---:|---:|---:|---|
| A. 현재 Flutter/AltBeacon 계속 보강 | 높음 | 가능 | 낮음 | 없음 | 단기 진단용, 근본 해결 아님 |
| B. Android native `PendingIntent` BLE scan/CDM | 중간 | 가능 | Android 한정 | 없음 | 현 구조보다 단순하지만 모바일 OS 의존 잔존 |
| C. Door가 smartphone BLE 광고를 scan | 중간 | 가능 | 낮음 | 없음/소규모 | scan 책임은 이동하지만 phone background 광고가 새 병목 |
| D. 스마트폰 NFC/HCE·Wallet tap | 매우 낮음 | tap 필요 | 구현 방식에 따라 중간~높음 | NFC reader | 모바일 앱 wake/상시 scan 제거, phone 중심 최선 |
| E. 전용 secure BLE fob + NFC fallback | 없음 | 가능 | 높음 | fob + reader | 신뢰성 최우선 권장 |
| F. QR/Wallet barcode + 고정 scanner | 없음 | 화면 표시 필요 | 높음 | camera/scanner | NFC entitlement 제약의 실용 fallback |

Android 공식 지침도 앱 프로세스가 죽을 수 있는 background discovery에는 callback 기반
상시 scan 대신 filter가 있는 `PendingIntent` scan 또는 Companion Device API를
대안으로 제시한다. 이는 A보다 B가 낫다는 근거지만 OEM/OS가 이벤트와 프로세스 재개를
관리한다는 사실은 변하지 않는다.

스마트폰 BLE 광고로 역할을 다시 역전하는 C도 완전한 해결이 아니다. Android process
정책이 남고, iOS background advertising은 local name 생략, service UUID overflow,
광고 주기 저하 같은 제한이 있어 phone-only hands-free의 범용성을 보장하기 어렵다.

NFC tap은 Android에서 reader 접근이 `HostApduService`를 직접 시작할 수 있어 상시 BLE
scan보다 모바일 생애주기 의존이 작다. 다만 화면 OFF/Secure NFC 동작은 OS 버전과 사용자
설정에 따라 다르고, Apple Wallet NFC는 entitlement/reader 생태계 검토가 필요하다.
그래서 phone-only라면 NFC/Wallet을 주 채널로, QR 또는 물리 fob를 fallback으로 둔다.

## 6. 권장 목표 아키텍처

### 6.1 원칙

1. **물리 감지, 인증 세션, relay는 Door Controller가 소유한다.**
2. **정상 출입은 WAN, NAS, DB, MQTT 실시간 응답 없이 가능해야 한다.**
3. **모바일 앱 process가 없어도 최소 하나의 승인 자격 경로가 동작해야 한다.**
4. **RSSI는 편의상 후보 선택에만 사용하고 최종 인증으로 사용하지 않는다.**
5. **모든 명령과 결과는 `session_id`로 상관 가능해야 한다.**
6. **중복 방지와 anti-passback은 문 상태를 아는 controller에서만 판정한다.**

### 6.2 구성

```text
                    비동기 권한/회수/감사 동기화
       ┌──────────────────────────────────────────────────┐
       │                                                  ▼
[Backend/DB] <──── signed ACL + version/expiry ────> [Door Controller]
       ▲                                                  │
       │ 비동기 access event queue                        ├─ presence sensor
       │                                                  ├─ NFC/Wallet reader
[Mobile 관리 UI]                                         ├─ optional BLE-fob reader
                                                          ├─ door/contact/exit input
                                                          └─ relay fail-safe

자격 채널
  1순위 신뢰성: secure BLE fob (hands-free)
  2순위 phone: NFC/HCE 또는 Wallet tap
  fallback: NFC card/fob, QR, 관리자 원격 개방
  optional: 현 smartphone BLE scan 방식은 편의 채널로만 유지
```

현재 AJ-SR04T/ToF는 “승인 뒤 문을 여는 두 번째 관문”이 아니라 **접근 세션을 시작하는
presence trigger**로 이동한다. false positive는 인증 창만 열 뿐 relay를 켜지 않으므로
안전 영향이 작다.

### 6.3 정상 출입 시퀀스

```text
IDLE
→ 센서가 접근 감지
→ AUTH_WINDOW(session_id, nonce, 짧은 timeout)
→ reader가 NFC/Wallet/fob 자격 수신
→ controller가 nonce·door_id·counter를 포함한 proof를 로컬 검증
→ 로컬 ACL의 active/version/expiry 확인
→ AUTHORIZED
→ relay one-shot
→ PASSAGE/COOLDOWN
→ IDLE
→ 결과를 로컬 queue에 저장하고 Backend로 비동기 업로드
```

Backend가 내려가도 유효한 캐시 자격은 정책상 허용된 offline window 동안 출입한다.
네트워크가 복구되면 ACL 버전, 회수 목록, 감사 로그를 동기화한다. offline 허용 기간은
보안과 가용성의 정책 결정이며 예시로 24시간을 제안할 수 있지만 운영자가 확정해야 한다.

### 6.4 모바일의 축소된 책임

| 유지 | 제거 |
|---|---|
| 최초 사용자 등록/관리자 승인 | 상시 foreground service |
| 기기별 키 생성·보안 저장 또는 Wallet pass 발급 | background location/GPS 요구 |
| 자격 갱신·회수 상태 표시 | 상시 BLE scan/monitoring/ranging |
| 출입 기록·문 상태 표시 | RSSI EMA·화면 OFF 우회 |
| 사용자가 누르는 원격 개방 UI | 모바일 cooldown/출입 세션 판정 |
| 선택적 진단 | 문 앞 Pre-arm REST 필수 호출 |

앱이 삭제·강제 종료·절전 제한 상태여도 NFC Wallet/물리 fob 중 하나는 독립적으로
동작해야 한다. 앱은 자격의 관리 도구이지 실시간 출입 오케스트레이터가 아니다.

## 7. 인증·데이터 계약 재설계

### 7.1 자격

- 사용자/기기마다 고유 key pair 또는 고유 secret을 발급한다.
- 공통 APK API key와 임의 문자열 `device_id`를 사용자 인증으로 사용하지 않는다.
- 가능한 경우 Android Keystore, Wallet/secure element, secure fob에 private material을
  저장한다.
- Door Controller에는 검증용 public key 또는 최소 권한 파생 key만 둔다.

### 7.2 replay 방지

매 접근마다 controller가 새 nonce와 `session_id`를 만든다. 자격 증명은 최소한 다음을
포함해 서명/MAC한다.

```text
credential_id | door_id | session_id | nonce | counter/expiry
```

controller는 nonce 1회 사용, counter 단조 증가 또는 짧은 expiry를 확인한다. 고정 UUID,
BLE MAC, NFC UID만으로 문을 열지 않는다.

### 7.3 ACL과 회수

- Backend는 서명된 ACL snapshot 또는 증분 목록을 발행한다.
- controller는 `acl_version`, 발급 시각, expiry, 서명을 검증한 뒤 원자적으로 교체한다.
- 회수는 MQTT/push 형태로 빠르게 전파하되, MQTT가 끊겨도 다음 정기 pull에서 수렴한다.
- offline window가 지나면 정책에 따라 fail-closed 또는 경비/관리자 fallback으로 전환한다.

### 7.4 명령·결과 상관관계

원격 개방을 포함한 모든 세션은 같은 `session_id`를 사용한다.

```text
command accepted
→ credential verified / denied(reason)
→ relay on
→ relay off
→ passage complete / timeout
```

Backend의 성공 응답은 broker PUBACK이 아니라 controller의 해당 상태 ACK를 기준으로 한다.
broker endpoint는 명시된 단일 logical cluster로 고정하고 임의 후보 순회를 제거한다.

## 8. 단계적 전환안

이 절은 구현 순서 제안이며 이번 분석에서 코드는 변경하지 않는다.

### Phase 0 — 현 구조의 사실 확정

- 첨부 로그와 같은 실패 건에서 `rangingCallbackCount`, 빈 callback, packet count,
  raw/EMA RSSI, screen state, POST start를 한 `session_id` 타임라인으로 수집한다.
- Target raw advertising UUID/interval을 별도 scanner로 캡처한다.
- `-6/0/+3/+9 dBm`, 화면 ON/OFF, 손/주머니를 교차 시험해 RF와 생애주기를 분리한다.
- 이 단계의 목적은 현 앱을 영구 보강하는 것이 아니라 전환 전 기준 성공률을 얻는 것이다.

### Phase 1 — 책임 경계 정리

- 출입 session/cooldown/anti-passback의 유일한 소유자를 Target으로 정의한다.
- Target ACK와 `session_id`를 도입하고 Backend는 실제 ACK를 성공 기준으로 사용한다.
- 모바일 remote/local override를 제거하고 Backend 정책 버전은 표시만 하게 한다.
- current smartphone BLE 경로는 `legacy_convenience` 채널로 명시한다.

### Phase 2 — 로컬 인증 PoC

- 접근 센서가 `AUTH_WINDOW`를 시작하게 한다.
- 우선 NFC card/fob 또는 secure BLE fob 한 종류로 로컬 challenge-response를 검증한다.
- Backend down, broker down, 인터넷 차단에서도 캐시 자격으로 relay가 정상 작동하는지
  검증한다.

### Phase 3 — phone 자격과 fallback

- Android는 NFC HCE 또는 system wallet 경로를 검토한다.
- iPhone을 지원하면 Apple Wallet NFC entitlement/reader 요건을 먼저 확인하고,
  불가능하면 Wallet QR + fixed scanner를 사용한다.
- phone hands-free BLE를 유지하더라도 실패 시 NFC/fob로 즉시 전환되게 한다.

### Phase 4 — 운영 전환

- signed ACL, 회수, offline expiry, audit queue를 운영화한다.
- 모바일 BLE 성공률이 아니라 전체 자격 채널 합산 성공률을 SLO로 관리한다.
- 충분한 병행 운영 뒤 mobile background scan을 정상 출입의 필수 경로에서 제거한다.

## 9. 제안 합격 기준

아래 값은 구현 완료 사실이 아니라 설계 검증을 위한 제안 기준이다.

| 시험 | 제안 기대 결과 |
|---|---|
| 앱 force-stop/삭제 | NFC Wallet 또는 fob 출입 성공 |
| 화면 OFF·주머니 | fob 자동 출입 또는 NFC tap 성공; 앱 scan 불필요 |
| WAN/NAS/DB/MQTT 24시간 차단 | 정책상 유효한 cached credential 출입 성공, 로그 queue 보존 |
| 회수된 credential | online 즉시, offline은 정의된 최대 회수 지연 안에 거부 |
| 광고/APDU replay | nonce/counter 불일치로 거부 |
| 중복 접근 | 한 physical passage에 relay 1회 |
| controller reboot | relay 기본 OFF, ACL 무결성 검증 후 서비스 복귀 |
| relay ON 중 firmware block | 기존 one-shot fail-safe로 설정 시간 안에 OFF |
| 100회 반복 | 실패 원인이 session_id와 reason code로 전부 추적 가능 |

운영 목표 예시는 로컬 credential 검증 p95 1초 이내, relay 명령 p95 1.5초 이내,
유효 credential 100회 연속 성공이다. 실제 문/센서/fob 하드웨어 측정 뒤 확정한다.

## 10. 의사결정이 필요한 항목

1. **UX 우선순위:** 완전 hands-free가 필수인가, phone tap을 허용하는가.
2. **추가 자격 하드웨어:** secure BLE fob, NFC reader/card, QR scanner 중 허용 범위.
3. **iPhone 지원:** 초기 범위인지, Android 전용 PoC 이후인지.
4. **offline 정책:** Backend 단절 중 허용 시간과 회수 최대 지연.
5. **안전 fallback:** 물리 키, 퇴실 버튼, 관리자 원격 개방의 우선순위.

신뢰성을 최우선으로 한 기본 선택은 **secure BLE fob 자동 통과 + NFC/Wallet tap
fallback + Door Controller 로컬 ACL**이다. 추가 물리 자격을 허용할 수 없고 phone-only가
필수라면 **NFC/Wallet tap + QR fallback**이 다음 선택이다. 현재 방식의 smartphone
background BLE는 어느 경우에도 유일한 출입 수단으로 두지 않는다.

## 11. 외부 플랫폼 근거

- [Android BLE background communication](https://developer.android.com/develop/connectivity/bluetooth/ble/background): process가 없을 때 filtered `PendingIntent` scan 또는 Companion Device API 사용을 안내한다.
- [Android foreground service background-start restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start): Android 12+ background start 제한과 예외를 설명한다.
- [Android power/background restrictions](https://developer.android.com/topic/performance/background-optimization): restricted 상태와 OEM별 제약을 설명한다.
- [Android HCE overview](https://developer.android.com/develop/connectivity/nfc/hce): reader tap이 HCE service를 시작하는 구조와 화면 OFF/Secure NFC 조건을 설명한다.
- [Apple Core Bluetooth background processing](https://developer.apple.com/library/archive/documentation/NetworkingInternetWeb/Conceptual/CoreBluetooth_concepts/CoreBluetoothBackgroundProcessingForIOSApps/PerformingTasksWhileYourAppIsInTheBackground.html): background scan/advertising의 coalescing, UUID overflow, 주기 저하와 process 종료 한계를 설명한다.
- [Apple Wallet NFC pass](https://developer.apple.com/documentation/walletpasses/pass/nfc-data.dictionary): NFC pass의 암호 payload와 entitlement 요건을 설명한다.

## 12. 2026-08-01 범위 결정 — 추가 자격 하드웨어 보류

사용자 결정에 따라 secure BLE fob, NFC reader/card, QR scanner 등 추가 자격 하드웨어는
현재 구현 범위에서 보류한다. 이에 따라 이번 소프트웨어 전환은 Android OS-managed BLE
wake, native GATT credential worker, ESP32-C6 local challenge-response와 ACL을 중심으로
진행한다.

이 결정은 force-stop/OEM restricted 상태까지 자동 출입을 보장한다는 뜻이 아니다.
해당 상태는 사용자 동작 기반 fallback을 제공하고, 구현 상세·병렬 작업·전환 gate는
[mobile_hardwareless_implementation_plan.md](mobile_hardwareless_implementation_plan.md)를
기준으로 한다.
