# schema.md — Wiki Governance Rules
> **Single Source of Truth** for the `smart-gatekeeper` project wiki.
> Co-evolve this file as conventions stabilise. Last updated: 2026-06-26.

---

## 1. Directory Layout

```
smart-gatekeeper/
├── .agents/
│   └── AGENTS.md         # IDE 자동 로드 핵심 규칙 (압축본)
├── raw/                  # Immutable source files (datasheets, API specs, etc.)
│   ├── ST_VL53L0X_Specs.md
│   ├── Espressif_ESP32C6_BoardSpec.md
│   └── BOM_SmartGatekeeper_Step1.md
├── wiki/                 # Compiled knowledge (Markdown only)
│   ├── index.md          # Navigation map — ALWAYS read first
│   ├── log.md            # Chronological change log
│   ├── env_setup.md      # Dev environment & toolchain
│   ├── pin_mapping.md    # Hardware pin assignments
│   ├── hardware_test.md  # Test procedures & results
│   └── architecture.md  # System overview & future phases
├── src/                  # PlatformIO / Arduino source code
├── include/              # Header files
├── platformio.ini        # PlatformIO project config
├── AGENTS.md             # 에이전트 협업 전체 지질 (각 에이전트 작업 시 필독)
├── schema.md             # 위키 거버넌스 규칙
└── README.md
```

---

## 2. File Naming Conventions

| Layer | Convention | Example |
|-------|-----------|---------|
| `raw/` | `<VENDOR>_<PART>_<TYPE>.pdf` | `ST_VL53L0X_Datasheet.pdf` |
| `wiki/` | `snake_case.md` | `pin_mapping.md` |
| `src/` | `PascalCase.cpp/.h` | `ToFSensor.cpp` |

---

## 3. Log Entry Format

Every change to the wiki **must** append a log entry to `wiki/log.md`:

```
## [YYYY-MM-DD] <type> | <brief description>
```

Allowed types:
- `ingest`   — new raw source added
- `compile`  — new or updated wiki page
- `code`     — firmware source added or changed
- `test`     — hardware test result recorded
- `fix`      — error corrected
- `lint`     — link/consistency check performed

---

## 4. Workflow — Per Turn

1. **Read** `wiki/index.md` before any action.
2. **Do** the work (write code, compile knowledge).
3. **Update** affected wiki pages.
4. **Update** `wiki/index.md` if new pages exist.
5. **Append** to `wiki/log.md`.
6. **Lint** — verify no broken links or contradictions.

---

## 5. Code Conventions (Firmware)

- Language: **C++17** (PlatformIO / Arduino framework)
- Style: Google C++ Style Guide (2-space indent)
- Modules: one `.cpp` + one `.h` per peripheral driver
- Error handling: `Serial.println("[ERROR] ...")` + safe fallback
- Pin constants: defined in `include/config.h`, never hardcoded

---

## 6. Hardware Constraints

| Item | Value |
|------|-------|
| MCU | **ESP32-C6-DevKitC-1** (RISC-V 32-bit, Wi-Fi 6, BLE 5.3) |
| Logic level | **3.3 V GPIO** |
| I2C bus | SDA=**GPIO6**, SCL=**GPIO7** (400kHz 명시 필수) |
| Relay control | GPIO**3** (Active-LOW 모듈 가정; 확인 필요) |
| ToF XSHUT | GPIO**10** (선택) |
| 스트래핑 핀 (사용 금지) | GPIO4, 5, 8, 9, 15 |
| 예약 핀 (사용 금지) | GPIO17(TX), 18(RX), 19(USB D+), 20(USB D-) |
| PlatformIO platform | pioarduino (공식 espressif32는 C6 Arduino 미지원) |

---

## 7. Open Questions Log

| # | Question | Status |
|---|----------|---------|
| 1 | Final ESP32 board variant? | ✅ **확정: ESP32-C6-DevKitC-1 (Type-C)** |
| 2 | 릴레이 모듈 극성? | 🟡 **조건부 해소**: Low/High 선택형 모듈 구매. 점퍼 "L" 위치 = Active-LOW. 현장에서 점퍼 확인 후 config.h 최종 확정 필요 |
| 3 | ToF 센서 수 (1 vs 2, 방향 감지)? | 🔴 Open |
| 4 | BLE stack: NimBLE or Bluedroid? | 🔴 Open (C6는 BLE 5.3 전용, Classic BT 없음) |
