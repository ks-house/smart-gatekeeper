# 설치·서비스 매뉴얼 / Installer and service manual

문서 버전: **0.1.0-baseline** · 기준 커밋: `b246aff9698ccbcbcd864f99aab63654cce2cc78`<br>
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

| 증상 | 즉시 조치 | 금지 조치 | 증거/owner |
|---|---|---|---|
| relay가 idle에서 동작 | 전원 차단, 기계식 안전 확보, GPIO/점퍼 측정 | firmware 재플래시로 덮기 | 사진·meter·board digest; installer **PENDING** |
| Target offline | 전원·Wi-Fi·TLS 상태를 분리 확인 | 인증 검증을 끄거나 `setInsecure()` 사용 | boot ID/verified logs; #50 **PENDING** |
| OTA 후 부팅 불가 | last-known-good slot과 현장 recovery 경로 보존 | single-slot 덮어쓰기 | power-loss/rollback event; #50 physical **PENDING** |
| 센서 반복 오작동 | commissioning 중지, 거리·배선·전원 확인 | threshold를 근거 없이 원격 변경 | test runs + config audit; #52 **PENDING** |

## 서비스 기록

모든 변경에는 actor, 대상 opaque ID, 입력 artifact digest, 전/후 state, observable event, rollback plan, reviewer와 만료일을 기록한다. 원본 secret·private key·raw MAC·tenant/unit은 기록하지 않는다. 현장 validation은 [제품 역분석·갭 등록부](product_gap_register_v1.md)의 physical gate를 갱신해야 한다.
