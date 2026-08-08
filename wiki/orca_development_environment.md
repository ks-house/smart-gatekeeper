# Orca Development Environment

> Windows Orca 워크트리의 반복 가능한 개발환경, 검증 suite, 프로파일 수명주기 기준.
> Last verified: 2026-08-08, Orca 1.4.176.

## 1. 적용된 프로젝트 정책

- 기본 기준 브랜치: `origin/main`
- 새 워크트리 setup: 기본 실행
- 에이전트 시작: setup 완료까지 대기
- 공유 설정: 루트 `orca.yaml`
- 로컬 setup 명령: `powershell -NoProfile -ExecutionPolicy Bypass -File .orca/scripts/setup_worktree.ps1`
- 자동화: 기본 비활성. 예기치 않은 비용, push, merge, 배포, 이슈 변경을 자동화하지 않는다.

setup은 새 워크트리에 ignored `.venv`를 만들고 backend/OTA Python 의존성을 설치한다. 요구사항
내용의 SHA-256이 바뀌지 않으면 재설치를 생략하고, PlatformIO `esp32c6` package를 확인한 뒤 doctor를
실행한다. `include/secrets.h`가 없을 때만 비밀값이 없는 example을 복사하며 기존 파일 내용은 읽거나
덮어쓰지 않는다.

## 2. 일상 명령

```powershell
# 최초 또는 요구사항 변경 후 setup
powershell -NoProfile -ExecutionPolicy Bypass -File .orca/scripts/setup_worktree.ps1

# 읽기 전용 상태 진단
powershell -NoProfile -ExecutionPolicy Bypass -File .orca/scripts/doctor.ps1

# 약 10초: backend, Compose, protocol, observability, OTA, hardwareless Gate
powershell -NoProfile -ExecutionPolicy Bypass -File .orca/scripts/validate.ps1 -Suite Quick

# Quick + root software suite
powershell -NoProfile -ExecutionPolicy Bypass -File .orca/scripts/validate.ps1 -Suite Software

# ESP32-C6 release build
powershell -NoProfile -ExecutionPolicy Bypass -File .orca/scripts/validate.ps1 -Suite Firmware

# Docker Flutter/JDK 17 분석 및 테스트
powershell -NoProfile -ExecutionPolicy Bypass -File .orca/scripts/validate.ps1 -Suite App

# 모든 software lane. 물리 Gate 통과를 의미하지 않는다.
powershell -NoProfile -ExecutionPolicy Bypass -File .orca/scripts/validate.ps1 -Suite Full
```

`-Suite App`은 네이티브 Flutter가 없으면 project Docker builder를 사용한다. 두 lane 모두 호스트 작업트리를
오염시키지 않도록 추적 파일과 ignore되지 않은 app 소스만 임시 디렉터리에 복사한 뒤 `pub get`, 범위형
`dart analyze lib test`, `flutter test`를 수행한다. 포맷까지 release-blocking으로 검사할 때만
`-EnforceFormat`을 추가한다.

## 3. 프로파일 작업 시작

작업은 필요한 역할만 on-demand로 시작한다. 모든 프로파일을 매 워크트리에서 자동 실행하지 않는다.

```powershell
.orca/scripts/start_task.ps1 `
  -Profile gpt5.6-terra `
  -RunObjective "Target and backend work" `
  -Objective "<scope, acceptance, and remaining physical gates>"
```

| Profile | 담당 |
|---|---|
| `gpt5.6-sol` | 코디네이션, 아키텍처, 리뷰, release Gate |
| `gpt5.6-terra` | ESP32-C6 firmware, protocol, backend |
| `gpt5.6-luna` | Android native, Flutter, QA |
| `antigravity` | 명시적 cross-layer 비상 작업 |

기본 런처는 Codex `workspace-write` sandbox를 유지하고 Antigravity permission bypass를 사용하지 않는다.
격리된 워크트리에서 범위와 위험을 확인한 경우에만 `-AllowUnsafe`를 명시한다.

## 4. 완료 수명주기

1. coordinator는 rolling `check --wait`로 `worker_done`, `escalation`, `question`을 확인한다.
2. `ready`, heartbeat, TUI activity, timeout은 완료가 아니다.
3. 현재 CLI의 worker는 주입된 정확한 Task/Dispatch ID로 exactly one `worker_done`을 보낸다.
4. coordinator는 완료 메시지를 검토한 뒤 exact Dispatch를 release하거나 즉시 재사용한다.
5. 그 다음 whole Delivery를 ACK한다.

```powershell
orca orchestration check --wait --types "worker_done,escalation,question" --timeout-ms 60000 --json
orca orchestration worker-release --dispatch <dispatch_id> --json
orca orchestration check --ack <delivery_id> --json
```

`worker_done`은 활성 Dispatch가 주입한 lifecycle preamble의 명령 전체를 그대로 사용한다. 저수준 staged Dispatch는 pane identity를 대신해 `--from`과 `--dispatch-capability`를 요구할 수 있고 supervised worker는 이를 생략할 수 있으므로, 문서 예시나 과거 명령을 기준으로 lifecycle 플래그를 추가·삭제·재구성하지 않는다. `ORCA_CLI_COMMAND`가 없을 때 프로젝트 스크립트는 준비된 public `orca`를 우선 사용하고, public CLI가 없을 때만 `ORCA_DEV_REPO_ROOT`의 `orca-dev`로 fallback한다.

## 5. 증거 경계

doctor와 모든 validation suite는 host/software evidence다. 성공해도 Samsung/OEM 화면 OFF, ESP32-C6
BLE radio/GPIO3, relay/sensor timing, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, production 승인
증거를 만들지 않는다. 물리 장비와 운영자 증거가 없으면 해당 Gate는 계속 `pending / fail-closed`다.
