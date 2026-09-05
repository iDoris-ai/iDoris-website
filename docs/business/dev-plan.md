# 基于开源组件的开发计划

> 每个产品用哪些开源件、怎么装配、分几步实现、风险在哪。
> 版本：v0.1 · 2026-09-05
> License 结论全部来自 [`oss-due-diligence.md`](oss-due-diligence.md)（2026-09-05 逐条核实）

## 0. 总原则

**我们不造运行时，只造方法论和装配。**

Agent 运行时、模型网关、文档解析、向量检索、语音、图像——全都有成熟的
Apache/MIT 件。自建等于把有限的时间花在别人已经做完的事上，
而我们的差异化（Discovery 方法论、本地化、交付流程）一分钟也没推进。

**唯一值得自己造的是隔离层**（如 Documents 的 DocIR）——它不是重复实现，
是让底层可替换。

---

## 1. 组件总表

| 组件 | License | 状态 | 用途 | 为什么选它 |
|:---|:---|:---:|:---|:---|
| **LiteLLM** | MIT（`enterprise/` 除外） | ✅ | Gateway 基座 | 自建等于重写别人做了两年的事 |
| **LangGraph** | MIT | ⚠️ | Assistant 状态机 | `interrupt` + checkpointer 正好解决「等人点头」 |
| **Docling** | MIT | ✅ | 文档解析 | 表格与扫描件还原优于 Unstructured；License 更干净 |
| **faster-whisper** | MIT | ✅ | 语音转写 | 本地跑是卖点不是成本（泰国客户数据敏感度高） |
| **pgvector** | PostgreSQL License | ✅ | 向量检索 | 一个 Postgres 撑到很久，**少一个要运维的东西** |
| **line-bot-sdk** | Apache-2.0 | ✅ | LINE 通道 | 官方 SDK |
| **ComfyUI** | **GPL-3.0** | ⚠️ | 图像生成 | **只能独立进程调用** |
| **Pillow** | MIT-CMU | ✅ | 图像后处理 | 裁切/叠字在我们进程内做 |
| ~~n8n~~ | Sustainable Use | ❌ | — | **不是 OSI 开源，禁止转售托管** |
| ~~Dify~~ | 改版 Apache | ❌ | — | **明文禁止多租户** |
| ~~Open WebUI~~ | BSD-3 + 品牌条款 | ❌ | — | >50 用户不得去品牌；且前三个客户不做前端 |

⚠️ = 有硬约束，见 §2。

---

## 2. 三条 License 红线（写死，代码评审执行）

### 2.1 GPL 隔离（ComfyUI）

- ❌ 不 vendor、不 fork 进仓库、不复制片段
- ❌ 不 `import comfy`
- ❌ 不打进同一容器镜像作为同一进程
- ✅ 独立服务部署，HTTP 调用
- ✅ 我们的 workflow JSON 是数据不是代码，可自有

> **任何 PR 引入 `import comfy` 或把 ComfyUI 代码复制进仓库，一律拒绝合并。**
> 越线后果：整个 iDoris Core 被传染成 GPL-3.0，所有商业交付代码必须开源，
> 且**不可逆**——发行过一次就覆水难收。

### 2.2 LiteLLM 的 `enterprise/` 目录

[已核] LICENSE 原文：`enterprise/` 目录另有许可，其余 MIT。
**绝不引用该目录下任何代码。** 每次升级检查该目录的新增文件。

### 2.3 模型权重的许可独立于代码

**这是本次尽调最大的未解决项。** 代码 MIT 不代表权重可商用。

| 权重 | 状态 | 阻塞什么 |
|:---|:---|:---|
| 图像生成模型 | **[待核]** | **Creative 图像部分不对外交付** |
| Whisper large-v3 | **[待核]** | Voice 商业交付 |
| Docling OCR/版面模型 | **[待核]** | Documents 商业交付 |

**降级路径**：Creative 先只上 `copy`（纯文案，零 License 风险）。

---

## 3. 分阶段实现路径

### 阶段 A — 让 Discovery 能跑（可立即开始）

**目标**：我们自己做 Discovery 时用得上，不依赖任何未完成的产品。

| 步 | 做什么 | 用什么 | 产出 |
|:--|:---|:---|:---|
| A1 | **Voice 现状盘点** | 读代码 | 盘点报告：用的哪个实现、泰语调过没、有没有 demo 入口、部署形态 |
| A2 | Gateway 最小版 | LiteLLM | 统一入口 + 三档路由 + 审计写 Postgres |
| A3 | Voice 泰语评测 | faster-whisper | 20 段真实音频的 CER 报告，**按场景分层** |

**A1 必须最先做。** 整个 Kit 的演示计划建立在「Voice 已有基础」这个假设上，
**不能在假设上继续叠设计**。

### 阶段 B — 一条端到端（第一个能演示的东西）

| 步 | 做什么 | 用什么 | 产出 |
|:--|:---|:---|:---|
| B1 | LangGraph 离线验证 | LangGraph | **断网容器抓包确认零出网** ← 阻塞项 |
| B2 | Assistant 骨架 | LangGraph + Postgres | 通用流程骨架 + 审批队列接口 |
| B3 | 「会议→纪要→任务」 | Voice + Assistant | 一条可演示的端到端 |

**B1 是硬阻塞。** [已核] LangGraph 经 `langchain-core` 传递依赖 `langsmith`，
包一定会被装上。**[待核] 不设任何环境变量时是否零出网**——
客户的会议内容是最敏感的数据，「大概不会上传」不是可接受的答案。
不通过就自建状态机（约 2–3 天，远低于数据外流的代价）。

### 阶段 C — 客户第一次真正用上

| 步 | 做什么 | 用什么 | 产出 |
|:--|:---|:---|:---|
| C1 | DocIR 隔离层 | 自建 | 稳定中间表示，六个动作只依赖它 |
| C2 | Documents `extract` | Docling + Gateway | 含泰历转换（**代码判历法，不让模型算**） |
| C3 | Documents `translate` | Docling + Gateway | 含专有名词保留、敬语 `formality` 参数 |
| C4 | Creative `copy` | Gateway | 纯文案，**零 License 风险，可先交付** |

### 阶段 D — 等前置解除

| 步 | 等什么 |
|:--|:---|
| Creative 图像 | 权重许可核清 |
| Documents `search` | pgvector + 泰文分块策略调优 |
| LINE Agent | Assistant 骨架稳定 + LINE 平台条款核清 |
| Skill Pack | Starter Kit 组件能跑 |
| Managed AI 面板 | **有 ≥3 个运维客户** |

---

## 4. 技术选型取舍记录

写下来是为了以后有人问「为什么不用 X」时不用重新吵一遍。

| 决策 | 选择 | 放弃的 | 理由 |
|:---|:---|:---|:---|
| Agent 编排 | LangGraph | Dify / n8n | **Dify 禁多租户、n8n 禁转售托管**（均 [已核]） |
| 模型网关 | LiteLLM | 自建 | 自建等于重写别人做了两年的事 |
| 向量库 | pgvector | Qdrant / Milvus | 少一个要运维的东西；撑不住再换，换的成本低于现在多养一个服务 |
| 文档解析 | Docling | Unstructured | 表格与扫描件更好，MIT 更干净 |
| 语音 | faster-whisper（本地） | 云 API | 泰语数据敏感度高，**本地跑是卖点不是成本** |
| 图像 | ComfyUI 独立服务 | 集成进主程序 | GPL 传染 |
| 前端 | **不做** | Open WebUI | 前三个客户不需要；且 >50 用户不得去品牌 |
| 说话人分离 | **不做**（第一版） | pyannote | 权重许可要单独核 + 多人会议准确率不稳定 |

**「前端不做」尤其重要**：做前端是最容易看起来很忙但不产生客户价值的事。

---

## 5. 风险汇总

| 风险 | 概率 | 影响 | 对策 |
|:---|:---:|:---|:---|
| LangGraph 无法完全离线 | 中 | Assistant 不能进客户环境 | B1 先验；不过就自建状态机 |
| 图像权重不可商用 | 中 | Creative 图像砍掉 | 先只上 `copy` |
| Voice 现状与假设不符 | 中 | Kit 演示计划要改 | A1 先盘点，不在假设上叠设计 |
| 泰语 CER 高到不可用 | 中 | Voice 不能当入口 | A3 先评测再定去留 |
| LiteLLM 功能挪进 `enterprise/` | 低 | 要改架构 | 每次升级检查；必要时锁版本 |
| 范围蔓延（客户要全公司文档搜索） | **高** | 交付失控 | 边界写死在各组件设计里 |

**「范围蔓延」概率标高不是悲观，是经验**：`search` 的边界、
Assistant 的自动放行、Creative 的「替代设计师」预期——
这三处客户一定会推，**对策必须在合同和演示话术里，不能等到实施阶段才说不**。
