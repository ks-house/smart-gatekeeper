# Orca Worker Done Report Template

```bash
orca orchestration send --type worker_done \
  --subject "<type>(<component>): <short summary>" \
  --body "1. Implemented <feature/fix details>\n2. Verification: <test and build results>\n3. Documentation: updated wiki/<page>.md and appended wiki/log.md" \
  --task-id <task_id> \
  --dispatch-id <dispatch_id> \
  --outcome succeeded \
  --files-modified "<space separated file list>" \
  --json
```
