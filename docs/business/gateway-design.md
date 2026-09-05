# iDoris AI Gateway 设计

> 基座 LiteLLM，我们加的是**路由策略、成本闸、审计留痕**。
> 版本：v0.1 · 2026-09-05 · License 结论见 [`oss-due-diligence.md`](oss-due-diligence.md) §1.1

## 0. 一条硬约束

**绝不引用、复制、依赖 LiteLLM 的 `enterprise/` 目录下任何代码。**

[已核] LiteLLM 的 LICENSE 原文：`enterprise/` 目录另有许可，其余为 MIT。
我们只用核心的模型路由与统一 API。**这条要进 Gateway 的代码评审清单。**

[待核] 每次升级 LiteLLM 时检查我们用到的功能是否被挪进 `enterprise/`。
核法：`git log --stat` 看该目录新增文件。

## 1. 它解决什么

不是「省钱买 token」。是这四件：

| 能力 | 没有 Gateway 会怎样 |
|:---|:---|
| **模型路由** | 每个组件各自硬编码模型名，换模型要改代码 |
| **成本可见** | 客户不知道每次调用花了多少，也就不敢放量 |
| **成本闸** | 一个死循环的 Agent 能在一夜之间烧掉一个月预算 |
| **审计留痕** | 出了问题查不出是谁、什么时候、用哪个模型做的 |

**价值不在 token 本身，在成本优化 + 模型路由 + 隐私 + 便利 + 管理。**

## 2. 不可破的边界

> **Gateway 绝不存储客户业务数据的内容，只存元数据。**

存：时间、用户、组件、任务类型、模型、token 数、成本、延迟、成败。
不存：提示词内容、模型输出内容、上传的文档。

理由：Gateway 是我们托管的、跨客户的组件。一旦它存内容，
它就成了一个集中的客户数据库——**那是我们最不想承担的责任**。
内容留在客户侧或客户指定的存储。

## 3. 路由策略表

路由是**数据不是代码**，可按客户覆盖：

```jsonc
{
  "tenant": "hotel-xxx",
  "rules": [
    {"task": "translate",  "tier": "cheap"},
    {"task": "extract",    "tier": "cheap",   "require": {"strict_schema": true}},
    {"task": "summarize",  "tier": "mid"},
    {"task": "rewrite",    "tier": "mid"},
    {"task": "compare",    "tier": "premium", "reason": "漏一条合同差异代价很高"},
    {"task": "search.answer", "tier": "mid"},
    {"task": "*",          "sensitivity": "high", "tier": "local", "override": true}
  ],
  "tiers": {
    "local":   {"models": ["<本地部署模型>"]},
    "cheap":   {"models": ["<低价档>"]},
    "mid":     {"models": ["<中档>"]},
    "premium": {"models": ["<高档>"]}
  }
}
```

**两条设计要点**：

1. **`sensitivity: high` 的规则带 `override`，优先级高于任务类型。**
   敏感任务无论多简单都走本地/私有模型。这是隐私承诺的机械保障，不能靠人记得。
2. **tier 里放的是模型列表不是单个模型。** 模型会下线、会涨价、会被更好的取代——
   `tiers` 是唯一需要改的地方，业务代码永远只说 "cheap"。

**具体填哪些模型型号故意留空**：模型换代极快，写死在设计文档里三个月就过期。
实际配置在部署时的 `tiers.json`，并由 `/pricing` 页面的牌价表提供选型依据。

## 4. 成本闸

三层，从软到硬：

| 层 | 触发 | 动作 |
|:---|:---|:---|
| 提醒 | 月度用量达 70% | 通知管理员 |
| 降级 | 达 90% | 非 `premium` 任务强制降到 `cheap` |
| 硬停 | 达 100% | 拒绝新请求，返回明确错误 |

**按部门/项目配额**，不只是全局。理由：一个部门的实验不该烧掉另一个部门的预算。

**硬停必须是真的停。** 见过太多「预算告警」最后变成没人看的邮件。

## 5. 审计留痕

```jsonc
{
  "ts": "2026-09-05T10:23:45Z", "tenant": "hotel-xxx", "user": "staff-07",
  "component": "documents", "task": "extract", "sensitivity": "normal",
  "tier": "cheap", "model": "<实际模型>", "tokens": {"in": 3200, "out": 450},
  "cost_usd": 0.0021, "latency_ms": 1840, "status": "ok"
}
```

这条记录同时服务三个目的：**客户看成本**、**我们做优化**、**出事能追溯**。

## 6. BYOK

客户已有模型订阅时，用他们的 key。**这是差异化不是让步**——
「我们不锁定你」在企业采购里是很强的说服力。

实现：`tiers` 里的凭据支持指向客户提供的 key。
**客户的 key 加密存储，且我们的日志绝不记录 key 本身。**

## 7. 最小可用形态

第一版只做三件：
1. 统一入口 + 路由表（tier 三档：cheap / mid / local）
2. 审计记录写 Postgres
3. 月度用量查询接口

**不做**：成本闸（等有真实用量再做）、BYOK（等有客户要求）、premium 档
（第一批用例用不上）。

## 8. 风险

| 风险 | 对策 |
|:---|:---|
| LiteLLM 把功能挪进 `enterprise/` | [待核] 每次升级检查；必要时锁版本 |
| 路由表配错导致敏感数据发到云端 | `sensitivity: high` 走 override；配置变更需评审 |
| 成本记录与厂商账单对不上 | 每月抽样核对；差异 >5% 要查 |
| Gateway 成为单点故障 | 第一版接受（客户量小）；有真实依赖后再做冗余 |
