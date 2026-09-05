# iDoris 客户环境部署 Runbook

> **这份文档的判定标准**：一个明天入职的 Dev，拿着它给一家新客户搭起环境，
> 每一步都有**可执行的命令**和**能对照的预期输出**，不需要问任何人。
> 做不到这一点就是这份 Runbook 的 bug，不是人的问题。
>
> 版本：v0.1 · 2026-09-06 · 前置：[`oss-due-diligence.md`](oss-due-diligence.md) ·
> [`gateway-design.md`](gateway-design.md) · [`starter-kit/assistant.md`](starter-kit/assistant.md)

---

## 0. 为什么需要这份文档

`egress_guard.py` 的启动断言挡住了「环境里有追踪配置就启动」这一种坏法。
但**它只在进程启动那一刻起作用**，而且只管环境变量。

真正会出事的地方在它之前：有人为了调试临时 `export LANGSMITH_TRACING=true`
然后忘了删、镜像基础层里带了变量、compose 文件从别的项目抄过来。

启动断言是**最后一道**，这份 Runbook 是前面那几道。

还有一类风险启动断言完全管不到：**许可边界**。
用错一个库不会有任何报错，会在客户签合同之后由律师发现。

---

## 1. 开始之前：三条绝不能破的边界

这三条一旦破了，代价不是「修一下」，而是法务问题或数据外流。
**每次部署都要过一遍，不是只在第一次。**

### 1.1 许可：三个库不能碰，一个目录不能引

| 库 | 状态 | 具体约束 |
|:---|:---|:---|
| **Dify** | ❌ 禁用 | **明文禁止多租户**。我们托管多客户 = 多租户 = 被禁止 |
| **n8n** | ❌ 禁用 | Sustainable Use License，**禁止转售托管** |
| **Open WebUI** | ⚠️ 有条件 | >50 用户不得去品牌。第一版不做前端，所以不涉及 |
| **LiteLLM** | ✅ 用 | **绝不引用 `enterprise/` 目录下任何代码** |
| **ComfyUI** | ⚠️ 隔离 | GPL-3.0。不 import、不 vendor、**不同镜像** |

**检查命令**（在部署机器上跑，不是在开发机上）：

```bash
# 1. 确认没有把 LiteLLM 的 enterprise/ 引进来
grep -rn "litellm.enterprise\|from litellm import enterprise\|litellm/enterprise" \
     --include='*.py' . && echo "❌ 引用了 enterprise/ —— 停止部署" || echo "✓ 没有引用 enterprise/"

# 2. 确认禁用的**服务**没被拉起来
#
#    注意:Dify 和 n8n 是**服务不是 Python 库**,所以 `pip list | grep dify`
#    永远抓不到东西 —— 那种检查看起来在把关、实际不可能命中,
#    比没有检查更危险。要查的是编排文件和镜像。
grep -rniE 'dify|n8n' docker-compose*.yml deploy/ k8s/ 2>/dev/null \
  && echo "❌ 编排文件里出现了禁用的服务 —— 停止部署" || echo "✓ 编排文件干净"
docker ps --format '{{.Image}}' 2>/dev/null | grep -iE 'dify|n8n' \
  && echo "❌ 跑着禁用的服务 —— 停止部署" || echo "✓ 没有禁用的服务在跑"
```

**ComfyUI 的检查不一样**：它是 GPL-3.0，允许用但**必须进程隔离**。
所以要查的不是「有没有」，而是「有没有被 import 进我们的进程」：

```bash
grep -rn "import comfy\|from comfy" --include='*.py' . \
  && echo "❌ 把 ComfyUI import 进来了 —— GPL 传染，停止部署" \
  || echo "✓ ComfyUI 没有被 import(隔离调用是允许的)"
```

**升级 LiteLLM 时必查**（[待核] 项，每次升级都要做）：

```bash
# 看 enterprise/ 目录有没有新增文件 —— 我们用到的功能可能被挪进去了
git -C <litellm-repo> log --stat --since="<上次升级日期>" -- enterprise/
```

核法写在 [`oss-due-diligence.md`](oss-due-diligence.md) §1.1。
**谁核**：做升级的那个人，不是「Dev 团队」——没有名字的责任等于没有责任。

### 1.2 出网：环境变量必须干净

```bash
# 部署前先扫一遍。退出码即结论,部署脚本直接用。
python3 products/assistant/egress_guard.py --check
```

预期输出：

```
✓ 环境干净：没有 LANGCHAIN_/LANGSMITH_ 追踪配置
```

**看到任何别的输出就停下来。** 报错信息会告诉你是哪个变量、以及怎么处理
（它刻意不打印变量值 —— 那可能是 API key，而报错会进日志、会被贴进工单）。

要检查的地方**不止 shell 环境**：

- [ ] `docker-compose.yml` / k8s manifest 的 `environment:` 段
- [ ] 基础镜像的 `ENV` 指令（`docker history <image>` 看得到）
- [ ] CI/CD 的 secrets 与变量
- [ ] `.env` 文件（**包括 `.env.local`、`.env.production` 这些不进 git 的**）
- [ ] systemd unit 的 `Environment=` 行

```bash
# 一次性扫上面这些
grep -rniE 'lang(chain|smith)_' \
     docker-compose*.yml .env* deploy/ 2>/dev/null \
  && echo "❌ 配置文件里有追踪变量" || echo "✓ 配置文件干净"
docker history <image> --no-trunc 2>/dev/null | grep -i 'lang\(chain\|smith\)_' \
  && echo "❌ 镜像层里带了追踪变量" || echo "✓ 镜像层干净"
```

**为什么值得查这么多处**：客户的会议内容是我们碰得到的最敏感的数据。
一个变量生效，转写稿就被发到 `api.smith.langchain.com`，
而**日志照常、功能照常、测试照常绿** —— 不会有任何东西提醒你。

### 1.3 路由：敏感任务强制本地

`sensitivity=high` 的任务**必须**走 `local` 档，这条压过任务类型、压过成本优化。

部署后立刻验：

```bash
python3 products/gateway/test_routing.py     # 含每条规则的负对照
python3 products/demo_meeting_to_tasks.py --self-test
```

预期最后一行包含 `敏感强制本地` 与 `事后核查为零`。

**事后核查**是第二道：

```python
from audit import AuditLog
with AuditLog("/var/lib/idoris/audit.db") as log:
    leaks = log.sensitive_calls_off_local("<tenant>")
    assert leaks == [], "有敏感调用没走本地：%r" % leaks
```

**正常情况下它必须永远返回空。** 非空说明有人绕过了 Gateway 直连模型，
或者规则 1 被改坏了。**建议做成每日定时任务**，不是只在部署时跑一次。

---

## 2. 部署步骤

### 2.1 前置检查（全部通过才继续）

```bash
cd <repo>
./scripts/deploy.sh --check                  # 站点资源
python3 products/assistant/egress_guard.py --check
python3 products/gateway/mutation_check.sh   # 变异测试:证明测试能变红
python3 products/documents/mutation_check.sh
python3 products/assistant/mutation_check.sh
python3 products/creative/mutation_check.sh
```

**四个变异脚本都要跑。** 它们回答的不是「代码对不对」，
而是「如果规则真被破坏了，测试会不会喊」—— 一个永远绿的测试套件，
看起来和真测试一模一样。

任何一个报 `✗` 就停下来。特别注意这一行：

```
✗ ... —— 变异未生效(sed 没匹配上,多半是代码重构了),请更新这条变异
```

这**不是**规则漏洞，是变异过期了。区别很重要：前者要改代码，后者要改变异脚本。

### 2.2 时区：账单按曼谷算

`AuditLog` 的账期固定 `+07:00`（`BILLING_TZ`），**与服务器在哪无关**。

不需要在部署机器上设 `TZ` 来「配合」它 —— 恰恰相反，
早先的 bug 就是月份边界跟着服务器本地时区漂，换台机器客户账单就变月份。

如果客户不在泰国，改的是 `AuditLog(path, billing_tz=...)`，**不是机器的 TZ**。

验证：

```bash
TZ=UTC python3 products/gateway/test_audit.py
TZ=Pacific/Midway python3 products/gateway/test_audit.py
```

两次都必须通过 —— 测试里本来就会切换四个时区跑同一套断言。

### 2.3 模型权重

| 组件 | 权重 | 许可 | 可商用 |
|:---|:---|:---|:---|
| Voice | `Systran/faster-whisper-large-v3` | MIT | ✅ [已核] |
| Documents | `ds4sd/docling-models` | CDLA-Permissive-2.0 + Apache-2.0 | ✅ [已核] |
| Creative 图像 | **尚未选定** | — | ❌ **[待核]，先不上** |

**条件**：Docling 第一版**不启用外部 OCR 引擎** —— 那些引擎各自的许可没核。

Creative 第一版**只上纯文案的 `copy`**，零 License 风险。
客户问到图像生成时直说「还在核许可，这一版不含」——
不要说「马上就有」，那是我们控制不了的时间。

### 2.3.1 Voice：必须同时锁两个版本，并显式验 GPU 路径

**[已核] 2026-09-06**（见
[`verification-2026-09-06-voice-stack.md`](verification-2026-09-06-voice-stack.md)）：

`faster-whisper` **维护者已停更 9.5 个月**（最后提交 2025-11-19，
社区仍在提 PR 但无人合并），而它的推理后端 `CTranslate2` **六天前还在发版**
（v4.8.2 · 2026-08-31）。

CUDA 兼容问题从 2024-10-24 open 至今；有人提过 `pin ctranslate2<4.6.3`
的修复，**PR 于 2026-04-13 被关掉、未合并**。

**风险的形状不是「哪天它坏了」，是「它已经在坏，只是我们还没装」** ——
后端每发一版，缺口就宽一点，而没有人在补。

#### 所以这两件事都要做，缺一不可

**① 同时锁两个包的版本。**

```
faster-whisper==1.2.1
ctranslate2==<与上面实测配对通过的版本>
```

**只锁 `faster-whisper` 不够** —— 问题恰恰出在后端会自己往前走。
`requirements.txt` 里两行都要有，都要是 `==` 不是 `>=`。

**② 部署时显式验 GPU 路径，不能只验 import 成功。**

```bash
python3 - <<'EOF'
from faster_whisper import WhisperModel
# 必须真的加载到 GPU 并跑一段,不能只 import。
# 那个报错(This CTranslate2 package was not compiled with CUDA)
# **在 import 阶段不出现,跑起来才出现**。
m = WhisperModel("large-v3", device="cuda", compute_type="float16")
segs, info = m.transcribe("<一段 5 秒的测试音频>.wav", language="th")
print("✓ GPU 路径可用，识别到语言:", info.language)
EOF
```

**看到 `This CTranslate2 package was not compiled with CUDA` 就停下来** ——
这不是配置问题，是版本配对不对。回到 ① 换 `ctranslate2` 版本重试。

### 2.4 审批队列

`AutoReleasePolicy` **默认为空**，也就是**全部人审**。

往里加意图必须同时满足三个条件（[`assistant.md`](starter-kit/assistant.md) 边界五）：

1. 客户**书面**确认
2. 该意图已积累 **≥50 条**人工审批历史且准确率 **≥95%**
3. 有随时可关的开关

**理由**：一条错误的自动回复对本地小生意的伤害，远大于省下的那点人工。
一家清迈酒店的 LINE 是他们的门面 —— 回错一次房价、答错一次是否有空房，
损失的是真实订单和口碑。

部署时**不要**替客户开任何自动放行。让他们用两周人审，再谈这件事。

---

## 3. 部署后验证（客户在场时跑一遍）

按顺序跑，每一步都有肉眼可见的结论：

| # | 命令 | 预期 |
|:--|:---|:---|
| 1 | `python3 products/assistant/egress_guard.py --check` | `✓ 环境干净` |
| 2 | `LANGSMITH_TRACING=true python3 products/demo_meeting_to_tasks.py; echo $?` | **`1`**（拒绝启动） |
| 3 | `python3 products/demo_meeting_to_tasks.py --self-test` | 六条安全属性全绿 |
| 4 | 审计库查 `sensitive_calls_off_local` | `[]` |

**第 2 步是正对照，不能省。** 只跑第 1 步的话，
一个「永远放行」的闸门也是绿的 —— 而那种坏法不会有任何人发现。

给客户看第 2 步的价值：它证明的不是「我们没上传」，
而是**「我们让上传这件事做不到」**。这两句话的分量差很远。

---

## 4. 出问题时

### 4.1 启动被拒绝

报错信息里有变量名和处理方法。**不要**为了把服务起起来去改
`KNOWN_HARMLESS` —— 那个清单默认为空是有意的，往里加东西要在代码评审里被看见。

正确做法：找到那个变量是哪来的（§1.2 的五个地方），删掉它。

### 4.2 变异测试报 ✗

先看是哪一种：

- `变异未生效(sed 没匹配上)` → **变异过期了**，代码重构挪走了被匹配的行。
  更新变异脚本，不要改测试。
- `破坏后测试仍然通过` → **真漏洞**，那条规则没有被测试兜住。
  补测试，补完再验证变异会变红。

**两种不能混。** 把过期变异当成漏洞，会把人引去改根本没问题的测试。

### 4.3 回滚

站点：Cloudflare Pages 有版本历史，回滚是一次点击。
产品代码：这些模块目前**没有持久化的迁移**，回滚就是切回上一个 commit 重启。
审计库是追加写的，回滚代码不影响已写入的记录。

---

## 5. 这份 Runbook 管不到的

写清楚边界，比让人以为「照着做就安全了」要紧：

- **代码里直接传 `callbacks=[LangChainTracer()]`** —— 环境变量检查挡不住，
  那是代码评审的事
- **别的库自己的遥测** —— 各自另有开关，需要逐个核（[待核]）
- **网络出口没关** —— 环境干净不等于出不去。出网控制是部署层的事，
  见 `tools/verify/` 里的 socket 探针
- **客户自己的人往里塞变量** —— 交付后的环境不在我们手上。
  所以启动断言比一次性检查重要：它每次启动都查

---

## 5.1 这份 Runbook 里的命令都实跑过

写下来的每条命令都在本机跑过一遍，不是照着抄的。**一份没跑过的 Runbook，
到了要用的那天会在最坏的时刻失败。**

有一条是跑的时候才发现不对的：原先写的是
`pip list | grep -iE '^(dify|n8n)'` —— 但 Dify 和 n8n 是**服务不是 Python 库**，
这条命令**永远抓不到东西**。一个看起来在把关、实际不可能命中的检查，
比没有检查更危险，因为它会让人以为已经查过了。改成查编排文件和运行中的镜像。

`egress_guard.py --check` 与出网相关的命令在 assistant 分支上验证，
Documents 的四个动作在 documents 分支上验证 —— 各分支合进 `preview` 之后
再整体跑一遍。

## 6. [待核]

| # | 项 | 谁核 | 怎么核 |
|:--|:---|:---|:---|
| 1 | 图像模型权重许可 | Dev | 选定模型后读该模型的 LICENSE 与使用条款 |
| 2 | Voice 组件现状 | Dev | 需读 iDoris 代码仓库（不在本仓库） |
| 2b | faster-whisper × ctranslate2 的**可用版本配对** | Dev | 按 §2.3.1 ② 的脚本实测；配对确定后写死进 `requirements.txt` |
| 3 | LiteLLM 升级后 `enterprise/` 变动 | 做升级的人 | `git log --stat -- enterprise/` |
| 4 | 其他库的遥测开关 | Dev | 逐库读文档 |

**[待核] 不是「以后再说」，是「现在不知道，所以现在不能做对应的事」。**
