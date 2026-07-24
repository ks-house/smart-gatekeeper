# hardware_test.md — 하드웨어 테스트 절차 및 결과
> Phase: Step 1 (Local PoC) — 🟢 **완료 (Step 1 통과)**
> Last updated: 2026-07-24

---

## Test #1: VL53L0X ToF 센서 단독 테스트

### 목표
mm 단위 거리를 I2C로 읽어 시리얼 모니터에 실시간 출력

### 사전 조건
- [ ] `env_setup.md` 기준 환경 구축 완료
- [ ] `pin_mapping.md` 기준 배선 완료
- [ ] VL53L0X 모듈에 3.3V 공급 확인

### 테스트 절차

```
1. platformio.ini 에서 [env:tof_test] 환경 선택
2. pio run -e tof_test -t upload
3. pio device monitor --baud 115200
4. 시리얼 모니터에서 다음 확인:
   - "[INFO] VL53L0X initialized" 출력
   - 거리 값 (mm) 주기적 출력
   - 손을 가져다 대면 값 변화 확인
```

### 합격 기준

| 항목 | 기준 |
|------|------|
| 초기화 | `[INFO] ToFSensor: VL53L0X initialized. Continuous mode @ 100ms interval.` 출력 |
| 거리 측정 범위 | 20mm ~ 1200mm 정상 값 |
| 측정 주기 | 100ms 이하 |
| 에러 처리 | I2C 연결 실패 시 "[ERROR]" 메시지 후 무한 루프 방지 |

### 결과 기록

| 날짜 | 결과 | 비고 |
|------|------|------|
| 2026-07-24 | 🟢 **합격** | GPIO6/7/10 배선 완료. `printf()+fflush()` 필수 |

**학습된 트릭 (ESP32-C6 특이사항):**
- `Serial.println()` → 철주히 사용 금지 — USB-CDC 버퍼 모드 불일치로 출력 유실
- `printf() + fflush(stdout)` → ESP-IDF stdout 경로 = i2cInit 로그와 동일, 항상 표시
- XSHUT 미연결 시 저가 모듈은 floating LOW → 센서 리셋 상태 고정 → GPIO10 명시 구동 필수

---

## Test #2: 릴레이 단독 테스트

### 목표
2초 주기로 릴레이를 ON/OFF 스위칭하여 동작음 및 접점 확인

### 사전 조건
- [ ] 릴레이 모듈 Active-HIGH/LOW 극성 확인
- [ ] `pin_mapping.md` 기준 배선 완료
- [ ] 릴레이 접점에는 테스트용 LED+저항만 연결 (AC 전원 미연결)

### 테스트 절차

```
1. platformio.ini 에서 [env:relay_test] 환경 선택
2. pio run -e relay_test -t upload
3. pio device monitor -b 115200
4. 시리얼 모니터에서 다음 확인:
   - "[Relay] ON  (t=xxx ms)" / "[Relay] OFF (t=xxx ms)" 교번 출력
   - 릴레이 동작음(딱낙) 2초 간격 확인
5. config.h 에서 RELAY_ACTIVE_LOW 값 조정 후 재테스트 (실제 모듈 실크스크린 확인)
```

### 합격 기준

| 항목 | 기준 |
|------|------|
| 스위칭 핀 | GPIO23 (`config.h: PIN_RELAY=23`) |
| 스위칭 주기 | 2000ms ± 50ms |
| 동작음 | 릴레이 코일 딱낙 소리 |
| 시리얼 로그 | `[Relay] ON  (t=xxx ms)` / `[Relay] OFF (t=xxx ms)` 연속 출력 |
| 출력 매쪭 | `printf()+fflush(stdout)` 사용 (`Serial.println` 사용 금지) |

### 결과 기록

| 날짜 | 결과 | 비고 |
|------|------|------|
| 2026-07-24 | 🟢 **합격** | GPIO23, INPUT 모드 트릭 적용. 딸깍 소리 + 시리얼 정상 출력 |

**학습된 트릭 (3.3V ESP32 ↔ 5V 릴레이 전압 호환성):**
- 문제: 5V - 3.3V = 1.7V > 포토커플러 Vf(1.2~1.4V) → 3.3V HIGH에도 전류 흐름 → 상시 ON
- 해결: `relayOff()` = `pinMode(INPUT)` (고임피던스) → 모듈 풀업으로 IN=5V → 포토커플러 OFF
- 출처: smartbox/reports/26061301_릴레이연결_report.md

---

## Test #3: 통합 테스트 (ToF + Relay) — Step 1 Local PoC 최종
> Test #1(VL53L0X) ✅ + Test #2(Relay) ✅ 통과 후 진행

### 목표
ToF 거리 ≤ 500mm 감지 시 릴레이 1초 ON → 자동 OFF (쿨다운 2초)

### 동작 설계 (상태 머신)

```
[IDLE] ──감지(<= 500mm)──▶ [RELAY_ON] ──1초 경과──▶ [COOLDOWN] ──2초 경과──▶ [IDLE]
  ▲                                                                                  │
  └──────────────────────────────────────────────────────────────────────────────────┘
```

### 파라미터 (config.h)

| 상수 | 값 | 설명 |
|------|-----|------|
| `GATE_THRESHOLD_MM` | `500` | 트리거 거리 (mm) |
| `RELAY_ON_DURATION_MS` | `1000` | 릴레이 ON 유지 시간 |
| `RELAY_COOLDOWN_MS` | `2000` | 재트리거 방지 쿨다운 |
| `TOF_POLL_INTERVAL_MS` | `100` | ToF 측정 주기 |

### 테스트 절차

```
1. pio run -e esp32c6 -t upload   (통합 빌드 환경)
2. pio device monitor -b 115200
3. 손을 센서 앞 50cm 이내로 접근
4. 시리얼 출력 확인:
   "[GATE] *** 감지! XXX mm <= 500 mm → 릴레이 ON ***"
   릴레이 딸깍(ON)
   1초 후 "[GATE] 릴레이 OFF (1초 경과)"
   릴레이 딸깍(OFF)
   2초 쿨다운 후 "[GATE] 쿨다운 완료. IDLE 상태 복귀."
```

### 합격 기준

| 항목 | 기준 |
|------|------|
| 감지 거리 | ≤ 500mm 진입 시 릴레이 ON |
| ON 유지 | 1000ms ± 100ms |
| 자동 OFF | 1초 후 자동 OFF (수동 개입 없음) |
| 쿨다운 | 2초 내 재트리거 없음 |
| 시리얼 로그 | IDLE/RELAY_ON/COOLDOWN 상태 전환 출력 |

### 결과 기록

| 날짜 | 결과 | 비고 |
|------|------|------|
| 2026-07-24 | 🟢 **합격** | ToF 500mm 이내 감지 시 릴레이 1초 ON 후 자동 OFF (쿨다운 2초) 동작 완벽 확인 |
