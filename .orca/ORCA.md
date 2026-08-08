# .orca/ORCA.md — Orca Multi-Agent Orchestration Master Guide
> **Smart Gatekeeper Orca Multi-Agent Architecture & Profile System**
> **Last updated**: 2026-08-08

---

## 1. 개요 (Overview)

이 지침서는 Orca Multi-Agent 오케스트레이션 엔진을 통해 `smart-gatekeeper` 프로젝트를 체계적이고 효율적으로 수행하기 위한 **4대 에이전트 프로파일 (`gpt5.6-sol`, `gpt5.6-terra`, `gpt5.6-luna`, `antigravity`)** 의 역할 분담, 설정 및 실행 워크플로우를 정의합니다.

모든 에이전트는 추론 깊이와 정확도를 극대화하기 위해 **`effort: high`** 로 고정 설정됩니다.

---

## 2. 에이전트 프로파일 구조 (Profile Roles & Responsibilities)

| 프로파일 | 에이전트 이름 | CLI 커맨드 | 주요 담당 영역 | 모델 & Effort | 설정 파일 |
|---|---|---|---|---|---|
| **`gpt5.6-sol`** | **Sol** | `codex --model gpt-5.6-sol -c model_reasoning_effort="high" ...` | 총괄 코디네이터, 아키텍처 설계, 작업 분할(DAG), PR 검토 및 최종 Merge 승인 | `gpt-5.6-sol` (Effort: `high`) | [gpt5.6-sol.md](profiles/gpt5.6-sol.md) |
| **`gpt5.6-terra`** | **Terra** | `codex --model gpt-5.6-terra -c model_reasoning_effort="high" ...` | ESP32-C6 펌웨어 (C++/PlatformIO/GATT/ToF/Relay) & 백엔드 (FastAPI/DB/MQTT/ACL Push) | `gpt-5.6-terra` (Effort: `high`) | [gpt5.6-terra.md](profiles/gpt5.6-terra.md) |
| **`gpt5.6-luna`** | **Luna** | `codex --model gpt-5.6-luna -c model_reasoning_effort="high" ...` | Android Native (Kotlin/WorkManager/BLE Wake) & Flutter Thin UI & QA/E2E Fault Injection | `gpt-5.6-luna` (Effort: `high`) | [gpt5.6-luna.md](profiles/gpt5.6-luna.md) |
| **`antigravity`** | **Antigravity** | `agy --dangerously-skip-permissions --effort high` | 시니어 풀스택 리드 & 크로스레이어 해결 / 비상 태스크 인수 직행 실행 | 실행 시 `agy`가 선택한 지원 모델 (Effort: `high`) | [antigravity.md](profiles/antigravity.md) |

> ⚡ **무승인 자동 수행 (YOLO Mode) 설정**:
> - **Codex 워커 (`codex`)**: `--dangerously-bypass-approvals-and-sandbox` 옵션으로 승인과 sandbox를 우회합니다. 현재 CLI는 이 옵션과 `--ask-for-approval never`의 동시 사용을 거부하므로 함께 넘기지 않습니다.
> - **Antigravity 워커 (`agy`)**: `--dangerously-skip-permissions` 옵션을 통해 모든 도구 호출 권한 요청을 프롬프트 없이 즉시 승인합니다.

> `codex --profile`은 `$CODEX_HOME/<name>.config.toml` 계층만 로드하며 Markdown 역할 파일을 받지 않습니다. Codex의 추론 강도는 `--effort`가 아니라 `-c model_reasoning_effort="high"`로 지정합니다. `agy`는 `--effort high`를 지원하지만 Markdown용 `--profile` 옵션은 지원하지 않습니다. 따라서 런처는 지원되는 CLI argv로 TUI를 만든 뒤 `terminal send`로 역할 문서를 읽게 하고, `tui-idle`을 다시 확인한 후 Task를 주입합니다.




---

## 3. Orca 오케스트레이션 표준 워크플로우

```mermaid
graph TD
    User["사용자 Request"] --> Sol["gpt5.6-sol (Coordinator)"]
    Sol -->|"task-create & dispatch"| Terra["gpt5.6-terra (Firmware & Backend)"]
    Sol -->|"task-create & dispatch"| Luna["gpt5.6-luna (Android & Flutter & QA)"]
    Terra -->|"worker_done + evidence"| Sol
    Luna -->|"worker_done + evidence"| Sol
    Sol -->|"PR Review & Gate Check"| Merge["main Merge & Deploy"]
```

### 3.1 코디네이터 (`gpt5.6-sol`) 실행 수칙
1. **Run & Task 생성**: `orca orchestration run-create` 및 `task-create`로 작업 명세 정의
2. **워커 터미널 디스패치**:
   - `gpt5.6-terra` 워커 실행: `.orca/scripts/launch_profiles.ps1 -Profile gpt5.6-terra -TaskID <task_id>`
   - `gpt5.6-luna` 워커 실행: `.orca/scripts/launch_profiles.ps1 -Profile gpt5.6-luna -TaskID <task_id>`
3. **모니터링**: `orca orchestration check --wait --types worker_done,escalation,question --timeout-ms 60000 --json`을 rolling window로 반복합니다. timeout 또는 `state: ready`는 완료가 아닙니다.
4. **완료 처리**: 각 `worker_done`을 검토한 뒤 `worker-release` 또는 즉시 재사용을 결정하고, Delivery를 처리한 뒤 ACK합니다.
5. **검증 & 병합**: 로컬/CI/물리 증거를 분리하고, 독립 리뷰와 사용자 병합 권한이 모두 있을 때만 병합합니다. 구현 워커가 자신의 PR을 승인하거나 자동 병합하지 않습니다.

### 3.2 워커 (`gpt5.6-terra`, `gpt5.6-luna`) 공통 작업 수칙

1. **작업 전 지침 이수**: `AGENTS.md`, `wiki/index.md`, 최신 `wiki/log.md`, 관련 wiki 문서 필독
2. **코드 변경 및 검증**: 담당 파트 수정 후 관련 unit test / build 실행 (Host C++, Python, Flutter, PlatformIO)
3. **지식베이스 동기화**: `wiki/` 문서 업데이트 및 `wiki/log.md` Append-only 기록
4. **`worker_done` 송신**: 문서의 고정 명령을 복사하지 말고 현재 Dispatch가 주입한 정확한 `--from`, `--dispatch-capability`, Task/Dispatch ID를 사용합니다.
   ```bash
   orca orchestration send --from <injected_worker_handle> --dispatch-capability <injected_capability> \
     --type worker_done --subject "<작업 완료 제목>" \
     --body "<무엇을 했는지, 무엇을 확인했는지, 무엇이 남았는지 3문장>" --task-id <task_id> --dispatch-id <dispatch_id> \
     --outcome succeeded --files-modified "<수정 파일 목록>" --json
   ```

---

## 4. 핵심 안전 불변 조건 (Safety Invariants)

1. **2단계 승인 게이트 구조 유지**:
   - `G0-SW` (소프트웨어 Release Candidate 게이트): 정확한 후보 SHA와 현재 증거 묶음에 대해 검증된 경우에만 `passed`; 그 외에는 `pending / fail-closed`
   - `G0-HW` (물리 장비 검증 게이트): 실기기 연결 전까지 상시 차단 (`pending / fail-closed`)
2. **OTA P0 비회귀 계약**:
   - 모바일 앱 업데이트 매니저 및 Target dual-slot rollback 경로 독립성 유지
3. **중복 ARM 방지**:
   - Hardwareless GATT 로컬 인증과 Legacy REST Pre-arm 간 인터락 유지
