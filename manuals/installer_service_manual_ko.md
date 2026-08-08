# 설치·서비스 매뉴얼 / Installer and service manual

문서 버전: **0.1.2-contract-loop** · 기준 커밋: `cb8b2efe92c771e8c139fcc1ba749d9dcff29f5f`<br>
대상: 설치자·서비스 기술자 (installer/service technician) · 상태: **모든 현장 walkthrough pending**

## 안전과 책임 경계

전원을 차단하고 현장 전기 규정·릴레이 정격·문 제조사 지침을 따른다. 설치자는 운영자 자격이나 관리자 force-open 권한을 공유하지 않는다. 문서·host build 통과는 GPIO, relay, 전원, bootloader, OTA, Samsung/OEM 실기기 승인으로 간주하지 않는다.

## 기준 배선

| 항목 | 기준 / Baseline | 확인 방법 |
|---|---|---|
| MCU | ESP32-C6-DevKitC-1, 3.3V logic, RISC-V | board label와 artifact board 확인 |
| I²C | SDA GPIO6, SCL GPIO7, 400 kHz 명시 | `Wire.begin(6, 7, 400000UL)` source trace |
| Relay IN | authoritative GPIO3 | continuity/logic measurement **PENDING** |
| 금지 핀 | GPIO4,5,8,9,15(strapping), 17–20(USB/UART) | wiring photo + review |
| ToF/센서 | 실제 BOM·pin_mapping에 정의된 부품만 연결 | `wiki/pin_mapping.md`, physical test **PENDING** |
| Relay polarity | `RELAY_ACTIVE_LOW=true`는 점퍼 L 가정일 뿐 | 점퍼 위치·idle output을 현장에서 확인 |

## 설치·시운전 단계

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact |
|---|---|---|---|---|---|
| 설치자 | 전원 차단, 승인된 BOM/배선도 | wiring·ground·level shifting·flyback 연결 | continuity, polarity, isolated power 측정값 | `wiki/pin_mapping.md`, `include/config.h` | 사진, meter trace, installer sign-off **PENDING** |
| 설치자 | signed release artifact, board/layout 일치 | ESP32-C6 flash/provision | boot ID/target identity가 생성되고 debug secret이 노출되지 않음 | `src/`, `include/secrets.h.example`, #50 | artifact digest + provisioning record **PENDING** |
| 설치자 | Wi-Fi/MQTT TLS CA와 target credential 승인 | network/provisioning 입력 | verified TLS online event; plaintext/rogue CA fail-closed | `src/MqttManager.cpp` | TLS negative tests + target log **PENDING** |
| 설치자 | relay idle state와 센서 위치 확인 | power-on/boot/idle | relay가 안전한 OFF/High-Z인지 측정; 문이 열리지 않음 | `src/main.cpp`, relay code | repeated meter/relay run **PHYSICAL PENDING** |
| 설치자 | commissioning actor와 emergency stop | authorized test passage | `armed/opening/confirmed` event와 물리 relay event 상관 | Target FSM/GATT/MQTT | 20+ runs and safety sign-off **PENDING** |
| 서비스 기술자 | maintenance window, backup, rollback artifact | firmware/config change | pre/post health, event IDs, rollback path | `src/OtaManager.cpp`, OTA contract | exact artifact + rollback report **PENDING** |
| 서비스 기술자 | RMA authorization, data deletion plan | quarantine/return device | credentials revoked, NVS/tenant data handling recorded | #49/#52 | redacted RMA record **PENDING** |

## 전기·기계 점검

- GPIO 3.3V가 relay input 정격과 맞는지, 필요한 level shifting을 사용했는지 확인한다.
- relay coil 전원과 MCU 전원을 분리하고 flyback/공통 접지/접점 정격을 확인한다.
- HIGH/LOW polarity를 가정하지 말고 점퍼와 실제 idle/active 전압을 측정한다. High-Z OFF가 회로에 미치는 영향도 기록한다.
- 센서가 문 움직임·사람 통행을 안전하게 구분하는지 단일 성공이 아닌 반복 시험으로 확인한다.
- 전기·화재·문 안전 규정 sign-off가 없으면 commissioning을 완료하지 않는다.

## 장애·현장 교체

아래 값은 현장 안전을 위한 문서 계약 목표이며 구현·SLO·물리 증거가 완료되었다는 뜻이 아니다. `reason`은 observable state/event와 같은 값으로 기록되어야 하고, 재시도 한도를 넘으면 자동으로 성공 처리하지 말고 escalation으로 전환한다.

| Actor | Preconditions | Input | Observable output | Code/API owner | Evidence artifact | Reason | Timeout | Bounded retry | Escalation |
|---|---|---|---|---|---|---|---|---|---|
| installer / safety owner | 전원·문 상태를 안전하게 격리하고 relay 점퍼·GPIO 배선을 확인할 수 있음 | idle에서 relay가 활성화된 사진, meter/GPIO level, board digest | 즉시 relay 전원 차단 후 `RELAY_UNEXPECTED_ACTIVE` 또는 `RELAY_POLARITY_UNKNOWN` 상태와 event ID를 표시; 문은 열림 성공으로 처리하지 않음 | `src/main.cpp`, `src/RelayController.cpp`, `include/config.h`, `wiki/pin_mapping.md` | 사진·meter trace·board digest·installer sign-off **PENDING** | `RELAY_UNEXPECTED_ACTIVE` / `RELAY_POLARITY_UNKNOWN` | 감지 후 **5초 이내** 전원 차단; 측정 계약 목표이며 구현 증거 **PENDING** | 자동 재시도 **0회**; 안전 격리 뒤에만 polarity 측정 **1회** | installer가 safety/incident owner와 관리자에게 즉시 escalation; 재배선·재플래시 전 현장 승인 필요 |
| installer / service owner | Target 전원·Wi-Fi·TLS를 각각 확인하고 인증서/시간이 검증됨 | boot ID, connectivity health, TLS verification log, offline event | **10초** health window 안에 `online` 또는 `TARGET_OFFLINE`과 reason/event ID를 표시; `setInsecure()`로 우회하지 않음 | `src/MqttManager.cpp`, `src/WifiManager.h`, `include/MqttManager.h`, #50 | boot ID·verified TLS log·offline fault test **PENDING** | `TARGET_OFFLINE` / `TLS_VERIFY_FAILED` | health 요청 **10초**; TLS socket 계약은 `src/MqttManager.cpp`의 15초 설정과 정합성 검토 **PENDING** | **최대 2회**, 5초→30초 backoff; 소진 후 재시도 중지 | service/on-call과 #50 owner에 connectivity, cert, target ID를 redacted bundle로 escalation; 인증 검증 완화 금지 |
| installer / release owner | signed manifest, dual-slot 및 last-known-good bootable slot이 확인되고 Target이 safe state임 | artifact digest/certificate, install result, reboot/health/rollback event | `install→reboot→health`가 **60초** 안에 확인되지 않으면 `OTA_HEALTH_TIMEOUT` 또는 `BOOT_ROLLBACK`을 표시하고 이전 slot을 유지; 성공은 health event 전 선언하지 않음 | `src/OtaManager.cpp`, `include/OtaManager.h`, `wiki/ota_reliability_contract.md`, #23/#50 | exact artifact digest·boot ID·health/rollback event·power-loss walkthrough **PENDING** | `OTA_HEALTH_TIMEOUT` / `BOOT_ROLLBACK` | reboot 후 health window **60초**; target contract 및 physical proof **PENDING** | install 재시도 **0회**; health 실패 시 **rollback 1회**만 허용, 반복 flash 금지 | release owner와 incident/on-call에 slot, digest, boot reason을 escalation; physical recovery 승인 전 작업 중지 |
| installer / sensor owner | commissioning 중지, 센서 전원·배선·거리 범위를 확인하고 relay가 안전 OFF임 | timestamped readings, timeout flag, range/config audit | 읽기 **500ms** 안에 유효 측정이 없거나 3회 연속 fault면 `SENSOR_TIMEOUT`, `SENSOR_OUT_OF_RANGE`, 또는 `SENSOR_REPEATED_FAULT`; commissioning을 중지하고 relay를 열림 성공으로 처리하지 않음 | `src/UltrasonicSensor.cpp`, `include/UltrasonicSensor.h`, `src/main.cpp`, `include/config.h` | 3회 이상 raw reading/timeout trace·wiring photo·config audit **PENDING** | `SENSOR_TIMEOUT` / `SENSOR_OUT_OF_RANGE` / `SENSOR_REPEATED_FAULT` | reading당 **500ms**, fault 판정 window **3회**; 보드별 실제 timeout은 source/test로 확정 **PENDING** | 재측정 **최대 3회**; 소진 후 threshold 원격 변경 및 자동 재시도 금지 | installer가 sensor/firmware owner와 safety/incident owner에게 readings·배선·전원 증거로 escalation |

## 서비스 기록

모든 변경에는 actor, 대상 opaque ID, 입력 artifact digest, 전/후 state, observable event, rollback plan, reviewer와 만료일을 기록한다. 원본 secret·private key·raw MAC·tenant/unit은 기록하지 않는다. 현장 validation은 [제품 역분석·갭 등록부](product_gap_register_v1.md)의 physical gate를 갱신해야 한다.
