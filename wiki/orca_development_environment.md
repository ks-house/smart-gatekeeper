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

작업은 필요한 역할만 on-demand로 시작한다. 모든 프로파일을 매 워크트리에서 자동 실행하지 않는다. 런처는 빈 TUI에 첫 prompt를 나중에 주입하지 않고 역할 bootstrap을 최초 CLI interactive prompt로 전달하며, assistant marker 뒤 렌더러의 `•Running` 경계까지 포함한 `PROFILE_READY`와 최종 `tui-idle`이 모두 확인된 뒤에만 Task를 Dispatch한다. 지시문 안의 marker 예시는 승인하지 않으며 bootstrap timeout/final-idle 실패는 정확한 터미널을 닫는다. 각 startup attempt는 생성 직후부터 cleanup 경계에 들어가므로 `tui-idle` timeout/error, startup snapshot error, 또는 tail 끝의 현재 PowerShell prompt를 발견하면 그 정확한 터미널을 닫는다. 첫 실패만 새 터미널에서 한 번 재시도하고 두 번째 실패도 정확한 터미널을 닫고 차단한다. Dispatch 직전 cursor 이후 출력을 기본 30초 동안 bounded 관찰해 exact `[Pasted Content N chars]`에는 Enter를 한 번 보내고, 아니면 post-Dispatch `UserPromptSubmit`/`Working` 증거를 요구한다. former 5초 동안 marker가 없었다는 사실은 성공 증거가 아니다.

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

기본 런처는 Codex `workspace-write` sandbox와 공식 `sandbox_workspace_write.network_access=true`, `windows.sandbox_private_desktop=false` 설정을 함께 사용한다. 파일 쓰기 범위는 작업공간으로 유지하면서 Windows worker command가 Orca desktop/runtime과 호환되는 기본 desktop 경계에서 lifecycle 명령을 전달하게 한다. 전용 repository worker는 시작 경쟁을 제거하기 위해 선택적 Apps 기능과 `node_repl` MCP를 비활성화하고 GitHub 작업은 `GITHUB_TOKEN` 기반 CLI를 사용한다. Antigravity permission bypass는 사용하지 않는다.
격리된 워크트리에서 범위와 위험을 확인한 경우에만 `-AllowUnsafe`를 명시한다.

### 3.1 Issue #55 임시 staged-launcher 정책

PR #60을 `cb8b2efe92c771e8c139fcc1ba749d9dcff29f5f`로 병합한 뒤에도 packaged
`worker-start`는 `stage=input_accepted` / `state=ready`를 반환한 후 Codex가 Task를 처리하지 않고
PowerShell prompt로 돌아가는 현상을 간헐적으로 보였다. 실패한 post-merge Dispatch는
`ctx_9c12b0b408b6`, `ctx_ee7fcea88a85`, `ctx_90e5dd8eb538`, `ctx_9fba6a4d79c8`,
`ctx_1a9c7feb07ad`, `ctx_d9b78c72bb32`이고, exact attempt를 완료로 계산하지 않았다. 반면 staged
launcher는 exact Task를 `ctx_e1f6e94ad254`로 profile-ready 이후 정상 주입했다. 이 한 번의 성공은
intermittent packaged-runtime 결함이 수정됐다는 증거가 아니다.

#55 acceptance matrix가 실제 runtime에서 통과할 때까지 repository profile worker는 다음 경로를 쓴다.

```powershell
# 새 Run/Task를 만들 때
.orca/scripts/start_task.ps1 `
  -Profile gpt5.6-terra `
  -RunObjective "<run objective>" `
  -Objective "<scope and acceptance>"

# coordinator가 이미 만든 exact Task를 시작할 때
.orca/scripts/launch_profiles.ps1 -Profile gpt5.6-terra -TaskId <task_id> -Worktree active
```

staged 경로의 contract는 initial argv profile bootstrap, 첫 `tui-idle`, exact `PROFILE_READY`, final
`tui-idle`, pre-Dispatch cursor, `dispatch --inject`, exact post-cursor paste marker에만 허용되는 bounded
Enter 순서다. startup 또는 Dispatch acceptance 전 실패는 exact terminal을 닫는다. Dispatch가 이미
수락된 뒤 submission 검증이 실패하면 launcher는 terminal을 보존하고 exact Dispatch ID와 함께
실패하므로 coordinator가 transcript/state를 검사하고 그 exact Dispatch를 stop/account한다.

실제 Luna `task_12e31176e5b3`의 `term_fe8c325a`와 Terra `-AllowUnsafe`
`task_469ab65347a5`의 `term_01eb874d`에서는 former 5초 observation이 성공 반환한 뒤에도 terminal 끝에
미제출 marker가 늦게 남아 coordinator가 각각 exact Enter를 한 번 보내야 했다. 따라서 새 contract는
marker 부재를 성공으로 해석하지 않고 기본 30초 안에 post-cursor `UserPromptSubmit`/`Working` 또는
exact marker+single Enter를 요구한다. positive evidence가 없으면 이미 accepted된 Dispatch와 terminal을
보존한 채 fail closed하여 coordinator가 exact attempt를 inspect/stop/account하게 한다.

Antigravity는 현재 `agy 1.1.11`을 사용한다. 이 버전은 positional initial prompt를 interactive TUI에
유지하지 않으므로 launcher는 `agy --effort high --prompt-interactive '<bootstrap>'`을 사용한다.
bootstrap은 이 checkout의 absolute root와 guidance 파일을 명시하고 exact worktree 밖을 search하지
말라고 요구한다. Orca가 `blockedReason=codex-trust-workspace`를 반환하면 launcher는 exact terminal을
닫고 명시적 진단으로 중단하며 자동 trust, home `--add-dir`, broad permission 저장 또는
`-AllowUnsafe` 우회를 하지 않는다. operator가 exact isolated worktree만 별도 interactive session에서
승인한 뒤 launcher를 다시 실행해야 한다.

agy renderer가 첫 `tui-idle` timeout 전에 exact `PROFILE_READY antigravity`를 이미 출력한 경우 그
marker는 initial observation만 대체할 수 있다. launcher는 final `tui-idle`을 다시 요구한 뒤에만
Dispatch한다. trust prompt, marker, renderer activity 또는 terminal shell `running`만으로 Task를
시작/완료했다고 판정하지 않는다.

launcher 성공 뒤에도 coordinator는 exact Dispatch와 terminal tail을 확인해야 한다. 현재 PowerShell
prompt로 끝나는 terminal, `input_accepted`, `ready`, injected prompt, heartbeat는 completion이 아니다.
accepted `worker_done`만 완료이며 `runtime_unavailable`에는 동일 mutation 반복이나 다른 identity의
대리 전송을 하지 않는다.

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

### 4.1 6분 초과 longevity probe

GitHub #55의 intermittently unreachable packaged runtime을 검사할 때는
`.orca/scripts/probe_lifecycle.ps1`을 사용한다. 기본 7회 × 65초 probe는 exact HEAD, 시작 대비
worktree status, `raw/`, runtime ID와 heartbeat receipt를 확인하지만 `worker_done`을 보내지 않는다.
probe 성공, heartbeat, ready 상태는 완료가 아니며 worker가 주입된 exact 명령으로 한 번 보낸
`worker_done`이 수락돼야 한다.

`runtime_unavailable`과 worker-side `starting/reachable=false/runtimeId=null`이 함께 나오면 변경과
transcript를 보존하고 fail closed한다. coordinator-side ready 상태가 있더라도 worker completion을
대리하거나 추측으로 반복하지 않는다. 설치된 Orca 1.4.176 분석과 recovery 절차는
[Orca lifecycle longevity incident](orca_lifecycle_incident.md)에 기록한다.

## 5. 증거 경계

doctor와 모든 validation suite는 host/software evidence다. 성공해도 Samsung/OEM 화면 OFF, ESP32-C6
BLE radio/GPIO3, relay/sensor timing, bootloader rollback, OTA-G1..G4, RELAY-G0..G2, production 승인
증거를 만들지 않는다. 물리 장비와 운영자 증거가 없으면 해당 Gate는 계속 `pending / fail-closed`다.
