# Orca lifecycle longevity incident (#55)

> Orca 1.4.176의 장기 `workspace-write` worker가 heartbeat를 전달한 뒤 최종
> `worker_done`에서 `runtime_unavailable`을 반환한 사건의 증거, 경계, 재현 절차.
> Last verified: 2026-08-09.

## 1. 결론

이 저장소의 profile bootstrap/Dispatch launcher는 Task 시작 전 경쟁과 실패한 터미널 정리를
담당하지만, 장기 worker의 최종 lifecycle RPC를 운반하는 packaged Orca named pipe를 구현하지
않는다. 현재 증거로 확인된 실패 경계는 **Dispatch capability 검증 전의 packaged CLI → desktop
runtime transport**이다. capability 만료나 저장소 launcher 결함을 원인으로 단정할 증거는 없다.

따라서 저장소 차원의 조치는 다음으로 제한한다.

- 안전한 기본값인 Codex `workspace-write`를 유지하고 `-AllowUnsafe`를 자동 적용하지 않는다.
- 장기 probe가 exact HEAD, worktree 상태, `raw/`, runtime ID, heartbeat receipt를 반복 확인하게 한다.
- probe는 `worker_done`을 보내거나 완료를 가장하지 않는다. 활성 worker만 주입된 정확한 명령으로
  exactly once 완료 보고를 시도한다.
- transport가 사라지면 변경과 transcript를 보존하고 Dispatch를 blocked로 처리한다. heartbeat,
  terminal activity, 로컬 report를 완료로 승격하지 않는다.

## 2. 관측 증거

### 2.1 재현된 장기 실패

GitHub issue #55의 Dispatch `ctx_7cc377d20311` / Task `task_2c7210ed6841`은 PR #47 exact head
`cf156c8dbb2dd9d677ca87231100b1163a546261`에서 initial heartbeat와 iteration 1~6, 총 7개의
heartbeat를 수락했다. 마지막 heartbeat는 `2026-08-08T16:24:08Z`에 기록됐다. 약 10초 뒤
bounded `worker_done` 시도는 `runtime_unavailable`을 반환했다.

같은 시점에 worker의 `orca status --json`은 desktop PID가 실행 중이지만 runtime을
`starting`, `reachable=false`, `runtimeId=null`로 표시했다. coordinator는 즉시 같은 desktop을
`ready`, `reachable=true`, runtime ID `e221a8da-b68b-4655-8f1b-d1bf51b68f36`으로 관측했다.
heartbeat keepalive가 최종 mutation 가능성을 보장하지 않음을 재현한 증거이며, 완료 증거는 아니다.

### 2.2 exact integrated main 기준선

- integrated main: `b246aff9698ccbcbcd864f99aab63654cce2cc78`
- post-merge GitHub Actions: run `31268170523`, terminal success
- coordinator Quick: doctor 12 pass/1 Java warning, backend 32 pass(선택형 MariaDB 1 skip),
  Compose/protocol/observability/OTA/hardwareless checks pass
- production deploy: 의도대로 skipped
- physical/operator/production Gates: 계속 pending / fail-closed

이 기준선은 저장소 software 상태를 확인하지만 packaged runtime 결함을 수정했다는 뜻이 아니다.

### 2.3 transport 보조 probe

현재 `workspace-write` worker에서 packaged CLI status를 8개 process × 12회, 총 96회 병렬 호출했다.
96회 모두 같은 runtime ID로 `ready/reachable`이었으므로 단순한 낮은 동시성 포화는 뒷받침되지
않는다. 새 harness의 1회 실제 heartbeat probe도 exact HEAD/status/`raw/`를 유지하며 수락됐고,
`completionSent=false`를 보고했다. 짧은 성공은 장기 최종 완료의 대체 증거가 아니다.

### 2.4 exact-main 장기 재검증: 성공, 결함 미재현

별도 read-only `workspace-write` worker를 exact main `b246aff9698ccbcbcd864f99aab63654cce2cc78`의
top-level worktree에서 Task `task_e043a7540909` / Dispatch `ctx_1c1a0ce01ab8`로 실행했다. 다음
7개 heartbeat가 모두 수락됐다.

| UTC | Message |
|---|---|
| 17:17:30 | `msg_1431cff18365` |
| 17:19:14 | `msg_8814d958ac63` |
| 17:20:29 | `msg_21febff9f87e` |
| 17:21:44 | `msg_1a84ffeed576` |
| 17:23:01 | `msg_39e0cca192b6` |
| 17:24:17 | `msg_8def8d249b8e` |
| 17:25:32 | `msg_607efe234d37` |

첫 heartbeat 약 8분 34초 뒤인 `17:26:04Z`, final `worker_done` `msg_666e7110dc1e`가
`outcome=succeeded`로 수락됐다. Dispatch는 `completed`, worker는 `succeeded/settled`,
`failure_count=0`이었고 exact clean HEAD가 유지됐다. worker와 coordinator 모두 같은 runtime ID
`e221a8da-b68b-4655-8f1b-d1bf51b68f36`을 ready/reachable로 관측했다.

coordinator의 `worker-release`는 `released`, `processAction=closed_agent_terminal`, transcript captured로
종료됐고 terminal resource는 오류 없이 정리됐다. read-only probe worktree만 의도적으로 남았다.
이 성공은 exact-main에서 장기 경로가 동작할 수 있음을 증명하지만, 이전 동일 runtime ID의 실패를
부정하거나 intermittent packaged-runtime 결함을 수정했다는 증거는 아니다.

### 2.5 PR #60 병합 후 packaged worker-start 재발

PR #60은 `cb8b2efe92c771e8c139fcc1ba749d9dcff29f5f`로 병합됐지만, 그 probe와 가이드는
packaged runtime 자체를 변경하지 않았다. 병합 뒤 packaged `worker-start`가
`stage=input_accepted` / `state=ready`를 반환한 다음 실제 Codex task 처리 없이 PowerShell로 돌아간
attempt가 Sol/Terra/Luna에서 다시 관측됐다.

- failed/non-completion Dispatch: `ctx_9c12b0b408b6`, `ctx_ee7fcea88a85`,
  `ctx_90e5dd8eb538`, `ctx_9fba6a4d79c8`, `ctx_1a9c7feb07ad`, `ctx_d9b78c72bb32`
- staged launcher success: `ctx_e1f6e94ad254`

각 failed attempt는 inspect/stop/terminal accounting 후 완료에서 제외됐다. 일부 bounded retry와
staged launcher가 성공한 사실은 total outage가 아니라 intermittency임을 뒷받침하지만, root cause
수정이나 acceptance matrix 완료를 증명하지 않는다. Issue #55는 open 상태를 유지한다.

같은 follow-up에서 Antigravity의 별도 profile-launch contract도 확인됐다. installed `agy 1.1.11`은
positional prompt를 interactive session으로 유지하지 않아 `agy --effort high '<bootstrap>'`가 종료했고,
cleanup 중 이미 사라진 tab은 `tab_not_found`를 반환했다. 지원되는
`agy --effort high --prompt-interactive '<bootstrap>'`은 시작했지만 최초 exact-worktree trust prompt를
Orca가 `codex-trust-workspace`로 보고했다. exact isolated worktree trust 뒤에도 broad search 성향이
있어 absolute root와 no-outside-search bootstrap이 필요했다. 이는 packaged `worker-start` root cause
증거가 아니라 staged Antigravity launcher의 독립된 version/scope contract다.

기존 5초 submission observation도 충분하지 않았다. Luna `task_12e31176e5b3` terminal
`term_fe8c325a`와 Terra `-AllowUnsafe` `task_469ab65347a5` terminal `term_01eb874d`에서 launcher가
성공을 반환한 뒤 exact unsubmitted marker가 terminal 끝에 늦게 나타났고 coordinator가 각각 Enter를
한 번 보내야 했다. marker가 5초 안에 없다는 사실은 submission이나 실제 Task processing 증거가 아니다.

## 3. packaged Orca 1.4.176 경계 분석

설치된 version-matched source를 읽은 결과:

1. `out/cli/runtime/metadata.js`는 `orca-runtime.json`의 Windows `named-pipe` transport와
   runtime auth token을 읽는다.
2. `out/cli/runtime/transport.js`는 named pipe에 연결한 뒤에야 auth token과 선택적
   `orchestrationCapability`를 request envelope에 쓴다. pipe connect error 또는 응답 전 close는
   typed `runtime_unavailable`이다.
3. `out/cli/runtime/status.js`는 status RPC가 실패했지만 metadata의 desktop PID가 살아 있으면
   상태를 `starting`, `reachable=false`, `runtimeId=null`로 투영한다.
4. `out/cli/handlers/orchestration.js`의 lifecycle send는 terminal identity RPC와 mutation RPC 모두
   같은 runtime transport에 의존한다.

따라서 위 실패에서 확정할 수 있는 것은 capability 검증 이전 transport 연결 실패다. named-pipe
실패의 packaged-runtime 내부 원인과 재현 빈도, token/capability TTL 가설은 아직 확정되지 않았다.

## 4. 반복 가능한 probe

활성 Dispatch worker에서 주입된 preamble의 Task/Dispatch/from/capability 값을 **현재 값 그대로**
전달한다. capability는 파일에 저장하거나 출력하지 않는다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .orca/scripts/probe_lifecycle.ps1 `
  -TaskId <task_id> `
  -DispatchId <dispatch_id> `
  -ExpectedHead <40-char-sha> `
  -Iterations 7 `
  -IntervalSeconds 65 `
  -From <only-when-injected> `
  -DispatchCapability <only-when-injected> `
  -RequireClean
```

기본 probe는 7개 heartbeat를 65초 간격으로 보내므로 첫 heartbeat부터 마지막 heartbeat까지 390초,
즉 6분을 초과한다. 각 iteration과 final boundary에서 다음을 검증한다.

- exact HEAD 유지
- 시작 시점 대비 worktree status 불변
- `raw/` 변경 없음
- runtime `ready/reachable` 및 runtime ID 불변
- exact Task/Dispatch를 포함하는 heartbeat receipt 수락

probe의 최종 JSON은 `completionSent=false`다. 이후 worker가 결과를 검토하고 주입된 exact
`worker_done` 명령을 한 번만 실행해야 비로소 lifecycle acceptance를 시험한다.

## 5. 실패 시 운영 절차

1. 동일한 완료 mutation을 추측으로 반복하거나 다른 terminal identity로 대리 전송하지 않는다.
2. CLI가 structured recovery arguments를 출력하면 같은 executable로 그 exact arguments만 사용한다.
3. recovery가 없거나 runtime이 계속 unreachable이면 worker 변경, transcript, probe output을 보존한다.
4. coordinator는 `worker-read`, `dispatch-show`, terminal/runtime 상태를 독립 확인하고 Task를 blocked로
   기록한다. prose, heartbeat, status, report file은 accepted `worker_done`이 아니다.
5. exact terminal/resource를 accounting한 뒤 conflict-free fresh Dispatch로 남은 작업을 재검증한다.

### 5.1 #55 staged-launcher workaround

repository profile worker는 #55 acceptance가 끝날 때까지 packaged `worker-start` 대신
`.orca/scripts/start_task.ps1` 또는 existing Task에 대한 `.orca/scripts/launch_profiles.ps1`을 쓴다.
이 경로는 initial argv bootstrap, exact marker, final idle, cursor-bound injection을 검증하고 startup
또는 Dispatch acceptance 전 실패의 exact terminal을 닫는다.

Dispatch가 수락된 뒤 submission 검증에 실패하면 launcher는 active attempt를 숨기지 않도록 terminal을
보존하고 exact Dispatch ID를 출력한다. coordinator가 `dispatch-show`/terminal transcript를 검사한 뒤
그 exact attempt를 stop/account한다. launcher 성공, first heartbeat, local report는 final completion이
아니며 accepted `worker_done`이 계속 유일한 완료 증거다.

post-Dispatch submission은 pre-Dispatch cursor 뒤에서 기본 30초 동안 bounded 관찰한다. exact
`[Pasted Content N chars]` marker에는 Enter를 한 번만 보내고, marker가 없으면
`UserPromptSubmit`/`Working` evidence를 요구한다. 둘 다 없으면 success를 출력하지 않고 accepted
Dispatch/terminal을 보존해 coordinator inspection으로 넘긴다.

Antigravity에서는 agy 1.1.11의 `--prompt-interactive`를 사용하고 exact worktree absolute path 밖의
search를 금지한다. trust prompt는 launcher가 승인하지 않는다. `codex-trust-workspace` 진단 후 exact
terminal을 닫고, operator가 isolated worktree만 명시적으로 trust한 다음 새 staged attempt를 만든다.
home/sibling checkout 추가, broad trust 저장, `-AllowUnsafe`는 이 recovery에 사용하지 않는다.

## 6. 남은 acceptance

- packaged Orca가 장기 safe worker에서 final mutation을 반복 수락하거나 typed/idempotent recovery를 제공
- packaged `worker-start` initial/release-follow-up 각각 Sol/Terra/Luna 3회 matrix
- `input_accepted` 뒤 agent-session과 PowerShell shell을 구분하는 관측 및 exact resource accounting
- 실패 주입에서 shell과 agent session 구분 및 resource cleanup 검증
- fresh exact-head independent review와 terminal GitHub CI

이 문서와 harness는 fail-closed 진단/완화다. packaged runtime 수정, 물리 검증, 운영자 승인 또는
production authorization을 주장하지 않는다.
