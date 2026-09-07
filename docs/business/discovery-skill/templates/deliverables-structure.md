# 九项交付物：目录与文件名

**固定。** 格式一致才能横向比较，才能沉淀成资产。

```
sample-discovery-<客户代号>/
├── README.md                      # 串起全部九项 + 一页摘要
├── 00-engagement-log.md           # 谁、何时、说了什么、同意记录、数据边界、风险
├── 01-workflow-map.md             # ① 现状工作流地图（Mermaid 泳道图 + 耗时表）
├── 02-pain-inventory.md           # ③ 痛点清单（含年化工时与成本）
├── 03-readiness-score.md          # ② AI Readiness 五维评分
├── 04-use-cases.md                # ④ Top 3 用例
├── 05-impact-effort-risk.md       # ⑤ 三轴矩阵与排序
├── 06-data-privacy.md             # ⑦ 数据与隐私风险
├── 07-roadmap-90d.md              # ⑧ 90 天路线图（30/60/90 三段，每段可验收）
├── 08-implementation-proposal.md  # ⑨ 实施建议与报价
└── prototype/                     # ⑥ 原型（代码，或录屏 + 说明）
    └── README.md
```

## 缺一项不算交付

原型若因时间盒到点而降级成录屏，`prototype/README.md` 里**必须写明这是模拟不是实物**。
不许含糊过去。

## `01-workflow-map.md` 的硬要求

每条流程一张 Mermaid 泳道图，**图下必须跟一张表**：

| 步骤 | 谁做 | 耗时 | 用什么工具 | 是否重复 |
|:---|:---|---:|:---|:---:|

**没有耗时的流程图是装饰品。**

## `07-roadmap-90d.md` 的硬要求

30 / 60 / 90 三段，每段必须有**可验收的产出**。
不许出现「持续优化」「逐步推广」这类不可验收的话。
