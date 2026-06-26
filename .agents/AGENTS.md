# AGENTS.md — smart-gatekeeper Workspace Rules
> 이 파일은 PlatformIO 워크스페이스 `.agents/` 경로에 위치하며,
> Antigravity IDE가 자동으로 로드하는 프로젝트 스코프 규칙이다.
> 전체 지침은 프로젝트 루트의 [AGENTS.md](../AGENTS.md) 를 참조하라.

---

## Critical Rules (자동 로드됨)

### 1. 반드시 먼저 읽어라
```
wiki/index.md   → 전체 지식 지도
wiki/log.md     → 직전 에이전트 작업 내용
```

### 2. 하드웨어 절대 규칙
- MCU: **ESP32-C6** (RISC-V). 구형 ESP32(Xtensa) 핀 번호 사용 금지.
- I2C: `Wire.begin(6, 7, 400000UL)` — 핀·속도 항상 명시.
- 금지 핀: **GPIO 4, 5, 8, 9, 15** (스트래핑) / **17, 18, 19, 20** (USB)
- 플랫폼: `pioarduino` (공식 `espressif32` 사용 시 C6 Arduino 빌드 불가)

### 3. 모든 변경 후 필수
- `wiki/log.md` 에 `## [YYYY-MM-DD] <type> | <desc>` 형식으로 append.
- 핀 변경 시: `config.h` + `pin_mapping.md` + `log.md` 동시 업데이트.
- `raw/` 파일 수정 금지 (읽기 전용).

### 4. 코드 규칙
- 핀 상수는 `include/config.h` 에서만 정의. 소스 파일 하드코딩 금지.
- 에러 접두어: `[FATAL]` / `[ERROR]` / `[WARN]` / `[INFO]`
- 라이브러리: `pololu/VL53L0X` (Adafruit 버전 사용 금지)
