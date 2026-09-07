# Discovery Sprint 样例 — Baan Rimping Boutique Hotel

> ⚠️ **本样例中的酒店、人名、数字全部虚构**，用于对外演示与内部培训。
> 不含任何真实客户信息。
> 版本：v0.1 · 2026-09-05 · 按 [`../discovery-sop.md`](../discovery-sop.md) 3 天版执行

## 一页摘要

**客户**：Baan Rimping Boutique Hotel，清迈古城，28 间客房，员工 22 人
**服务**：3 天 Discovery Sprint · 35,000 THB
**AI Readiness**：**13 / 25** → 建议从 L1 Skill Pack 起步

### 我们发现了什么

| 排名 | 重复性工作 | 年化工时 | 年化成本（THB） |
|:--|:---|---:|---:|
| 1 | LINE 客户询问回复 | **1,040 h** | 208,000 |
| 2 | OTA 平台内容与促销文案 | 312 h | 78,000 |
| 3 | 泰英菜单与说明翻译 | 156 h | 39,000 |
| 4 | 每日交班记录整理 | 122 h | 24,400 |
| 5 | 月度经营报告 | 96 h | 28,800 |
| | **合计（前五项）** | **1,726 h** | **378,200** |

**一句话**：这家 22 人的酒店，每年有 **1,726 小时**——相当于**接近一个全职员工**——
花在这五件重复的事上。

### 我们建议先做什么

| 位次 | 用例 | 理由 |
|:--|:---|:---|
| 1 | **泰英翻译 Skill** | Effort 2，**一周内见效**，建立信心 |
| 2 | **LINE 回复助手（半自动）** | 价值最大（1,040 h），但需 4 周 |
| 3 | 交班记录 → 结构化 | 战略性：为将来的知识库打底 |

### 我们建议**不要**做什么

- ❌ **不要做全自动 LINE 回复。** 房价和空房状态答错会直接损失订单。
  第一年做半自动（草稿 + 人工放行）就够——8 分钟降到 2 分钟已经是 4 倍。
- ❌ **不要现在接 PMS 系统。** Readiness 的「工具基础」只有 2 分，
  他们的 PMS 没有可用 API（[待核] 现场只确认了「供应商说要另外收费」）。
- ❌ **不要做菜单图片自动生成。** 他们的主厨对出品视觉有强烈意见，
  这里省的时间会被返工吃掉。

### 九项交付物

| # | 文件 |
|:--|:---|
| 0 | [`00-engagement-log.md`](00-engagement-log.md) — 访谈记录、同意、数据边界、风险 |
| 1 | [`01-workflow-map.md`](01-workflow-map.md) — 现状工作流地图 |
| 2 | [`03-readiness-score.md`](03-readiness-score.md) — AI Readiness 五维 |
| 3 | [`02-pain-inventory.md`](02-pain-inventory.md) — 痛点清单（含年化工时）|
| 4 | [`04-use-cases.md`](04-use-cases.md) — Top 3 用例 |
| 5 | [`05-impact-effort-risk.md`](05-impact-effort-risk.md) — 三轴矩阵 |
| 6 | [`prototype/`](prototype/) — 原型 |
| 7 | [`06-data-privacy.md`](06-data-privacy.md) — 数据与隐私 |
| 8 | [`07-roadmap-90d.md`](07-roadmap-90d.md) — 90 天路线图 |
| 9 | [`08-implementation-proposal.md`](08-implementation-proposal.md) — 实施建议与报价 |
