# 설치·서비스 매뉴얼 / Installer and service manual

문서 버전: **0.3.0-rc.1** · 제품 기준: `e42d1f417a555b17d7476522aa48f7e4d72306b7`<br>
대상: 설치자·서비스 기술자 · 상태: **software 계약 반영; 모든 현장 walkthrough와 규제 승인 pending**

## 1. 안전 경계

- 작업 전 문과 relay 전원을 격리하고 현장 전기·화재·자동문 규정, relay 접점 정격과 문 제조사 지침을 따른다.
- ESP32-C6 GPIO는 3.3V logic이다. 5V ECHO, relay coil, mains/door power를 GPIO에 직접 연결하지 않는다.
- 설치자는 운영자 credential, production signing key, 관리자 session을 공유받지 않는다.
- 문서, build, host tests는 relay polarity, RF, sensor, bootloader, power-cut rollback 또는 사람 안전을 증명하지 않는다.
- 예상 밖 relay 활성, rail 변동, reset, 발열, 연기, 통신 중복이 보이면 즉시 전원을 차단하고 trial을 무효화한다.

## 2. 기준 BOM·배선

| 기능 | 기준 | 설치 확인 | 금지 |
|---|---|---|---|
| MCU | ESP32-C6-DevKitC-1, RISC-V, 3.3V | board label, exact board/layout artifact | Xtensa ESP32 artifact 사용 |
| 센서 | 현재 AJ-SR04T/JSN-SR04T 계열 | TRIG GPIO10 `PIN_TRIG`, ECHO GPIO11 `PIN_ECHO` | 과거 VL53L0X GPIO6/7 또는 GPIO21/22 배선 |
| ECHO | 측정 후 3.3V 이하 | 전원 OFF continuity, 분배기/level shifter, powered high-voltage trace | 5V ECHO를 GPIO11에 직결 |
| relay IN | GPIO3, `RELAY_ACTIVE_LOW=true` 가정 | 점퍼 L/H, idle/active voltage, High-Z OFF를 실측 | GPIO4/5/8/9/15/17–20 사용 |
| relay 출력 | 자동문에는 승인된 무전압 접점 | COM/NO/NC, 접점 정격, 문 controller manual | coil·mains를 MCU rail에서 직접 구동 |
| 전원 보호 | MCU/sensor/relay 부하와 ground 설계 검토 | 별도 전원/광절연, fuse, flyback, 역극성·brownout trace | 보호 소자 없는 inductive load |

GPIO6/7은 현재 센서 핀이 아니지만 부팅 bus-clear 코드가 남아 있어 비워 둔다. relay OFF는 현재 `INPUT` High-Z이므로 module pull-up, optocoupler와 역전류를 실측해야 한다. 상세 기준은 [핀 매핑](../wiki/pin_mapping.md)과 [relay 문제 해결](../wiki/relay_troubleshooting_guide.md)을 따른다.

## 3. Secure provisioning

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| manufacturing owner + reviewer | exact signed firmware, board/layout, isolated station | flash/provision 시작 | artifact SHA, board, source commit 일치; debug secret 출력 0 | PlatformIO build, protected firmware producer | provisioning record + firmware digest **PENDING** | station window | flash 1회; mismatch 0회 | release/hardware security owner |
| security owner | unique Target ID/password, broker CA/hostname, command signer, ACL/recovery credentials | encrypted credential injection | Target username=Target ID, unique topic ACL, secret length/format 통과 | `config.h`, `MqttManager`, `WifiManager` | credential inventory의 opaque ID, no plaintext | 15분 작업 목표 | 입력 교정 1회 | key custody owner; `secrets.h` commit 금지 |
| hardware security owner | production candidate, approved eFuse plan | Secure Boot v2·release flash encryption·NVS encryption·anti-rollback·debug lock | eFuse/readback가 policy와 일치 | `security/target-production-policy.json` | eFuse report + distinct reviewer **PHYSICAL PENDING** | irreversible 작업 window | 자동 0회 | 불일치 board 격리/RMA, 임의 fuse 재작업 금지 |
| installer | credentialed Target, verified time/CA | first MQTTS connect | non-1883 verified TLS, per-Target `/boot` event, monotonic boot count | `MqttManager.cpp`, backend boot registry | TLS/boot log **PHYSICAL/OPS PENDING** | socket 15초 source 값 | 5초→30초 최대 2회 | broker/Target owner; plaintext·insecure fallback 금지 |

## 4. 전원 투입 전·후 시운전

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| installer | mains/door 격리, approved wiring | continuity·polarity·rail 측정 | short 없음, GPIO 보호, relay contact/coil 분리 | wiring plan, `config.h` | timestamped photo/meter trace | 작업 window | 재측정 1회 | safety owner; 불명확하면 전원 금지 |
| installer + safety observer | emergency stop, relay contact는 door에서 분리 | Target만 power-on | boot 중 GPIO3 idle/High-Z, relay contact 변화 0, stable 3.3V | `RelayController`, `main.cpp` | boot/rail/GPIO waveform **PHYSICAL PENDING** | boot 60초 | power cycle 1회 | unexpected active/reset이면 즉시 차단 |
| sensor owner | relay OFF, 20–200cm test jig, ECHO 보호 | 거리 point와 obstruction 입력 | valid distance 또는 explicit timeout/out-of-range; 0을 성공으로 사용 안 함 | `UltrasonicSensor.cpp`, `config.h` | raw readings와 fixture geometry | reading 30ms source pulse timeout; 500ms 운영 목표 미검증 | point별 최대 3회 | repeated fault면 firmware/safety owner |
| installer + operator | relay dry contact만 안전 test load 연결 | 승인된 1회 open command | relay LOW active, 1초 hold, OFF/High-Z, 3초 cooldown; event와 waveform 일치 | `TargetAccessFsm`, `GattServer`, relay controller | boot/session/event + waveform **PHYSICAL PENDING** | hold 1초, cooldown 3초 source 값 | effect 0회 자동 | latch/duplicate면 전원 차단, RELAY-G owner |
| installer + operator | 실제 door 연결, safety zone clear | Issue #54 planned trials | 센서/relay/door event와 physical effect correlation | physical gate plan | 100-run ledgers, approvals **PENDING** | plan 조건 | plan 이외 0회 | trial 중 unsafe 관찰 즉시 stop |

NAS 검증 배포는 실기기 시험 준비 단계다. 설치자는 배포된 API의 `/live`가 process 응답만 뜻하고 `/ready`가 DB schema `007`, bounded broker probe, runtime/control secret, mTLS proxy, ACL runtime, legacy pre-arm retirement와 exact build SHA를 모두 확인한다는 차이를 기록한다. 어느 응답도 Target·relay·sensor 정상이나 production 승인을 의미하지 않는다.

## 5. BLE·offline·local recovery 시운전

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| mobile installer | 승인 Samsung build, app credential, Target | foreground/screen-off/reboot/kill matrix | 100개 eligible trial의 wake→auth→effect/denial state | native wake/GATT | SAMSUNG-WAKE-100 **PENDING** | gate plan | scenario별 plan | mobile/OEM owner |
| operator | DNS/MQTT/backend unavailable, local credential | authenticated local station `/recovery/enable-ap` | 10분 WPA2 AP+STA window, station credentials 보존 | `WifiManager.cpp` | auth/timeout/device log **PHYSICAL PENDING** | AP 10분 source 값 | enable 1회 | unauth portal을 만들지 말고 recovery owner |
| release owner | AP 또는 station recovery, signed manifest, safe state | `/recovery/manifest`와 `/recovery/firmware` | remote OTA와 동일 size/hash/image/inactive-slot 검증 | `WifiManager`, `OtaManager` | OTA-G4 evidence **PHYSICAL PENDING** | upload/change window | install 0회 | 실패 시 old slot 유지, 반복 upload 금지 |

## 6. OTA·rollback 서비스

Target은 부팅 60초 후, 이후 6시간마다 HTTPS manifest를 확인하고 실패 시 15분 뒤 bounded retry한다. signed `ota_check`는 추가 trigger이며 유일 경로가 아니다. image는 inactive slot에만 쓰고 exact size/hash/ESP image를 검증한다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| release owner | safe state, signed Ed25519 manifest, exact board/layout, N/N-1 overlap | canary OTA | `WAIT_SAFE_STATE`→download/verify→reboot→`HEALTH_WINDOW` | `OtaManager.cpp` | exact manifest/artifact/boot IDs | safe wait는 code reason, health deadline 120초 | install 0회 | wait/verify failure이면 firmware/release owner |
| Target | pending image, last-known-good slot | health sampling | safe state+network/recovery+heap가 30초 연속이면 valid; gap>1초면 timer reset | `OtaManager` health state | sampled health ledger **PHYSICAL PENDING** | 120초 deadline | valid mark 0회 retry | deadline이면 automatic rollback 1회 |
| installer | power-cut plan과 spare recovery path | OTA-G1..G4 interruption | old slot boot 또는 authenticated recovery; credential/ACL/NVS 보존 | ESP-IDF rollback/local recovery | power/boot trace **PHYSICAL PENDING** | gate plan | interruption은 plan 횟수만 | boot loop/unknown이면 전원 안정화 후 recovery owner |

## 7. 장애 대응

| Reason | Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|---|
| `RELAY_UNEXPECTED_ACTIVE` / `RELAY_POLARITY_UNKNOWN` | installer+safety observer | isolation 가능 | 즉시 relay/door 전원 차단, waveform 보존 | OFF 격리, 문 열림 success 없음 | relay/main/config | photo+meter **PHYSICAL PENDING** | 감지 후 5초 내 차단 목표 | 자동 0회, 격리 후 polarity 측정 1회 | safety/incident owner; 재배선 승인 필요 |
| `TARGET_OFFLINE` / `TLS_VERIFY_FAILED` | service owner | time/CA/rail 확인 | DNS→time→CA→hostname→credential 순서 점검 | verified online 또는 offline 유지 | MQTT/WiFi | TLS/boot log **PHYSICAL PENDING** | connect 15초 | 5초→30초 2회 | broker/PKI/Target owner; verifier 완화 금지 |
| `SENSOR_TIMEOUT` / `SENSOR_OUT_OF_RANGE` | sensor owner | relay OFF, safe jig | ECHO voltage·geometry·raw pulse 확인 | fault와 raw reading; commissioning 중지 | ultrasonic/config | pulse trace **PHYSICAL PENDING** | pulse 30ms | 측정 최대 3회 | firmware/safety owner; threshold 원격 완화 금지 |
| `OTA_HEALTH_TIMEOUT` / `BOOT_ROLLBACK` | release owner | old slot 확인 | boot reason/slot/digest 캡처 | rollback 또는 recovery; health 전 success 없음 | OTA/bootloader | boot ledger **PHYSICAL PENDING** | 120초 | install 0회, rollback 1회 | release/incident owner |
| `duplicate_uncertain` | operator | physical scene safe | session/nonces/event correlation | effect 불명 유지, 새 effect 실행 0 | Target replay ledger/GATT | causal event **PHYSICAL PENDING** | 15초 목표 | 자동 0회 | physical + security owner |

## 8. 유지보수·RMA·폐기

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|
| service technician | maintenance approval, backup, exact replacement | board/sensor/relay 교체 | old component quarantine, new identity/provisioning, full commissioning reset | #50/#52 lifecycle | RMA ID, before/after digest, photos | change window | 교체 1회 | hardware/security owner |
| credential owner | lost/RMA reason | Target/mobile credential revoke | backend revoke, broker ACL removal, Target denial pending/confirmed | ACL/broker | audit + denial event | 60초 목표 | same request 1회 | Target/platform owner |
| privacy owner | retention/legal hold | NVS/data erase or quarantine | deletion scope, exception, method, reviewer | #52 privacy | redacted destruction record **OPS PENDING** | approved window | erase 0회 자동 | privacy/security owner |
| installer + regulator | completed physical gates and local law | final handover | wiring diagram, emergency procedure, training, sign-off | Issue #54 | operator/regulatory approvals **PENDING** | project window | 0회 | production authorization owner |

서비스 기록에는 actor, opaque Target/door ID, exact artifact digest, 전/후 state, reason/event, 계측기·firmware version, rollback plan, 별도 reviewer와 만료일을 남긴다. secret, private key, raw MAC, tenant/unit과 개인 주소는 남기지 않는다.
