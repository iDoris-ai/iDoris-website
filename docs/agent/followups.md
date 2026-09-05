# Follow-ups ledger（append-only · 永不删行 · 提交进仓库）

> pilot 的 review triage 把「真问题但不阻塞（B）」和延后项记在这里。
> 主线 task 全部完成后，由 `pilot run` 批量合成一个 cleanup PR 做掉，逐条标 [x] done=PR#n。
> `- [ ]`=OPEN，`- [x]`=DONE。GitHub PR comment 是永久兜底。

- [ ] FU-1 · B · src=集成试合 · 2026-09-06 · check.yml 是单文件，多条并行栈各自加步骤必然冲突。拆成 .github/workflows/check-<product>.yml，让独立 PR 不再碰同一个文件
