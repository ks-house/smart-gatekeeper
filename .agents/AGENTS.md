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
- 현재 센서: AJ-SR04T `TRIG=GPIO10`, `ECHO=GPIO11`; 5 V ECHO 직결 금지.
- 릴레이: authoritative `GPIO3`, Active-LOW, OFF `INPUT` High-Z; 전기 안전 실측 필수.
- GPIO6/7 I2C는 초기 VL53L0X 이력이며 현재 배선 지시가 아니다. 잔존 bus-clear와 충돌하지 않게 비워 둔다.
- 금지 핀: **GPIO 4, 5, 8, 9, 15** (스트래핑) / **17, 18, 19, 20** (USB)
- 플랫폼: `pioarduino` (공식 `espressif32` 사용 시 C6 Arduino 빌드 불가)

### 3. 모든 변경 후 필수
- `wiki/log.md` 에 `## [YYYY-MM-DD] <type> | <desc>` 형식으로 append.
- 핀 변경 시: `config.h` + `pin_mapping.md` + `log.md` 동시 업데이트.
- `raw/` 파일 수정 금지 (읽기 전용).

### 4. 코드 규칙
- 핀 상수는 `include/config.h` 에서만 정의. 소스 파일 하드코딩 금지.
- 에러 접두어: `[FATAL]` / `[ERROR]` / `[WARN]` / `[INFO]`
- Hardwareless RC는 기본 `ENABLE_HARDWARELESS_RC=0`; lab build와 production 승인을 혼동하지 않는다.

### 5. 사실 축 분리
- 저장소 구현, 검증 증거, 현장 배포 상태를 분리한다.
- 현재 요약은 `wiki/project_status.md`, 최신 코드 감사는 `wiki/current_code_audit.md`를 따른다.
- 현관 매립 Target의 구형 배포 상태를 최신 source 구현으로 확대 해석하지 않는다.

### 6. OTA 최상위 불변조건
- 모바일 앱과 Target은 **항상 OTA 가능한 복구 경로**를 유지해야 한다.
- BLE/FSM/ACL/Backend/storage/network 변경은 mobile·Target OTA 비회귀와 N/N-1 호환을 증명하기 전 병합 금지.
- Target dual OTA, 이전 slot 보존, health 확인·rollback, periodic HTTPS + MQTT + local wireless recovery를 유지.
- 모바일 update는 scanner/foreground service/WebView와 독립시키고 설치 실패 시 기존 APK를 보존.
- 세부 기준: `wiki/ota_reliability_contract.md`, GitHub #23.

### 7. GitHub 인증
- GitHub CLI와 push는 현재 프로세스의 `GITHUB_TOKEN` 환경 변수만 사용한다.
- 토큰 원문을 출력하거나 파일·로그·remote URL에 저장하지 않는다.
- socket/network 차단을 인증 실패로 오판하지 말고 네트워크 권한을 적용한 `gh auth status`로 재검증한다.
- GitHub 연결 후에도 401/invalid인 경우에만 `GITHUB_TOKEN` 갱신을 요청하며, `gh auth login` 또는 저장 계정으로 우회하지 않는다.
