# hardware_test.md — 하드웨어 테스트 절차 및 결과
> Phase: Step 1 (Local PoC)
> Last updated: 2026-06-26

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
| 초기화 | "[INFO] VL53L0X initialized" 출력 |
| 거리 측정 범위 | 20mm ~ 1200mm 정상 값 |
| 측정 주기 | 100ms 이하 |
| 에러 처리 | I2C 연결 실패 시 "[ERROR]" 메시지 후 무한 루프 방지 |

### 결과 기록

| 날짜 | 결과 | 비고 |
|------|------|------|
| - | 🔲 미실시 | |

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
3. 시리얼 모니터에서 "RELAY ON" / "RELAY OFF" 교번 출력 확인
4. 릴레이 동작음(딸깍) 및 LED 점멸 확인
```

### 합격 기준

| 항목 | 기준 |
|------|------|
| 스위칭 주기 | 2000ms ± 50ms |
| 동작음 | 릴레이 코일 딸깍 소리 |
| LED | ON/OFF 교번 점멸 |
| 시리얼 로그 | 타임스탬프 포함 ON/OFF 메시지 |

### 결과 기록

| 날짜 | 결과 | 비고 |
|------|------|------|
| - | 🔲 미실시 | |

---

## Test #3: 통합 테스트 (ToF + Relay)
> 이 테스트는 Test #1, #2 통과 후 진행

### 목표
거리 임계값(threshold) 이하 감지 시 릴레이 자동 트리거

### 임계값
- 기본값: **300mm** (30cm) 이하 감지 시 릴레이 ON
- `config.h`의 `GATE_THRESHOLD_MM` 상수로 조정

### 결과 기록

| 날짜 | 결과 | 비고 |
|------|------|------|
| - | 🔲 미실시 | |
