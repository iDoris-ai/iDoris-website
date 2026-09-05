# 验证脚本

> 用来把 `docs/business/facts-to-verify.md` 里的 [待核] 变成 [已核] 的**可重跑证据**。
> 结论写在文档里，**证据留在这里**——三个月后有人质疑，能重跑一遍。

## `langgraph-egress-probe.py` + `langgraph-egress-control.py`

**回答的问题**（P0 #1）：LangGraph 在不设任何 `LANGSMITH_*` / `LANGCHAIN_*`
环境变量时，是否有任何出网请求？

**为什么重要**：LangGraph 经 `langchain-core` 传递依赖 `langsmith`，
包一定会被装上。而 Assistant 处理的是客户的会议内容与客户消息——
**最敏感的数据**。「大概不会上传」不是可接受的答案。

### 怎么跑

```bash
uv venv --python 3.12 .venv
VIRTUAL_ENV=.venv uv pip install langgraph
.venv/bin/python langgraph-egress-probe.py     # 主验证
.venv/bin/python langgraph-egress-control.py   # 正对照
```

### 方法

在 `socket` 层打桩，记录所有 `connect` / `connect_ex` / `getaddrinfo`，
并**拒绝**任何非本机目标。这比抓包更严格：任何试图出网的行为都会被记录且失败，
不会被静默重试掩盖。

跑的是一个**带人工审批断点**（`interrupt` + checkpointer）的真实流程，
不是空转——因为断点恢复正是 Assistant 依赖 LangGraph 的唯一理由。

### 为什么必须有正对照

**一个抓不到出网的探针，它报的「零出网」什么都不证明。**

`control.py` 验证三件事：直接 HTTP 请求会被抓到 · 本机连接不被误拦 ·
**开启 `LANGSMITH_TRACING` 后确实会变红**。

三条都过，主验证的「零出网」才是可信读数。

> 这条纪律来自本仓库 2026-09-05 的教训：所有检查全绿，但结论集体错了。
> **一致性证明不了正确性。**
