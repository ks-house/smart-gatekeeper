# Orca Worker Done Report Template

현재 Dispatch가 주입한 lifecycle preamble이 권위 있는 명령입니다. 아래 placeholder를 그 preamble의 정확한 값으로 치환하고, 오래된 capability를 복사하거나 추측하지 마십시오.

```bash
orca orchestration send --from <injected_worker_handle> --dispatch-capability <injected_capability> --type worker_done \
  --subject "<type>(<component>): <short summary>" \
  --body "<3 sentences: what changed, what was verified, and what remains>" \
  --task-id <task_id> \
  --dispatch-id <dispatch_id> \
  --outcome succeeded \
  --files-modified "<comma-separated file list>" \
  --json
```
