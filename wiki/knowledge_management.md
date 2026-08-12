---
title: smart-gatekeeper knowledge management
type: governance
project: smart-gatekeeper
status: active
updated: 2026-08-12
source_of_truth: true
---

# Obsidian·LLM 위키 운영 규칙

## 1. 진실 공급원

이 Git 저장소의 Markdown이 프로젝트 지식의 진실 공급원이다. Obsidian은 편집·검색·backlink UI이며 별도 데이터베이스가 아니다.

- 프로젝트 현재 사실, 결정, 테스트, 사건: 이 저장소
- 원본 사양과 초기 BOM: `raw/` 읽기 전용
- 여러 프로젝트에 재사용할 원칙: `E:\knowledge-hub\knwlege-hub`
- 코드 동작: 실제 source와 tests가 최종 근거이며 wiki는 이를 설명하고 라우팅한다.

## 2. 문서 유형과 상태

새 문서부터 YAML frontmatter를 적용한다. 기존 문서는 내용 변경이 있을 때 점진적으로 전환하며, frontmatter만 추가하기 위한 대량 변경은 하지 않는다.

```yaml
---
title: 문서 제목
type: reference
project: smart-gatekeeper
status: active
updated: YYYY-MM-DD
source_of_truth: true
applies_to:
  - target
---
```

허용 `type`:

| type | 용도 |
|---|---|
| `reference` | 현재 구조와 설정 |
| `decision` | 채택한 선택과 근거 |
| `proposal` | 아직 승인·배포되지 않은 설계 |
| `runbook` | 설치·배포·복구 절차 |
| `incident` | 사건 시점의 관측과 원인 |
| `test` | 시험 조건·결과·증거 |
| `governance` | 문서·릴리스 운영 규칙 |

허용 `status`: `draft`, `proposed`, `active`, `superseded`, `deprecated`.

## 3. 세 개의 사실 축

문서는 다음을 한 문장에 섞지 않는다.

1. **Repository implementation**: 현재 checkout에 코드가 존재함.
2. **Verified evidence**: 특정 commit/artifact/environment에서 시험을 통과함.
3. **Deployed state**: 특정 현장 기기에 실제 설치되어 관측됨.

“구현됨”은 “실기기 검증됨”이나 “배포됨”을 뜻하지 않는다. 문서에는 가능한 경우 commit, artifact, run ID, Target version/boot ID 중 관련 식별자를 적는다.

## 4. 링크와 파일 배치

- 저장소 내부 링크는 GitHub와 LLM도 읽을 수 있는 상대 Markdown 링크를 사용한다.
- 문서 이름은 `snake_case.md`를 유지한다.
- 현재는 기존 링크와 trusted digest를 보존하기 위해 파일을 대량 이동하지 않는다.
- 새 사건은 `*_incident_YYYY_MM_DD.md`, 새 결정은 `*_adr.md` 또는 명확한 decision 제목을 사용한다.
- `wiki/index.md`는 모든 프로젝트 문서의 사람·LLM 공통 라우터다.
- `wiki/log.md`는 append-only이며 과거 내용을 현행 사실로 해석하지 않는다.

## 5. Hub 승격 규칙

다음 조건을 만족할 때만 공통 Hub로 승격한다.

- 두 프로젝트 이상에서 재사용 가능하거나 기술 독립적인 운영 원칙이다.
- 프로젝트 이름, 비밀, 실제 URL, 기기 ID와 현장 상태를 제거해도 의미가 유지된다.
- Hub 문서에 `origin_project`, `origin_path`, `promoted_from_commit`을 기록한다.
- Hub에는 원칙을 요약하며 프로젝트 문서를 그대로 복제하지 않는다.
- 프로젝트별 현재 값과 증거의 진실 공급원은 계속 프로젝트 저장소에 둔다.

현재 승격 항목은 Hub의 `projects/smart-gatekeeper.md`에서 역추적한다.

## 6. Obsidian 설정

Vault root는 저장소 root다. `.git`, `.pio`, build, `dist`, `node_modules`, `.venv`, `.dart_tool`은 검색에서 제외한다. 개인 UI 상태인 `.obsidian/workspace*.json`, cache와 trash는 Git에 포함하지 않는다.

문서 구조가 Dataview나 community plugin 없이는 보이지 않는 상태가 되면 안 된다. `wiki/index.md`와 표준 Markdown만으로 전체 탐색이 가능해야 한다.

## 7. 작업 종료 체크리스트

1. `wiki/index.md`와 최근 `wiki/log.md`를 읽는다.
2. 코드·테스트·배포 상태를 분리해 확인한다.
3. 관련 문서를 갱신한다.
4. 새 문서를 index에 연결한다.
5. `wiki/log.md`에 append한다.
6. 상대 링크, UTF-8/LF, `raw/` 불변, append-only prefix를 검사한다.
7. 문서의 구현/검증/배포 표현이 증거보다 강하지 않은지 확인한다.
