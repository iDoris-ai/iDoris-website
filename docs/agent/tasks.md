# iDoris Thailand 任务台账 — Task

> 前置：[`roadmap.md`](roadmap.md) · [`architecture.md`](architecture.md) · [`spec.md`](spec.md)
> 每个 Task 自包含，可独立开发与验收。**验收标准必须可机器验证**。
> 状态：BACKLOG · READY · IN_PROGRESS · BLOCKED · PR_OPEN · CHANGES_REQUESTED · APPROVED · DONE
> 记录日期：2026-09-05

## 深度要求（对所有 Task 一体适用）

这批 Task 的产出物是**给人照着干活的东西**，不是方向性描述。判定标准只有一条：

> **一个明天入职的新员工，读完能不能直接上岗？**

具体到三类产出：

- **SOP 类**：必须精确到「第几天第几个小时、见谁、问哪几个问题（原话）、
  用什么工具、产出哪个文件」。写「进行客户访谈」等于没写；
  写「Day 1 09:00–10:30 见老板，按 `interview/owner.md` 的 12 个问题问，
  录音转写用 Voice，当场填 `pain-inventory.md` 前三行」才算写了。
- **设计类**：必须精确到「用哪个开源仓库、什么版本、License、
  它负责哪一段、我们自己写哪一段、两段之间的接口长什么样」。
  写「基于开源组件实现」等于没写。
- **调研类**：每个影响决策的事实必须标 **[已核]** 或 **[待核]**，
  [待核] 的要写明「去哪个链接能核」。没有第三种。

**所有产出物放在 `docs/business/` 下**，与 `docs/agent/`（pilot 运行态）分开。

---

# M1 — 明天能开业

## F1.1 — 服务定义与定价

### T1.1.1 四阶段服务定义  `DONE`
- **优先级**：high
- **目标**：把 Discover / Enable / Implement / Operate 写成任何人都能照着卖的定义
- **开发范围**：`docs/business/services.md`。每阶段含：解决什么问题、做什么、
  几天、交付物清单、**什么情况下客户该买这个、什么情况下明确不该卖**
- **明确不做**：不写价格（在 T1.1.2）
- **交付物**：`docs/business/services.md`
- **验收命令**：`for s in Discover Enable Implement Operate; do grep -q "$s" docs/business/services.md || exit 1; done; grep -q "不该" docs/business/services.md`

### T1.1.2 泰铢定价表与区间判据  `DONE`
- **优先级**：high
- **目标**：每档有价格区间，且写明**什么情况取上限、什么情况取下限**
- **开发范围**：`docs/business/pricing.md`。以源文档第 6 节为起点，
  显著标注**「初始定价假设，非市场调研结果」**
- **明确不做**：不编泰国市场价（没有可靠一手来源）
- **依赖**：T1.1.1
- **验收命令**：`grep -q "初始定价假设" docs/business/pricing.md && grep -q "取上限" docs/business/pricing.md && grep -q "THB" docs/business/pricing.md`
- **风险**：价格是对外承诺，必须标明可调整

### T1.1.3 竞争与替代方案分析  `DONE`
- **优先级**：high
- **目标**：客户不买我们会买什么/自己干什么，我们凭什么赢
- **开发范围**：`docs/business/alternatives.md`。至少覆盖五种替代：
  政府/大学免费培训、客户自己买 ChatGPT 订阅、本地 IT 外包、大厂咨询、什么都不做。
  每种写：它便宜在哪、它在哪里失效、我们的说法是什么
- **验收命令**：`grep -c "^## " docs/business/alternatives.md | awk '$1>=5{exit 0}{exit 1}'`

## F1.2 — 三角色分工与上岗

### T1.2.1 客户旅程手册  `DONE`
- **优先级**：high
- **目标**：把 spec.md 的状态机与 RACI 变成可以直接给新人的操作手册
- **开发范围**：`docs/business/playbook-customer-journey.md`
- **验收命令**：`grep -q "stateDiagram" docs/business/playbook-customer-journey.md && grep -q "RACI" docs/business/playbook-customer-journey.md && grep -q "退化" docs/business/playbook-customer-journey.md`

### T1.2.2 阶段门检查表（可打印）  `DONE`
- **优先级**：high
- **开发范围**：`docs/business/stage-gates.md`，checkbox 形式，每个阶段门列出
  「缺一项不准进下一阶段」的条目
- **依赖**：T1.2.1
- **验收命令**：`grep -c '^\- \[ \]' docs/business/stage-gates.md | awk '$1>=20{exit 0}{exit 1}'`

### T1.2.3 新员工第一天上岗手册  `DONE`
- **优先级**：high
- **目标**：**明天有人入职，读这一份就能开始干活**
- **开发范围**：`docs/business/onboarding-day1.md`。三条角色路径（BD / PM / Dev），
  每条含：你负责什么、你的第一周做什么、必读的五份文档（按顺序）、
  你的第一个产出物是什么、遇到什么情况要停下来问人
- **依赖**：T1.2.1、T1.2.2
- **验收命令**：`for r in BD PM Dev; do grep -q "$r" docs/business/onboarding-day1.md || exit 1; done; grep -q "第一周" docs/business/onboarding-day1.md`

## F1.3 — 销售弹药

### T1.3.1 一页纸（EN + TH）  `DONE`
- **优先级**：high
- **开发范围**：`docs/business/one-pager-en.md` 与 `one-pager-th.md`。
  结构：解决什么 → 四阶段 → 价格区间 → 为什么是我们 → 下一步
- **依赖**：T1.1.1、T1.1.2
- **验收命令**：`test -f docs/business/one-pager-en.md && test -f docs/business/one-pager-th.md && grep -q "待泰语 native 校对" docs/business/one-pager-th.md`
- **风险**：泰语版由 AI 生成，**必须标注待 native 校对**

### T1.3.2 Discovery Sprint 完整样例（虚构酒店）  `DONE`
- **优先级**：high
- **目标**：一个从访谈到 90 天路线图的完整样例，九项交付物齐全
- **开发范围**：`docs/business/sample-discovery-hotel/`。虚构清迈精品酒店，
  按 spec.md 第五节九项逐项产出，每项都是**填好的真样例**不是空模板
- **明确不做**：不用真实客户信息
- **依赖**：T2.1.1（先有 SOP 才知道样例长什么样）
- **验收命令**：`ls docs/business/sample-discovery-hotel/*.md | wc -l | awk '$1>=10{exit 0}{exit 1}'`

### T1.3.3 报价单模板  `DONE`
- **优先级**：high
- **开发范围**：`docs/business/quote-template.md`，填空式，含交付物清单与验收条款
- **依赖**：T1.1.1、T1.1.2
- **验收命令**：`grep -q "验收" docs/business/quote-template.md && grep -c "{{" docs/business/quote-template.md | awk '$1>=8{exit 0}{exit 1}'`

## F1.4 — 官网可承接

### T1.4.1 官网服务页 `/services`  `DONE`
- **优先级**：mid
- **开发范围**：`site/services/index.html`，沿用 `/pricing` 的版式与 i18n 约定；
  `deploy.sh` 的 PAGES 加 `/services`；首页 nav 与 footer 挂链接
- **依赖**：T1.1.1、T1.1.2
- **验收命令**：`./scripts/deploy.sh --check`
- **备注**：**必须带 `/pricing` 同款「仅供参考」大字免责**

---

# M2 — 可交付

## F2.1 — iDoris Discovery Skill v0.1（今晚的重中之重）

### T2.1.1 Discovery SOP：逐小时、逐问题、逐工具  `DONE`
- **优先级**：**highest**
- **目标**：**任何一个 FDE 拿着它进企业，产出的九项交付物格式一致、质量可比**
- **开发范围**：`docs/business/discovery-sop.md`。必须包含：
  - **3 天版与 5 天版各自的逐时段安排**（Day N / 时段 / 见谁 / 干什么 / 产出哪个文件）
  - **三套访谈问题清单的完整问题原话**（老板 / 中层 / 一线），每套 ≥10 个问题，
    每个问题标注「想问出什么」
  - **每一步用什么工具**（录音转写用什么、画泳道图用什么、评分用什么）
  - **AI Readiness 五维评分的每一维的 1–5 分判据**（什么样算 3 分，什么样算 4 分）
  - **年化工时的计算公式**（频次 × 单次耗时 × 人数 → 年化小时 → 折算成本）
  - **Impact / Effort / Risk 三轴各自的打分判据**
  - **进场话术与收尾话术**（第一次见面说什么、交付会怎么讲）
  - **踩坑清单**（客户说"我们没什么重复工作"时怎么办、老板不放人时怎么办、
    数据不让看时怎么办）
- **明确不做**：不做真实客户访谈
- **交付物**：`docs/business/discovery-sop.md`
- **验收命令**：`grep -c "^### Day\|^## Day" docs/business/discovery-sop.md | awk '$1>=3{exit 0}{exit 1}'` 且 `grep -c "^[0-9]\+\. " docs/business/discovery-sop.md | awk '$1>=30{exit 0}{exit 1}'`
- **备注**：**这份文档是整个 iDoris 差异化的载体。** 写不到「新人照着能干」
  的程度就是没写完

### T2.1.2 Discovery Skill 打包为可分发资产  `DONE`
- **优先级**：high
- **目标**：把 SOP 变成一个目录结构清晰、可开源、可被 Claude Code 直接调用的 Skill
- **开发范围**：`docs/business/discovery-skill/`，结构见 architecture.md 3.1：
  `SKILL.md` + `interview/{owner,manager,user}.md` + `templates/`（5 个）+ `scripts/score.py`
- **依赖**：T2.1.1
- **验收命令**：`test -f docs/business/discovery-skill/SKILL.md && ls docs/business/discovery-skill/templates/*.md | wc -l | awk '$1>=5{exit 0}{exit 1}' && python3 docs/business/discovery-skill/scripts/score.py --self-test`
- **备注**：`score.py` 输入五维评分 → 输出矩阵与排序，**必须带 `--self-test`**

## F2.2 — Thailand AI Starter Kit v0.1（四个组件的设计）

> Voice 已有基础，其余三个要从零设计。**每个组件的设计文档必须回答同一组问题**：
> 它替谁省了什么时间 · 用哪个开源仓库（含 License）· 我们自己写哪一段 ·
> 接口长什么样 · 最小可用形态是什么 · 怎么演示给客户看

### T2.2.0 Starter Kit 总体设计与四组件边界  `DONE`
- **优先级**：high
- **开发范围**：`docs/business/starter-kit/README.md`。四个组件各自的定位、
  共用的 Gateway 契约、四者之间的数据流、统一的部署形态
- **验收命令**：`grep -q "Voice" docs/business/starter-kit/README.md && grep -q "Gateway" docs/business/starter-kit/README.md`

### T2.2.1 Voice 组件：现状盘点与补齐设计  `DONE`
- **优先级**：high
- **目标**：已有的东西到什么程度、缺什么才能当产品演示
- **开发范围**：`docs/business/starter-kit/voice.md`。含现状盘点、
  泰语识别质量的评测方法、三语混合输入的处理、语音→文档模板的衔接
- **验收命令**：`grep -q "faster-whisper\|whisper" docs/business/starter-kit/voice.md && grep -q "泰语" docs/business/starter-kit/voice.md`

### T2.2.2 Documents 组件设计  `DONE`
- **优先级**：**highest**
- **目标**：定义清楚 Documents 到底是个什么东西
- **开发范围**：`docs/business/starter-kit/documents.md`。必须回答：
  - **它是什么**：不是"文档 AI"这种空话，而是具体的六个动作
    （summarize / rewrite / compare / translate / extract / search）各自的输入输出
  - **开源基座**：Docling（文档解析）+ Gateway（模型调用）+ pgvector（检索），
    每个含 License、版本、它负责哪一段
  - **我们自己写的**：六个动作的 Skill 封装、泰文 PDF 的坑、表格与扫描件处理策略
  - **接口**：文件进 → 结构化中间表示 → 动作 → 结果出，中间表示长什么样
  - **最小可用形态**：先做哪两个动作就能演示
  - **典型场景**：合同对比、会议纪要抽取、泰英文件翻译
- **验收命令**：`grep -q "Docling" docs/business/starter-kit/documents.md && grep -c "^### " docs/business/starter-kit/documents.md | awk '$1>=6{exit 0}{exit 1}'`

### T2.2.3 Creative 组件设计  `DONE`
- **优先级**：high
- **开发范围**：`docs/business/starter-kit/creative.md`。必须回答：
  - **它是什么**：社媒素材 / 基础图像生成 / 营销内容 / 演示材料 / 品牌适配
  - **开源基座**：ComfyUI（**GPL-3.0，必须独立进程隔离**）+ Gateway 的文案生成
  - **GPL 隔离的具体做法**：HTTP 调用、我们的仓库里不含其代码、部署边界
  - **我们自己写的**：品牌一致性模板、社媒尺寸预设、泰英双语文案配图流程
  - **最小可用形态**：一个「输入产品描述 → 出三张社媒图 + 泰英文案」的流水线
- **验收命令**：`grep -q "GPL" docs/business/starter-kit/creative.md && grep -q "独立进程\|隔离" docs/business/starter-kit/creative.md`

### T2.2.4 Assistant 组件设计  `DONE`
- **优先级**：**highest**
- **开发范围**：`docs/business/starter-kit/assistant.md`。必须回答：
  - **它是什么**：会议→纪要→任务 / 邮件→草稿 / 文档→行动项 /
    调研→结构化摘要 / LINE→建议回复
  - **开源基座**：LangGraph（Agent 状态机 + human-in-the-loop 断点，MIT）+ Gateway
  - **为什么需要状态机**：这几个场景都有「人要在中间点头」的环节
  - **我们自己写的**：五个流程的图定义、审批队列、与 LINE 的衔接
  - **人工审批的默认策略**：默认全部要审，自动放行是白名单
  - **最小可用形态**：会议录音 → 纪要 → 任务清单，一条端到端
- **验收命令**：`grep -q "LangGraph" docs/business/starter-kit/assistant.md && grep -q "审批" docs/business/starter-kit/assistant.md`

## F2.0 — 产品设计与开发计划

### T2.0.1 产品清单与优先级  `DONE`
- **优先级**：high
- **开发范围**：`docs/business/product-portfolio.md`。以 architecture.md 第二节展开，
  每个产品含：解决谁的什么问题、优先级理由、依赖、最小可用形态
- **验收命令**：`grep -c "^## " docs/business/product-portfolio.md | awk '$1>=6{exit 0}{exit 1}'`

### T2.0.2 基于开源组件的开发计划  `DONE`
- **优先级**：high
- **开发范围**：`docs/business/dev-plan.md`。每个产品含组件表
  （名称/License/用途/为什么选它）、装配图、分阶段实现路径、风险
- **依赖**：T2.0.1、T2.2.0–4
- **验收命令**：`grep -q "Apache" docs/business/dev-plan.md && grep -q "GPL" docs/business/dev-plan.md && grep -q "LiteLLM" docs/business/dev-plan.md`

### T2.0.3 开源组件尽调  `DONE`
- **优先级**：**highest**
- **目标**：research.md 那张表逐行做实
- **开发范围**：`docs/business/oss-due-diligence.md`。每个组件：仓库地址、
  License 全名、最近发布、维护活跃度、商用限制、**我们的用法是否踩线**
- **验收命令**：`grep -c "\[已核\]\|\[待核\]" docs/business/oss-due-diligence.md | awk '$1>=10{exit 0}{exit 1}'`
- **备注**：**n8n 与 Dify 的许可条款必须逐条读过**——n8n 不是 OSI 开源，
  Dify 有品牌与多租户附加条款

### T2.0.4 AI Gateway 设计  `DONE`
- **优先级**：high
- **开发范围**：`docs/business/gateway-design.md`。LiteLLM 基座 + 我们的路由策略表、
  成本闸、审计留痕。含「Gateway 绝不存内容只存元数据」的边界
- **验收命令**：`grep -q "LiteLLM" docs/business/gateway-design.md && grep -q "元数据" docs/business/gateway-design.md`

### T2.0.5 LINE AI Agent 设计  `DONE`
- **优先级**：mid
- **开发范围**：`docs/business/line-agent-design.md`。LINE SDK + LangGraph，
  含意图识别、业务检索、人工审批队列、默认全审的策略
- **验收命令**：`grep -q "LangGraph" docs/business/line-agent-design.md && grep -q "审批" docs/business/line-agent-design.md`

---

# M3 — 可复制

## F3.1 — 度量

### T3.1.1 Before/After 度量方法  `DONE`
- **优先级**：high
- **开发范围**：`docs/business/measurement.md`。怎么取基线（**防自欺**：
  不能事后回忆，必须事前测）、测什么、怎么算年化收益、案例模板
- **验收命令**：`grep -q "基线" docs/business/measurement.md && grep -q "年化" docs/business/measurement.md`

## F3.2 — 泰国渠道

### T3.2.1 三条渠道路径调研  `DONE`
- **优先级**：high
- **开发范围**：`docs/business/thailand-channels.md`。depa 合作 / Digital Catalog
  注册 / 注册培训课程三条路径，各自：做什么、前置条件、时间成本、金钱成本、
  我们现在缺什么、下一步动作
- **明确不做**：不联系任何外部机构
- **验收命令**：`grep -c "^## " docs/business/thailand-channels.md | awk '$1>=3{exit 0}{exit 1}'`

### T3.2.2 待核事实清单  `DONE`
- **优先级**：**highest**
- **目标**：把所有 [待核] 集中一处，每条写明「去哪里、点哪个链接能核」
- **开发范围**：`docs/business/facts-to-verify.md`。扫描 `docs/` 下所有 [待核]，
  逐条列：断言、来源、影响哪个决策、怎么核、谁去核、核之前不能做什么
- **依赖**：T3.2.1、T2.0.3
- **验收命令**：`grep -c "^| " docs/business/facts-to-verify.md | awk '$1>=10{exit 0}{exit 1}'`
- **备注**：**这是防止「自洽地错着」的唯一机械保障。**
  2026-09-05 我们已经栽过一次：所有检查全绿，但结论集体错了

---

## 明确不在今晚范围（防止 run 跑偏）

- 注册公司 / VAT / 任何法律实体动作
- 联系 depa 或任何外部机构
- **真的实现** Starter Kit 四个模块（只出设计）
- 生产级 Gateway 部署
- ISO/IEC 29110 认证本身
- 官网首页重做

## 优先级说明

标 `highest` 的五个 Task 是今晚的骨干，其余可以往后排：

| Task | 为什么 |
|:---|:---|
| T2.1.1 Discovery SOP | 差异化本身，新员工上岗的核心依据 |
| T2.2.2 Documents 设计 | 你点名要设计清楚的 |
| T2.2.4 Assistant 设计 | 同上，且是四个组件里最复杂的 |
| T2.0.3 开源尽调 | License 踩线是不可逆的错误 |
| T3.2.2 待核事实清单 | 防止整套规划自洽地错着 |
