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

