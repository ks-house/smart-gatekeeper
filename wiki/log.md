# wiki/log.md — Chronological Change Log
> Format: `## [YYYY-MM-DD] <type> | <description>`
> Append only. Never edit past entries.

---

## [2026-06-26] compile | wiki 초기 뼈대 생성 (schema.md, index.md, log.md)

- `schema.md` 생성: 디렉토리 레이아웃, 네이밍 컨벤션, 코드 스타일, 워크플로우 정의
- `wiki/index.md` 생성: 4개 카테고리 + Quick Reference 테이블
- `wiki/log.md` 생성: 본 파일

## [2026-06-26] compile | env_setup.md 생성 — 개발 환경 세팅 가이드

- PlatformIO IDE 기반 워크플로우 확정
- ESP32 Arduino 프레임워크 boilerplate `platformio.ini` 내용 정의
- VL53L0X 라이브러리 선택: `pololu/VL53L0X` (C++ native, no HAL dependency)
- 필수 라이브러리 목록 확정

## [2026-06-26] compile | pin_mapping.md 생성 — I2C 및 릴레이 핀 매핑

- ESP32 기본 I2C 핀 확정: SDA=GPIO21, SCL=GPIO22
- 릴레이 제어 핀: GPIO26 (Active-LOW 가정, 확인 필요)
- 안전 배선 주의사항 기록

## [2026-06-26] code | ToF 센서 드라이버 스켈레톤 생성 (src/ToFSensor.h, .cpp)

## [2026-06-26] code | 릴레이 드라이버 스켈레톤 생성 (src/RelayController.h, .cpp)

## [2026-06-26] code | Step1_ToF_Test.cpp, Step1_Relay_Test.cpp 예제 스케치 생성

## [2026-06-26] ingest | raw/ST_VL53L0X_Specs.md — VL53L0X 데이터시트 핵심 스펙 컴파일

- 소스: STMicroelectronics DS11486 + Pololu Arduino Library GitHub
- 전기 사양, I²C 타이밍, 측정 모드, Pololu API 요약, ESP32 특이사항 포함
- 다중 센서 XSHUT 주소 할당 패턴 기록

## [2026-06-26] fix | ToFSensor.cpp — 데이터시트 기반 3가지 버그 수정

- Bug #1: `Wire.begin(21, 22)` → `Wire.begin(21, 22, 400000UL)` (100kHz→400kHz, 응답 지연 해소)
- Bug #2: `sensor.setTimeout(500)` 누락 추가 (I2C 단선 시 무한 블로킹 방지)
- Bug #3: 반환값 65535 sentinel 미처리 → 명시적 체크 추가 (out-of-range 오류)

## [2026-06-26] lint | 위키 전체 링크 및 일관성 검사

- index.md: raw/ 카테고리 추가, Quick Reference 항목 3개 추가
- 깨진 링크: 없음
- 모순 정보: 없음

## [2026-06-27] ingest | raw/Espressif_ESP32C6_BoardSpec.md — ESP32-C6 보드 사양 컴파일

- 아키텍처 비교 (Xtensa vs RISC-V), GPIO 사용 가능 여부 분류
- 스트래핑 핀(GPIO4/5/8/9/15) 및 예약 핀(GPIO17-20) 사용 금지 목록
- I2C 권장 핀: GPIO6(SDA), GPIO7(SCL)
- pioarduino 플랫폼 필수 이유 기록

## [2026-06-27] fix | ESP32 → ESP32-C6 전면 마이그레이션 (CRITICAL)

- `platformio.ini`: board=esp32dev → esp32-c6-devkitc-1, platform → pioarduino
  `-DARDUINO_USB_CDC_ON_BOOT=1` 및 `-DARDUINO_USB_MODE=1` 빌드 플래그 추가
- `include/config.h`: 핀 전면 수정
  - I2C SDA: GPIO21 → GPIO6
  - I2C SCL: GPIO22 → GPIO7
  - Relay IN: GPIO26 → GPIO3
  - XSHUT:   GPIO16 → GPIO10
- `src/ToFSensor.cpp`: Wire.begin() 핀 인자는 config.h 상수 사용으로 자동 반영

## [2026-06-27] compile | wiki/pin_mapping.md 전면 재작성 (ESP32-C6 기준)

- GPIO 사용 분류 다이어그램 추가
- 구/현재 핀 비교 테이블 추가
- Wire.begin() 명시 코드 스니펫 추가

## [2026-06-27] compile | schema.md — Hardware Constraints 및 Open Questions 업데이트

- Open Question #1 해소: ESP32-C6-DevKitC-1 확정
- Hardware Constraints 테이블 ESP32-C6 기준 재작성

## [2026-06-27] lint | 2차 위키 전체 검사

- index.md: Espressif_ESP32C6_BoardSpec.md 추가
- 깨진 링크: 없음
- 모순 정보: 없음 (구 GPIO21/22 레퍼런스 pin_mapping.md에서 완전 제거됨)

## [2026-06-27] ingest | raw/BOM_SmartGatekeeper_Step1.md — 구매 확정 BOM

- 7개 카테고리 부품 확정 (스페어 포함)
- 전압/전류 호환성 전수 검토 완료
- 주의사항 W1: 400홀 미니 브레드보드 공간 부족 가능 (C6 DevKitC-1이 보드 가득 채움)
- 주의사항 W2: 점퍼 와이어 M-M(수-수) 포함 여부 미확인

## [2026-06-27] compile | schema.md Open Question #2 조건부 해소

- 릴레이 모듈: Low/High Level Trigger 선택형 구매 확인
- 점퍼 "L" 위치 = Active-LOW → config.h `RELAY_ACTIVE_LOW=true` 유지
- 현장 점퍼 확인 후 최종 확정 필요

## [2026-06-27] compile | wiki/architecture.md BOM 테이블 업데이트

- 구매 확정 목록 기준으로 전면 교체

## [2026-06-27] lint | 3차 위키 전체 검사

- index.md: BOM raw 파일 추가
- 깨진 링크: 없음
- 모순 정보: 없음

## [2026-06-27] compile | AGENTS.md 생성 — 다중 에이전트 협업 지침

- `AGENTS.md` (프로젝트 루트): 전체 지침 (TL;DR, 워크플로우, 하드웨어, 코드 컨벤션, 에티켓)
- `.agents/AGENTS.md`: IDE 자동 로드용 핵심 규칙 압축본
- `schema.md` 디렉토리 레이아웃 업데이트 (AGENTS.md, .agents/ 추가)
- `wiki/index.md` Meta 카테고리에 두 AGENTS.md 링크 추가

## [2026-06-27] lint | 4차 위키 전체 검사

- 깨진 링크: 없음
- 모순 정보: 없음
- AGENTS.md ↔ schema.md ↔ index.md 상호 참조 일관성 확인

## [2026-06-27] fix | README.md 릴레이 핀 번호 정정 및 Git 커밋 준비

- `README.md`에서 릴레이 핀 번호가 `GPIO 23`으로 잘못 표기되어 있던 부분을 `config.h` 및 `wiki/pin_mapping.md`와 일치하도록 `GPIO 3`으로 수정.

## [2026-06-27] fix | src/ToFSensor.cpp — 에러 메시지 구 핀 번호 하드코딩 버그 수정

- `[ERROR]` 메시지에 구 ESP32 핀 번호 `(SDA=GPIO21, SCL=GPIO22)` 가 하드코딩되어 있어 실제 설정 `GPIO6/7` 과 불일치.
- → `Check wiring (SDA=GPIO6, SCL=GPIO7)` 으로 수정.

## [2026-06-27] compile | wiki/env_setup.md 전면 재작성 (ESP32-C6 + pioarduino 기준)

- 구 ESP32(esp32dev) 기준 `platformio.ini` 예제 코드를 실제 사용 중인 ESP32-C6 + pioarduino 설정으로 전면 교체.
- 3개 빌드 환경(`esp32c6`, `tof_test`, `relay_test`) 예제 모두 반영.
- 빌드 환경별 업로드 명령어 테이블 추가 (§5 신설).
- 첫 빌드 체크리스트 실제 출력 메시지에 맞게 업데이트.
- 별첨 A(Arduino IDE): v2.x→v3.x 요구사항, `USB CDC On Boot` 설정 필수 항목 추가.

## [2026-06-27] compile | wiki/hardware_test.md 합격 기준 메시지 실제 코드와 동기화

- Test #1 합격 기준: `VL53L0X initialized` → 실제 출력 `[INFO] ToFSensor: VL53L0X initialized. Continuous mode @ 100ms interval.` 으로 수정.
- Test #2 합격 기준: 실제 `main.cpp` 출력 포맷 `[Relay] ON (t=xxx ms)` 으로 수정.

## [2026-06-27] lint | 5차 위키 전체 검사 (전체 프로젝트 상세 분석)

- 분석 범위: 모든 src/, include/, wiki/, raw/, platformio.ini, schema.md, AGENTS.md
- 깨진 링크: 없음
- 모순 정보: 없음 (모든 핀 번호, 플랫폼 설정, 에러 메시지가 단일 진실 소스와 일치)
- Last updated 날짜 동기화: index.md, architecture.md, hardware_test.md → 2026-06-27

## [2026-07-24] test | VL53L0X 부품 도착 및 ESP32-C6 배선 완료

- 부품(VL53L0X ToF 센서) 실물 수령 확인
- 아래 4핀 물리 배선 완료 (브레드보드):
  - VL53L0X VCC  → ESP32-C6 3V3
  - VL53L0X GND  → ESP32-C6 GND
  - VL53L0X SDA  → ESP32-C6 **GPIO6**
  - VL53L0X SCL  → ESP32-C6 **GPIO7**
  - XSHUT: **미연결** (단일 센서 운용이므로 문제 없음)

## [2026-07-24] compile | wiki/pin_mapping.md — 배선 완료 상태 반영

- §2 I2C 테이블에 `상태` 열 추가 (배선 완료 ✅ / 미연결 ⬜ 표시)
- XSHUT 핀 미연결 안내 주석 추가
- Last updated: 2026-06-27 → 2026-07-24

## [2026-07-24] code | src/main.cpp — ToF 거리 측정 테스트 코드 재작성

- 기존 통합 데모/릴레이 코드 제거, ToF 단독 mm 거리 출력에 집중
- 핵심 구현:
  - `Wire.begin(PIN_SDA, PIN_SCL, 400000UL)` — GPIO6/7, 400kHz 명시
  - `sensor.setTimeout(500)` — init() 전 설정 (I2C 단선 블로킹 방지)
  - `sensor.startContinuous(POLL_MS)` — 연속 측정 모드
  - 65535 sentinel 및 `timeoutOccurred()` 이중 체크
  - `Serial.printf("[ToF] Distance: %4u mm\n", mm)` 출력 포맷
- 빌드 환경: `pio run -e tof_test -t upload` (`-DTEST_TOF_ONLY` 플래그)
- `config.h` 상수만 참조, 핀 하드코딩 없음

## [2026-07-24] test | 1차 플래싱 결과 — I2C 초기화 성공, VL53L0X init 결과 미확인

- 플래싱 성공, 시리얼 출력 확인:
  - `i2cInit(): sda=6 scl=7 freq=400000` ← I2C 초기화 ✅
  - 이후 출력 없음 (USB-CDC 타이밍 문제로 배너 유실, 또는 sensor.init() 블로킹)
- 원인 후보:
  1. USB-CDC: `delay(500)` 동안 모니터 미연결 → 배너 유실
  2. XSHUT 미연결 floating → 일부 저가 VL53L0X 모듈에서 LOW 유지 → 센서 리셋 상태 지속

## [2026-07-24] fix | src/main.cpp — USB-CDC 대기 + XSHUT 명시 + I2C 스캐너 추가

- `while(!Serial)` + 5초 타임아웃: USB-CDC 연결 전 출력 유실 방지
- `pinMode(PIN_TOF_XSHUT, OUTPUT); digitalWrite(PIN_TOF_XSHUT, HIGH)`: XSHUT floating 문제 해결
- I2C 스캔 함수 `i2cScan()` 추가: 0x29 응답 여부로 배선 문제 vs. 라이브러리 문제 구분
- `Serial.flush()` before `sensor.init()`: init 전 메시지 반드시 전송 보장

## [2026-07-24] test | 2차 테스트 — [5127ms] 타임스탬프로 USB-CDC 타이밍 문제 확인

- i2cInit 로그가 [5127ms]에 출력됨 → `while(!Serial)` 이 5000ms 풀 타임아웃 소진
  - USB-CDC DTR 신호가 늦게 올라와 Serial이 준비되지 않은 것으로 판단
- Wire.begin() 이후 코드 출력 없음 → XSHUT floating LOW 가능성 높음
  - 저가 VL53L0X 모듈: XSHUT 내부 풀업 저항 없음 → 미연결 = LOW = 센서 리셋 상태
  - sensor.init() 타임아웃 후 [FATAL] 출력됐으나 USB 버퍼 플러시 전 유실

## [2026-07-24] fix | src/main.cpp — USB-CDC/XSHUT/flush 3중 안정화

- Wire.begin()을 Serial.begin() 전으로 이동 (USB-CDC 안정화 유도)
- `logln()` 헬퍼 함수 추가: 모든 출력 후 `Serial.flush()` 강제 실행
- I2C 스캔 → 0x29 미응답 시 sensor.init() 호출 전 [FATAL] 분기 (배선 문제 조기 진단)
- 하드웨어 조치 안내: XSHUT → 3V3 직결 또는 GPIO10 → XSHUT 점퍼 배선 필요

## [2026-07-24] test | 3차 테스트 — [2027ms] 타임스탬프, Serial.begin 순서 수정 후에도 동일 현상

- i2cInit [2027ms] 확인 → Serial.begin() + delay(2000) + Wire.begin() 순서는 정상
- 그러나 Wire.begin() 이후 logln() (Serial.println 기반) 출력 여전히 미표시
- 결론: **Arduino Serial.println()이 ESP32-C6 USB-CDC에서 ESP-IDF stdout과 다른 버퍼 경로 사용**
  - ESP-IDF 로그 (i2cInit 등): `stdout` → USB-CDC FIFO 직접 기록 → 항상 표시
  - Arduino Serial.println(): 별도 CDC 래퍼 → 버퍼링/플러시 타이밍 불일치로 유실

## [2026-07-24] fix | src/main.cpp — Serial.println → printf/fflush(stdout) 전환 (최종 해결)

- `LOGF()` 매크로 정의: `printf(fmt "\n", ...) + fflush(stdout)`
- ESP-IDF stdout 경로 = i2cInit 로그와 동일 → 반드시 모니터에 출력됨
- **동작 확인: "굿" (2026-07-24 09:44 KST)**
- Wire.begin() 이전 배너, I2C 스캔, sensor.init() 결과 모두 정상 표시

## [2026-07-24] compile | wiki/hardware_test.md 업데이트 예정 (Test #1 결과 기록 필요)

- VL53L0X 단독 테스트 통과 여부 → hardware_test.md 결과 테이블에 기록 예정

## [2026-07-24] test | Test #1 합격 — VL53L0X ToF 단독 테스트 성공

- 배선: SDA=GPIO6, SCL=GPIO7, XSHUT=GPIO10, VCC=3.3V
- mm 단위 거리 정상 출력 확인 (`[ToF] Distance: xxxx mm`)
- 핵심 해결책:
  1. `Serial.println()` → `printf()+fflush(stdout)` 전환 (ESP32-C6 USB-CDC 특이사항)
  2. XSHUT 명시적 HIGH 구동 필수 (저가 모듈 floating LOW 문제)
- hardware_test.md Test #1 결과: 🟢 합격 기록

## [2026-07-24] fix | include/config.h — PIN_RELAY 변경: GPIO3 → GPIO23

- 계획: GPIO3 | 실제 배선: GPIO23 (사용자 확인)
- `config.h: constexpr uint8_t PIN_RELAY = 23;` 으로 수정
- 동시 업데이트: pin_mapping.md §3 릴레이 테이블, §4 배선 요약, §5 config.h 스니펫

## [2026-07-24] compile | wiki/pin_mapping.md — GPIO23 릴레이 배선 완료 반영

- §2 XSHUT: ⬜ 미연결 → ✅ 배선 완료 (GPIO10 연결)
- §3 릴레이 핀: GPIO3 → GPIO23, 배선 완료 상태 표시
- §4 전체 배선 요약: GPIO10/GPIO23 완료 표시로 업데이트

## [2026-07-24] code | src/main.cpp — 릴레이 단독 토글 테스트 코드 작성

- `RELAY_TOGGLE_MS` (2000ms) 주기 millis() 기반 비블로킹 ON/OFF 토글
- `relayOn()` / `relayOff()`: `RELAY_ACTIVE_LOW` 상수로 극성 분기
- setup()에서 반드시 `relayOff()` 초기화 (안전)
- `LOGF()` 매크로: `printf()+fflush(stdout)` (ToF 테스트에서 검증된 방식)
- 빌드 환경: `pio run -e relay_test -t upload`

## [2026-07-24] test | Test #2 합격 — 릴레이 단독 테스트 성공

- 배선: IN=GPIO23, VCC=5V, GND=GND
- 문제: 초록불(상태 LED) 상시 ON, 소리 없음 → 3.3V HIGH ≠ 5V 릴레이 OFF
- 원인: 5V - 3.3V = 1.7V > 포토커플러 Vf(1.2~1.4V) → 미세전류로 릴레이 상시 ON
- 해결: `relayOff()` = `pinMode(INPUT)` (고임피던스) → 모듈 풀업으로 IN=5V → OFF 확실
- 출처: smartbox/reports/26061301_릴레이연결_report.md (동일 하드웨어, 동일 증상)
- hardware_test.md Test #2 결과: 🟢 합격

## [2026-07-24] fix | include/config.h — 통합 파라미터 추가

- `GATE_THRESHOLD_MM`: 300 → 500 (50cm)
- `RELAY_ON_DURATION_MS`: 1000ms (신규 추가)
- `RELAY_COOLDOWN_MS`: 2000ms (신규 추가)
- `RELAY_ACTIVE_LOW`: true 유지 (relayOn()에서 LOW 출력 기준)

## [2026-07-24] code | src/main.cpp — Step 1 로컬 통합 코드 작성 (ToF + Relay)

- 상태 머신 3단계: IDLE → RELAY_ON(1초) → COOLDOWN(2초) → IDLE
- `GateState` enum class로 상태 명시
- 비블로킹 millis() 기반 타이밍
- ToF: Wire.begin(GPIO6,7,400kHz), XSHUT=GPIO10, 65535 sentinel 체크
- Relay: INPUT 모드 트릭 (smartbox 26061301 보고서 방식)

## [2026-07-24] test | Test #3 합격 — Step 1 (Local PoC) 최종 완료 🟢

- ToF 센서 500mm 이하 감지 시 릴레이 1초 ON 후 자동 OFF (2초 쿨다운) 비블로킹 상태 머신 정상 작동
- hardware_test.md, index.md 등 문서 업데이트 완료
- Step 1 (하드웨어 단독 및 연동 검증) 최종 성공 완료 처리

## [2026-07-24] code | backend/ 뼈대 파일 생성 — Step 2 시놀로지 NAS 백엔드 구축 시작

- `backend/docker-compose.yml`: MariaDB 및 FastAPI 서비스 구성
- `backend/db/schema.sql`: Tenants (세입자 정보), AccessLogs (출입 기록) DDL 작성
- `backend/app/main.py`: FastAPI 기반 출입 자격 검증 및 로그 저장 API 뼈대 작성







