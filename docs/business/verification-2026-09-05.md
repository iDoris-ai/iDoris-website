# P0 阻塞项验证报告 — 2026-09-05

> 把 [`facts-to-verify.md`](facts-to-verify.md) 里 5 条 P0 中的 **3 条**变成 [已核]。
> 证据脚本在 [`../../tools/verify/`](../../tools/verify/)，可重跑。

## 结论摘要

| # | P0 断言 | 结论 | 状态 |
|:--|:---|:---|:---|
| 1 | LangGraph 完全离线时零出网 | **成立，但有前提** | ✅ [已核] |
| 4 | Whisper 模型权重可商用 | **可商用** | ✅ [已核] |
| 5 | Docling OCR/版面模型权重可商用 | **可商用** | ✅ [已核] |
| 2 | 图像生成模型权重可商用 | **仍待核** —— 尚未选定具体模型 | ⏳ |
| 3 | Voice 组件现状 | **仍待核** —— 需读 iDoris 代码仓库 | ⏳ |

---

## P0 #1 · LangGraph 出网行为 —— ✅ 已核，但结论带前提

### 方法

在 `socket` 层打桩，记录并**拒绝**所有非本机连接（含 DNS 解析），
跑一个带 `interrupt` 人工审批断点 + checkpointer 的真实流程。

**并做了正对照**——因为一个抓不到出网的探针，它报的「零出网」什么都不证明。

### 结果

| 场景 | 外部连接尝试 | 判定 |
|:---|---:|:---|
| **不设任何环境变量** | **0** | ✅ 零出网 |
| 正对照：直接发 HTTP 请求 | 1 | ✅ 探针能抓到 |
| 正对照：连本机 | 0（放行）| ✅ 无假阳性 |
| **正对照：设 `LANGSMITH_TRACING=true`** | **2** | ⚠️ **确实会出网** |

开启追踪时的报错原文显示它试图访问
`api.smith.langchain.com` 的 `/info` 与 `/runs/multipart`。

### 结论与可执行的控制手段

**LangGraph 本身不主动出网。** 但它**会**在环境变量存在时上报——
所以风险不在库，在**部署配置**。

**因此不是「可以放心用」，而是「必须机械保证那些变量不存在」**：

1. 部署清单里显式 `unset LANGSMITH_TRACING LANGSMITH_API_KEY LANGCHAIN_TRACING_V2 LANGCHAIN_API_KEY`
2. **服务启动时加一条断言**：检测到任何 `LANGSMITH_*` / `LANGCHAIN_*` 变量就**拒绝启动**，
   而不是打个警告——警告没人看
3. 客户环境部署前跑一次 `tools/verify/langgraph-egress-probe.py`

**降级路径不再需要**：原计划「若不通过就自建状态机（2–3 天）」可以取消。

---

## P0 #4 · Whisper 模型权重 —— ✅ 可商用

| 对象 | 许可 | 来源 |
|:---|:---|:---|
| `openai/whisper`（代码）| **MIT** | GitHub API |
| `openai/whisper-large-v3`（权重）| **Apache-2.0** | HuggingFace API |
| `Systran/faster-whisper-large-v3`（转换后权重）| **MIT** | HuggingFace API |

**我们实际要用的是 `Systran/faster-whisper-large-v3`（MIT）**，无商用限制。

---

## P0 #5 · Docling 模型权重 —— ✅ 可商用

| 对象 | 许可 | 来源 |
|:---|:---|:---|
| `ds4sd/docling-models`（版面/表格）| **CDLA-Permissive-2.0 + Apache-2.0** | HuggingFace API |
| `ds4sd/DocumentFigureClassifier` | **MIT** | HuggingFace API |

CDLA-Permissive-2.0 是宽松的数据许可，允许商用与再分发。

**[待核] 剩余一项**：Docling 若启用外部 OCR 引擎（EasyOCR / Tesseract），
那些是独立依赖，许可需另核。**对策**：第一版**只用 Docling 自带模型**，
不启用外部 OCR 引擎。

---

## 仍然阻塞的两条

### P0 #2 · 图像生成模型权重

**无法现在核，因为还没选定具体模型。**

这不是拖延——`starter-kit/creative.md` 已经写死了降级路径：
**先只上 `copy`（纯文案，零 License 风险）**，图像部分等选型后再核。

**选型时的核法**：找到权重的 HuggingFace 页或发布页，
读 `cardData.license`，**特别看 commercial use 条款**——
图像模型是许可差异最大的一类，有的明确禁商用。

### P0 #3 · Voice 组件现状

**需要读 iDoris 的代码仓库**，不在本仓库内。

这条是 Dev 入职第一周的第一件事（见 `onboarding-day1.md` §4）。
在它核清之前，**Starter Kit 的演示计划建立在一个未经验证的假设上**。

---

## 这份报告自己的可信度

- 三条结论都有**可重跑的证据**：脚本在 `tools/verify/`，API 查询命令在上表的「来源」列
- P0 #1 **做了正对照**，证明探针能变红
- **没有把「探针没报警」直接当成「安全」**——而是查清了它在什么条件下会报警，
  并据此给出机械的控制手段

> 本轮开始时 P0 有 5 条，现在剩 2 条，且两条都有明确的下一步动作与降级路径。
