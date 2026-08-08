# Orca Worker Done Report Template

현재 Dispatch가 주입한 lifecycle preamble이 권위 있는 명령입니다. 아래 placeholder를 그 preamble의 정확한 Task/Dispatch 값으로 치환하십시오. 현재 CLI에서는 워커 identity와 capability를 명령 인자로 다시 보내지 않습니다.

```bash
orca orchestration send --type worker_done \
  --subject "<type>(<component>): <short summary>" \
  --body "<3 sentences: what changed, what was verified, and what remains>" \
  --task-id <task_id> \
  --dispatch-id <dispatch_id> \
  --outcome succeeded \
  --files-modified "<comma-separated file list>" \
  --json
```
