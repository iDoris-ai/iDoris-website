# 开源组件尽调

> `research.md` 那张表逐行做实。**每一条都标 [已核] 或 [待核]，没有第三种。**
> 核实日期：2026-09-05 · 方法：GitHub API 取 `LICENSE` 原文 + PyPI 取版本与依赖
>
> **这份文档纠正了 `research.md` 的两处错误。** 见 §0。

---

## 0. 纠正 research.md 的两处错误

调研的价值就在这里——**不核就会把假设当事实往下传**。

| 项 | research.md 原写 | 实际 | 影响 |
|:---|:---|:---|:---|
| **LiteLLM** | `MIT` | **MIT，但 `enterprise/` 目录另有许可** | Gateway 基座。必须确保不引用 `enterprise/` 下任何代码 |
| **Dify** | 「Apache 2.0（含品牌与多租户附加条款，商用前须逐条读）」 | **明文禁止多租户，除非获书面授权** | 我们托管多客户＝多租户＝**被禁止**。已排除是对的，但理由要写准 |

第一条尤其值得记：`research.md` 写「MIT」时我没核，是凭印象。
GitHub 对 LiteLLM 返回的是 `NOASSERTION`——**这个信号本身就说明许可不是标准的**。

---

## 1. 我们要用的组件（结论：可用）

### 1.1 LiteLLM — Gateway 基座

| 项 | 值 |
|:---|:---|
| 仓库 | `BerriAI/litellm` |
| SPDX | **[已核]** `NOASSERTION` ← GitHub 无法归类，因为是复合许可 |
| 实际条款 | **[已核]** 原文：「All content that resides under the `enterprise/` directory … is licensed under the license defined in `enterprise/LICENSE`. Content outside … is available under the MIT license」 |
| 最新版本 | **[已核]** `1.99.0`，发布于 2026-09-01（活跃） |
| PyPI license 字段 | **[已核]** `MIT`（**与仓库不完全一致，以仓库 LICENSE 为准**） |

**我们的用法是否踩线**：不踩，**但有一条硬约束**——

> **绝不引用、复制、依赖 `enterprise/` 目录下的任何代码。**
> 我们只用核心的模型路由与统一 API。这条要写进 Gateway 的代码评审清单。

**风险**：这类「核心 MIT + enterprise 目录另计」的结构，厂商有可能逐步把功能
挪进 `enterprise/`。**[待核] 每次升级 LiteLLM 时检查我们用到的功能是否被挪走。**
核法：`git log --stat` 看 `enterprise/` 目录的新增文件。

---

### 1.2 LangGraph — Assistant 的状态机

| 项 | 值 |
|:---|:---|
| 仓库 | `langchain-ai/langgraph` |
| SPDX | **[已核]** `MIT` |
| 最新版本 | **[已核]** `1.2.11`，`langgraph-checkpoint 4.2.0`（2026-08-07，活跃） |
| 直接依赖 | **[已核]** `langchain-core`、`langgraph-checkpoint`、`langgraph-prebuilt`、`langgraph-sdk`、`pydantic`、`xxhash` |

**⚠️ 关键发现（回答 `starter-kit/assistant.md` 里那条 [待核]）**：

> LangGraph **不直接**依赖 LangSmith，但经 `langchain-core 1.6.2`
> **传递依赖 `langsmith<1.0.0,>=0.3.45`** —— **[已核]**。
> 也就是说 **langsmith 包一定会被装上**。

**这是否是问题？** 分两层，第二层还没核清：

- **[已核]** 装上 ≠ 会上传数据。LangSmith 的追踪通常由环境变量开关控制。
- **[已核 2026-09-05]** 已在 socket 层拦截 + 正对照验过：**不设变量时 0 次外部连接**；
  但设 `LANGSMITH_TRACING=true` 时**确实会连** `api.smith.langchain.com`。
  **所以风险不在库，在部署配置。** 证据见
  [`verification-2026-09-05.md`](verification-2026-09-05.md)。

**对策**：启动断言（`products/assistant/egress_guard.py`，检测到就**拒绝启动**）+ 部署清单。

> 🔶 **2026-09-07 顺手改的（本条与 Voice 无关）**：这里原来还挂着
> 「[待核] 必须验证零出网」和一条「改为自己写状态机」的降级路径，
> 但 `facts-to-verify.md` P0 #1 与 `dev-plan.md` §5 都已记为 2026-09-05 解除。
> **同一件事在三份文档里两种状态**，读到这份的人会以为 Assistant 还不能部署。
> **降级路径已取消**（`dev-plan.md` 同款结论）。
工作量约 2–3 天，**远低于数据外流的代价**。

---

### 1.3 Docling — Documents 的解析层

| 项 | 值 |
|:---|:---|
| 仓库 | `DS4SD/docling` |
| SPDX | **[已核]** `MIT`（GitHub 直接归类，非 NOASSERTION） |
| 最新版本 | **[已核]** `2.126.0`，发布于 2026-09-04（**非常活跃**） |

**我们的用法是否踩线**：不踩。MIT 无商用限制。

**[待核]** Docling 在解析扫描件时会拉取 OCR 模型权重（如 EasyOCR/Tesseract 系）。
**这些权重的许可是独立的**，须逐个确认。
核法：`docling` 首次运行时看它下载了什么，逐个查权重仓库的 LICENSE。
**这与 Creative 的模型权重问题是同一类风险**（见 §3）。

---

### 1.4 ~~faster-whisper~~ → SenseVoice + whisper.cpp — Voice

> 🔶 **[已核 2026-09-07] 本条整体换掉。** Voice 的实际基础在
> `iDoris-ai/AgentEar`，**主链路不用 faster-whisper**。
> 完整证据见 [`verification-2026-09-07-voice-v0.md`](verification-2026-09-07-voice-v0.md)。

| 链路 | 组件 | 许可 | 备注 |
|:---|:---|:---|:---|
| **主链路** | SenseVoiceSmall q8 GGUF | **[已核]** Apache-2.0 | 242 MiB |
| 主链路 | FunASR llamacpp runtime | **[已核]** 取上游**发布产物** `runtime-llamacpp-*` | ⚠️ **产物停发 = 断供** |
| 主链路 | fsmn-vad GGUF | 同上游 | 静音切分 |
| **泰语支线** | whisper.cpp | **[已核]** MIT | 单二进制 |
| 泰语支线 | `distill` q5_0 GGML | **[已核]** MIT | ⚠️ **我们要托管转换后的 GGML 产物 —— 再分发义务是真的，不是形式** |

**⚠️ 新的活跃度关注点**：不再是「某个库停更」，而是
**「上游还发不发 runtime 产物」**。对策：锁版本 **+ 自留一份产物副本**
（版本号锁不住上游删 release）。

**[已核] 原来那条 faster-whisper 的核查**（停更 9.5 个月、CUDA 活口子）
见 `verification-2026-09-06-voice-stack.md` —— **结论仍成立，但只适用于
泰语支线的相邻生态，不再是主链路风险。**

**[已核 2026-09-07] 可以用。** AgentEar 本体 **Apache-2.0**（仓库 `LICENSE`）；
runtime **MIT**、SenseVoice 与 FSMN-VAD **Apache-2.0**（均见其 `NOTICE`）；
泰语 GGML 上游 `biodatlab/distill-whisper-th-large-v3` **MIT**，
再分发只需保留版权声明，Release 已注明出处、revision 与许可。

> 🔴 **但有一条条件义务，V1 必须挂上**：三个泰语候选的上游许可**不一样**。
> `distill` 与 `turbo` 是 MIT，而 **`medium`（`biodatlab/whisper-th-medium-combined`）
> 是 Apache-2.0** —— ADR-0004 原话「如果日后换成 Apache-2.0 的 `medium`，
> **NOTICE 义务要重新过一遍**」。
>
> 而 `medium` 恰好是 CER 表里最好的那个（0.0608）——**这就是陷阱所在**。
> 但那 0.0014 的差距**未检出**（配对 CI [−0.0142, +0.0099]），
> 换它还要多付 425 MB 内存。**默认跟随 `distill` q5_0，别为一个测不出来的差异换许可。**

---

### 1.5 pgvector — 向量检索

| 项 | 值 |
|:---|:---|
| 仓库 | `pgvector/pgvector` |
| SPDX | **[已核]** `NOASSERTION`，实际是 **PostgreSQL License**（BSD 风格） |
| 原文要点 | **[已核]** 允许任意用途的使用、复制、修改、分发，需保留版权声明 |

**我们的用法是否踩线**：不踩。PostgreSQL License 是最宽松的许可之一。

---

### 1.6 LINE Messaging API SDK

| 项 | 值 |
|:---|:---|
| 仓库 | `line/line-bot-sdk-python` |
| SPDX | **[已核]** `Apache-2.0` |

**我们的用法是否踩线**：不踩。

**[待核]** SDK 的许可 ≠ **LINE 平台的服务条款**。
以商业身份代客户运营 LINE OA 需确认 LINE 的开发者条款与商用规定。
核法：读 LINE Developers 的 Terms of Use。**这是渠道风险不是代码风险。**

---

## 2. 我们排除的组件（结论：不用，理由已核实）

### 2.1 ComfyUI — GPL-3.0，只能隔离调用

| 项 | 值 |
|:---|:---|
| SPDX | **[已核]** `GPL-3.0` |

**结论**：**只能独立进程 HTTP 调用。** 具体规矩见
[`starter-kit/creative.md`](starter-kit/creative.md) §0。

越线后果**不可逆**：整个 iDoris Core 被传染成 GPL，所有商业交付代码必须开源。

---

### 2.2 n8n — 不是开源，禁止转售托管

| 项 | 值 |
|:---|:---|
| SPDX | **[已核]** `NOASSERTION`，实际是 **Sustainable Use License** |
| 原文要点 | **[已核]** ① 非 master 分支的内容**不授予许可**；② 文件名含 `.ee.` 或目录含 `.ee` 的源码**需持有 n8n Enterprise License**；③ 其余适用 Sustainable Use License |

**结论**：**不用。** Sustainable Use License 不是 OSI 开源许可，
对「作为服务转售」有限制。我们要做的正是托管服务。

**若将来需要通用连接器编排**：自建轻量层，或找 Apache 2.0 的替代品。

---

### 2.3 Dify — 明文禁止多租户

| 项 | 值 |
|:---|:---|
| SPDX | **[已核]** `NOASSERTION`，实际是 **modified Apache 2.0** |
| 原文要点 | **[已核]** 「**Multi-tenant service: Unless explicitly authorized by Dify in writing, you may not use the Dify source code to operate a multi-tenant environment.**」（一个 tenant = 一个 workspace）；另有前端 LOGO 与版权信息不得移除的条款 |

**结论**：**不用。** 我们的商业模式是给多个客户提供托管服务——
按其定义每个客户一个 workspace，即多租户，**明文禁止**。

> `research.md` 原写「含品牌与多租户附加条款，商用前须逐条读」——
> 方向对，但没说清这是**禁止**而非「须注意」。已在此纠正。

---

### 2.4 Open WebUI — 50 用户以上不得去品牌

| 项 | 值 |
|:---|:---|
| SPDX | **[已核]** `NOASSERTION`，BSD-3 + 附加条款 |
| 原文要点 | **[已核]** 第 4 条：禁止移除/修改 "Open WebUI" 品牌标识，**例外**：① 30 天滚动周期内终端用户 ≤ **50** 人；② 获书面许可；③ 持有企业许可 |

**结论**：**不用**（本来就决定「前三个客户不做前端」）。
但这条值得记下来：将来若要做白标前端，Open WebUI 在 50 用户以上就不可行。

---

## 3. 横跨多个组件的风险：模型权重许可

**这是本次尽调里最大的未解决项。**

代码的许可和**模型权重的许可是两回事**，而权重的商用条款差异极大
（有的禁商用、有的要署名、有的对生成内容有限制、有的要求接受平台条款）。

| 涉及组件 | 权重 | 状态 |
|:---|:---|:---|
| Voice | Whisper large-v3 等 | **[待核]** |
| Documents | Docling 的 OCR/版面模型 | **[待核]** |
| Creative | 图像生成模型 | **[待核]** ← **风险最高** |

**核法**：逐个找到权重的发布页/仓库，读其 LICENSE 或 model card 的 license 段，
特别看「commercial use」条款。

**核之前不能做什么**：
- **Creative 的图像部分不对外交付**（降级方案：先只上纯文案的 `copy`）
- Voice / Documents 可以先在内部与演示中使用，但**正式商业交付前必须核清**

---

## 4. 汇总

| 组件 | License | 结论 | 硬约束 |
|:---|:---|:---|:---|
| LiteLLM | MIT（`enterprise/` 除外） | ✅ 用 | 绝不碰 `enterprise/` |
| LangGraph | MIT | ⚠️ 待验证离线 | 确认零出网前不进客户环境 |
| Docling | MIT | ✅ 用 | OCR 权重许可待核 |
| ~~faster-whisper~~ **SenseVoiceSmall** | Apache-2.0 | ✅ 用 | **[已核 2026-09-07]** 主链路已换；风险改为「上游 runtime 产物停发」|
| **whisper.cpp + `distill` q5_0** | MIT | ✅ 用 | 泰语支线；**托管 GGML 产物有再分发义务** |
| pgvector | PostgreSQL License | ✅ 用 | 无 |
| LINE SDK | Apache-2.0 | ✅ 用 | 平台服务条款待核 |
| ComfyUI | **GPL-3.0** | ⚠️ 仅隔离调用 | 不 import、不 vendor、不同镜像 |
| n8n | Sustainable Use | ❌ 不用 | — |
| Dify | 改版 Apache（**禁多租户**） | ❌ 不用 | — |
| Open WebUI | BSD-3 + 品牌条款 | ❌ 不用 | >50 用户不得去品牌 |

## 5. 待核清单（汇总进 `facts-to-verify.md`）

1. LangGraph 完全离线时是否零出网 —— **Dev，Assistant 开工前，阻塞客户部署**
2. ~~Whisper 权重许可~~ **[已核 2026-09-07] 已不适用**（链路已换）。接替它的是：**首次实装 AgentEar 把「能跑/离线」从自述变实测** —— Dev，Voice 商业交付前
3. Docling OCR 权重许可 —— Dev，Documents 商业交付前
4. 图像模型权重许可 —— Dev，**Creative 图像部分交付前，阻塞**
5. LINE 平台商用服务条款 —— BD/PM，LINE Agent 立项前
6. LiteLLM 升级时 `enterprise/` 目录变化 —— Dev，每次升级
7. ~~faster-whisper 维护活跃度~~ → **`modelscope/FunASR` 还发不发 `runtime-llamacpp-*` 产物** —— Dev，季度复查
8. **AgentEar 成果的内部使用边界与再分发义务** —— BD 问 jason，Voice V1 之前
