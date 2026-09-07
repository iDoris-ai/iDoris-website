# 评估 · Anthropic `commerce-agents` 能不能进我们的四阶段

> 对象：[`anthropics/commerce-agents`](https://github.com/anthropics/commerce-agents)
> 起因：仓库主人给了两篇解读文章，问能否作为某一阶段的基础组件。
> 评估人：Dev · 2026-09-06

---

## 一句话结论

**能用，但用法不是「引入一个依赖」，而是「抄一套架构 + 收一个新垂直」。**

它最大的价值**不在代码**，在于它**独立地印证了我们已经做出的三条设计决定** ——
这件事对销售的意义大于对工程的意义。

---

## 1. [已核] 它到底是什么

| 项 | 事实 | 来源 |
|:---|:---|:---|
| 许可 | **Apache-2.0** | GitHub API，`license.spdx_id` |
| 发布 | **2026-09-01**（5 天前） | GitHub API |
| 提交数 | **1 次**（`building commerce agents using claude`，2026-08-31） | GitHub API |
| 发版 | **0 个 release** | GitHub API |
| 打包 | **没有 `pyproject.toml` / `setup.py`**，只有 `requirements.txt` | 仓库根目录清单 |
| Stars | 2,189 | GitHub API |

**所以它不是一个能 `pip install` 的库，是参考实现（照着抄的代码）。**
这一条决定了后面所有讨论 —— 我们不会「依赖」它，只会「学」它。

### README 自己怎么定位

> Every company, brand, product, and person here is **fictional**; the only company is ACME.
> **Nothing places an order, charges a card, or changes a live listing.**
>
> **Business rules, authorization, and compliance are the deployment's.**

**它明确把最难的三件事推给了使用者。** 这不是缺点 —— 一个参考架构本来就该这样 ——
但它意味着**「接上它」的工作量，和从零做一个 Agent 差不了太多**。

---

## 2. ⚠️ 那个「购物车 +30%、完成率 +60%」不要用

**[待核]，而且是我们已经学会警惕的那个形状。**

- **官方 README 里没有这两个数字。** 我搜过全文。
- 它们只出现在解读文章里，出处写的是「partner testing」，
  **没有样本量、没有对照组、没有测量口径，文章自己也说「no ablation studies are cited」**。

这和 `verification-2026-09-06-source-provenance.md` 里识别出的那类断言**形状完全一样**：
**一个具体到能证伪的数字，配一个追不到的出处。**

> ❌ **不得写进任何对外材料**（提案、一页纸、官网、报价单）。
> 客户问起时可以说「Anthropic 发布了一套商务 Agent 的参考架构」，
> **但不要引用那两个百分比** —— 我们无法为它背书。

---

## 3. 它印证了我们已经做出的三条决定

这是这次评估最有价值的发现。**我们和 Anthropic 独立地走到了同一套机制上。**

| `commerce-agents` 的做法 | 我们已经建好的 | 位置 |
|:---|:---|:---|
| **Staging gates** —— 所有写操作先暂存，`apply_change` 必须有人批准 | **默认全审，自动放行是白名单** | `products/assistant/approval.py` |
| **Provenance gates** —— 只接受本次会话里目录工具返回过的 product ID | **出处必须在本次检索结果里**，编出处比不给出处更危险 | `products/documents/search.py` |
| **Fencing** —— 第三方内容在进入模型前先净化隔离 | **审计只存元数据不存内容**，字段名闸门 + 长度上限 | `products/gateway/audit.py` |
| **「安全约束写在 harness 层，不是提示词里」** | 我们所有不可破规则都是**代码**，且每条配变异测试证明它真的会红 | 四个产品共 113 条变异 |

它原文的说法是：

> Safety constraints write in the harness layer, not just the prompt —
> **prompts work only when models comply; code always works.**

**这句话可以直接拿去用**（它是 Apache-2.0 的公开表述，不是我们编的），
用来回答客户那个最常问的问题：「你们怎么保证 AI 不乱来？」

**答案不是「我们提示词写得好」，是「我们把它写死在代码里，并且证明过那条代码真的会拦」。**

---

## 4. 按四阶段逐个看能不能用上

### Discover — 能用，但用法是**清单**不是组件

它的 `Backend Interface` 定义了商务系统必须暴露的约 20 个方法
（`search_products` / `get_product` / `add_to_cart` / `get_orders` / `get_policy` …）。

**这本质上是一张「一家零售/酒店的系统里到底有什么」的清单。**
Discovery 第 2 天要做「现有系统与数据边界盘点」（`discovery-sop.md` Day 2 · 14:30–16:00），
对**零售、餐饮、酒店**这类客户，可以拿它当**盘点提纲**：
逐条问「这个你们有吗？在哪个系统里？谁能给我们接口？」

**价值：中等且具体。** 不需要写代码，明天就能用。
**限制：只对有商品/订单概念的客户有用**，对做服务、做内容的客户没用。

### Enable — 基本用不上

我们的 Enable 是**按角色、用客户自己的例子**做实操。
一套别人家的参考架构进不了这个场景 —— 除非客户的技术团队想学 Agent 架构，
那属于另一种生意（技术培训），不是我们现在卖的东西。

**结论：不进 Enable。** 硬塞会让 Enable 变回「通用 AI 培训」，
而那正是 `services.md` §2 明确写着不该卖的东西。

### Implement — **这里是它真正的位置**

两种用法，价值差很多：

**用法 A（推荐）：作为第五个 Starter Kit 组件的设计蓝本 —— `Commerce`。**

我们现有四个组件是 Voice / Documents / Creative / Assistant，
**没有一个碰「订单、库存、价目」**。而清迈的酒店、餐厅、零售店恰恰是我们的 ICP。

它的 `merchant-agent`（面向店员的后台 Agent）比 `shopping-agent`（面向顾客）
**对我们更有用** —— 因为：

- 后台是**内部使用**，出错的爆炸半径小得多，符合我们「先做低风险的」的一贯选择
- 它做的事（「解释销售表现、维护商品列表、响应库存告警、设定价格与促销」）
  正是小生意老板每天花时间最多、最愿意付钱免掉的事
- 面向顾客的那半边**在泰国有个硬问题**，见下

**用法 B：直接抄它的 skills-as-markdown 设计。**
「技能按需装载进上下文，核心安全与法务规则永远留在 system prompt」——
这一条我们的 Assistant 还没做，值得借鉴。

### Operate — 顺带受益

Staging gate 的模式天然适合运维期：每月的价目调整、促销上下架，
都可以走「暂存 → 人批准 → 执行」。不需要额外工作，是 Implement 的自然延伸。

---

## 5. ⚠️ 一个它没解决、而我们必须解决的问题

**它假设有一个「host application」—— 网页或 App 商城。**

`checkout` 只渲染购物车，由宿主应用完成支付。这在美国是合理假设。

**但在泰国，我们客户的生意发生在 LINE 里。**

- 没有 App，很多小生意连网站都没有
- 下单、问价、改单全在聊天窗口
- 支付走 PromptPay 扫码，不是网页收银台

**所以 `shopping-agent` 那一半不能照搬** ——
它的对话流是「Agent 帮你在商城里挑」，而我们的场景是
「Agent 在 LINE 里替店主回客人」，那更接近我们已有的
[`line-agent-design.md`](line-agent-design.md)。

**这个差距是真实工作量，不是配置问题。** 谁要是照着它排期，会低估。

---

## 6. 建议：做什么、不做什么

| | |
|:---|:---|
| ✅ **现在就做** | 把 `Backend Interface` 的方法清单整理成 Discovery 的**系统盘点提纲**（零售/酒店/餐饮版）。零代码，明天可用 |
| ✅ **现在就做** | 把「安全写在 harness 层不是提示词里」这句话，连同我们的 113 条变异测试，写进销售话术 —— **这是我们最强的差异化，而现在没人说得清** |
| 🟡 **列入 todo** | `Commerce` 作为第五个 Starter Kit 组件的设计，**从 `merchant-agent`（后台）切入，不从 shopping 切入** |
| ❌ **不做** | 不把它当依赖引进代码库（一次提交、零发版、非可安装包） |
| ❌ **不做** | 不进 Enable |
| ❌ **绝不** | 不引用「+30% / +60%」那两个数字 |

### 触发条件

**只有当我们签下第一个有商品/订单概念的客户时，才启动 `Commerce` 组件的设计。**

理由和我们一贯的做法一致：没卖出去的产品不知道该做成什么样。
现在做，做出来的会是 ACME 那个虚构公司的形状，不是清迈某家酒店的形状。

---

## 7. [待核]

| # | 要核什么 | 怎么核 | 谁 |
|:--|:---|:---|:---|
| 1 | 它有没有第二次提交 / 第一个 release | `gh api repos/anthropics/commerce-agents/commits` | Dev，一个月后再看 |
| 2 | `commerce-common` 里有没有可直接复用的代码（而不只是模式） | 读 `commerce-common/` 源码 | Dev，启动 Commerce 组件时 |
| 3 | LINE 平台是否允许 Agent 代店主处理订单类消息 | **与 `facts-to-verify.md` #14 是同一条** —— 人用浏览器读 LINE 条款 | BD |

**第 3 条尤其重要**：如果 #14 的答案是「不允许」，
那么整个 Commerce 组件在泰国的主要渠道上就走不通，
`merchant-agent`（内部后台）仍然可行，但 `shopping-agent` 直接出局。
