# Orca Worker Done Report Template

활성 Dispatch가 주입한 lifecycle preamble의 `worker_done` 명령 전체가 유일한 권위입니다. 저수준 staged Dispatch는 `--from`과 `--dispatch-capability`를 요구할 수 있고 supervised worker는 이를 생략할 수 있으므로, 과거 명령이나 아래 보고서 양식에서 lifecycle 플래그를 추가·삭제·재구성하지 마십시오. 주입된 명령의 placeholder만 실제 값으로 바꾸고 exactly one `worker_done`을 보냅니다.

```text
subject: <type>(<component>): <short summary>
body: <exactly 3 sentences: what changed, what was verified, and what remains>
outcome: <succeeded|failed>
files-modified: <comma-separated file list; empty for read-only work>
report-path: <optional artifact path>
```
