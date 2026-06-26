# raw/ST_VL53L0X_Specs.md
# VL53L0X — Compiled Datasheet Reference
> Source: STMicroelectronics VL53L0X Datasheet (DS11486) + Pololu Arduino Library API
> Ingested: 2026-06-26
> Status: Immutable — edit only by creating a new version file

---

## 1. 디바이스 개요

| 항목 | 값 |
|------|-----|
| 제조사 | STMicroelectronics |
| 파트 번호 | VL53L0X |
| 기술 | Time-of-Flight (ToF), 940nm IR 레이저 (Class 1, 눈 안전) |
| 패키지 | LGA-12 (2.4 × 4.4 × 1.0 mm) |
| 기본 I²C 주소 | **0x29** (7-bit) |

---

## 2. 핵심 전기 사양

| 파라미터 | Min | Typ | Max | 단위 |
|---------|-----|-----|-----|------|
| 공급 전압 AVDD | 2.6 | 2.8 | 3.5 | V |
| 동작 전류 (측정 중) | — | ~20 | — | mA |
| 대기 전류 (XSHUT=LOW) | — | 5 | — | µA |
| 동작 온도 | -20 | +25 | +70 | °C |

> ⚠️ **CRITICAL**: AVDD 최대 3.5V. ESP32 3.3V 공급은 안전. **5V 직결 절대 금지**.

---

## 3. 측정 사양

| 파라미터 | 값 | 조건 |
|---------|-----|------|
| 측정 범위 | 30 ~ 2000 mm | 일반 환경 |
| 측정 범위 (실용) | 30 ~ 1200 mm | 실내, 백색 타깃 |
| 분해능 | 1 mm | |
| 정확도 | ±3~5% | 타깃 반사율, 조도 의존 |
| 시야각 (FoV) | 25° | 전각(Full angle) |
| 레이저 파장 | 940 nm | |

---

## 4. I²C 인터페이스

| 파라미터 | 값 |
|---------|-----|
| 지원 속도 | Standard (100 kHz), Fast (400 kHz) |
| 기본 주소 | 0x29 |
| 레지스터 폭 | 8/16/32-bit |
| SCL/SDA 전압 | 1.8V ~ AVDD |

### 핀 설명
| 핀 | 기능 | 비고 |
|----|------|------|
| SDA | I²C 데이터 | |
| SCL | I²C 클록 | |
| XSHUT | Active-LOW 셧다운/리셋 | 풀업 필요 또는 GPIO HIGH 유지 |
| GPIO1 | 인터럽트 출력 (data ready) | 선택사항 |
| VDD/AVDD | 전원 | 2.6~3.5V |
| GND | 접지 | |

---

## 5. 측정 모드 (Ranging Profiles)

| 모드 | 타이밍 버짓 | 최대 범위 | 특성 |
|------|-----------|---------|------|
| Default | 33 ms | ~1.2 m | 일반 용도 |
| High Accuracy | 200 ms | ~1.2 m | 정밀도 우선 |
| Long Range | 33 ms | ~2.0 m | 어두운 환경 |
| High Speed | 20 ms | ~1.2 m | 속도 우선, 정밀도 저하 |

---

## 6. Pololu 라이브러리 API 요약

```cpp
// 초기화
bool init();                                  // true = 성공
void setTimeout(uint16_t timeout_ms);         // I2C 타임아웃 설정 (권장: 500ms)
bool timeoutOccurred();                       // 마지막 읽기가 타임아웃이었는지

// 타이밍 버짓 (정확도 vs 속도)
bool setMeasurementTimingBudget(uint32_t us); // 기본값 33000 µs
uint32_t getMeasurementTimingBudget();

// 연속 측정 모드 (권장)
void startContinuous(uint32_t period_ms = 0); // 0 = back-to-back
void stopContinuous();
uint16_t readRangeContinuousMillimeters();    // 블로킹 (다음 측정 완료까지 대기)

// 단발 측정 모드
uint16_t readRangeSingleMillimeters();        // 블로킹

// 논블로킹 읽기 (고급)
// RESULT_INTERRUPT_STATUS & 0x07 != 0 → 데이터 준비됨
// RESULT_RANGE_STATUS + 10 → 측정값 레지스터
```

---

## 7. ESP32 특이사항

### I²C 400kHz 활성화
```cpp
Wire.begin(21, 22, 400000UL);  // SDA, SCL, 400kHz fast mode
```
> 기본 `Wire.begin(21, 22)` 는 **100kHz** → 측정 사이클 지연 발생

### 타임아웃 설정 필수
```cpp
sensor.setTimeout(500);  // init() 전에 설정
```
> 미설정 시 I²C 끊어지면 `readRange...()` 영구 블로킹

### 값 65535 = 측정 오류
```cpp
uint16_t mm = sensor.readRangeContinuousMillimeters();
if (mm == 65535 || sensor.timeoutOccurred()) {
    // 에러 처리
}
```

---

## 8. 다중 센서 (XSHUT 순차 주소 할당)

```cpp
// 예: 2개 센서 → 각각 GPIO15, GPIO16 에 XSHUT 연결
// 1. 모든 XSHUT LOW → 모든 센서 셧다운
// 2. 센서1 XSHUT HIGH → 부팅 → setAddress(0x30)
// 3. 센서2 XSHUT HIGH → 부팅 → 기본 주소 0x29 유지
// 결과: 센서1=0x30, 센서2=0x29
```

---

## 9. 참고 문서

| 문서 | URL |
|------|-----|
| 공식 데이터시트 DS11486 | https://www.st.com/resource/en/datasheet/vl53l0x.pdf |
| API 사용자 매뉴얼 UM2039 | https://www.st.com/resource/en/user_manual/um2039-world-smallest-i2c-ranging-sensor-application-programming-interface-stmicroelectronics.pdf |
| Pololu Arduino 라이브러리 | https://github.com/pololu/vl53l0x-arduino |
