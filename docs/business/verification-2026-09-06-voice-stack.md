# 核查记录 · 2026-09-06 · Voice 技术栈的维护状况

> 核 `facts-to-verify.md` 的 P1 第 15、16 条。
> 方法：GitHub API 直读仓库元数据与提交历史，不依赖二手描述。
> 核的人：Dev。**证据命令都写在下面，可复现。**

---

## 结论先说

**#16 的结论要改。** 原来记的是「faster-whisper 维护活跃度存疑（最新发布
2025-10-31，约 10 个月前）」——这个说法**低估了问题**，而且找错了指标。

真正的问题不是「它老」，是 **它冻在一个还在动的依赖上**。

| 项目 | 角色 | 最后提交 | 最近发版 | open issues/PR | 归档 |
|:---|:---|:---|:---|---:|:---|
| `SYSTRAN/faster-whisper` | 封装层 | **2025-11-19** | v1.2.1 · 2025-10-31 | 320 | 否 |
| `OpenNMT/CTranslate2` | 推理后端 | **2026-08-31** | v4.8.2 · 2026-08-31 | 282 | 否 |

**[已核]** 后端六天前还在发版，封装层九个半月没有合并过任何东西。

---

## 证据

```bash
# faster-whisper:最后一次提交
gh api 'repos/SYSTRAN/faster-whisper/commits?per_page=1' \
   --jq '.[]|"\(.commit.author.date[0:10])  \(.commit.message|split("\n")[0])"'
# → 2025-11-19  Adds new VAD parameters (#1386)

# CTranslate2:最后一次提交
gh api 'repos/OpenNMT/CTranslate2/commits?per_page=1' \
   --jq '.[]|"\(.commit.author.date[0:10])  \(.commit.message|split("\n")[0])"'
# → 2026-08-31  Version 4.8.2 with CHANGELOG (#2095)
```

### 社区还活着，维护者不在

**[已核]** 仍有人持续提 PR —— 最新几条：

| 提交日期 | 标题 |
|:---|:---|
| 2026-09-03 | fix: disable tqdm's background monitor thread |
| 2026-09-02 | Fix crash when model config.json lacks suppress_ids keys |
| 2026-08-26 | Load the transcription stack on first use |
| 2026-07-27 | fix: handle mid-stream sample rate/format changes in decode_audio |

**但自 2025-11-19 起没有一条被合并。**

**[已核]** 2026-08-22 新开的 issue（`Importing faster_whisper.vad` 相关）
**零条评论**。

### CUDA 兼容是一个九个月没人管的活口子

**[已核]**：

| 日期 | 状态 | 标题 |
|:---|:---|:---|
| 2024-10-24 | **open**，16 条评论 | CUDA compatibility with CTranslate2 |
| 2025-12-04 | **open**，1 条评论 | Whisper error: This CTranslate2 package was not compiled with CUDA |
| 2026-04-13 | **closed，未合并** | fix: pin ctranslate2<4.6.3 to maintain CUDA compatibility |

最后那条是关键：**有人写了修复，PR 被关掉，没有合并。**

```bash
gh api 'search/issues?q=repo:SYSTRAN/faster-whisper+ctranslate2+CUDA+in:title' \
   --jq '.items[]|"\(.created_at[0:10])  \(.state)  评论\(.comments)  \(.title)"'
```

---

## 这对我们意味着什么

`dev-plan.md` 把 Voice 的本地部署当成**卖点而不是成本**：
「泰语数据敏感度高，本地跑是卖点」。本地跑就意味着我们要自己管 GPU 环境，
而 GPU 环境正是这个活口子所在的地方。

风险的形状是：**CTranslate2 每发一版，兼容缺口就宽一点，而没有人在补。**
不是「哪天它坏了」，是「它已经在坏，只是我们还没装」。

### 决策：不换方案，但必须锁版本 + 显式验 GPU 路径

**不换**的理由：faster-whisper 的权重许可已核（MIT，可商用），
换方案要重新核许可、重新评泰语准确率，成本远大于锁版本。
而且它不是坏了，是停更 —— 停更的库只要锁住依赖，行为是稳定的。

**必须做的两件事**：

1. **同时锁 `faster-whisper` 与 `ctranslate2` 的版本**，锁成一对实测可用的组合。
   只锁 faster-whisper 不够 —— 问题恰恰出在后端会自己往前走。
2. **部署时显式验 GPU 路径**，不能只验「import 成功」。
   那个 issue 的报错原文是 `This CTranslate2 package was not compiled with CUDA`——
   它在 import 阶段不报错，**跑起来才报**。

这两条已写进部署 Runbook 的待办（见下）。

### [待核] 备选方案

**没有核过，所以不写结论。** 需要核的是：`whisper.cpp`、`WhisperX`、
以及 faster-whisper 的活跃 fork（如果有）在**泰语**上的准确率与许可。

- **核法**：各仓库 LICENSE + 泰语基准测试（`dev-plan.md` 阶段 A 的
  「Voice 泰语评测」那一步本来就要做）
- **谁核**：Dev
- **什么时候核**：只有在锁版本方案实测不通过时才做 —— 现在做是浪费

---

## #15 LiteLLM 的 `enterprise/` 目录：风险确认存在，且在增长

**[已核]** `enterprise/` 目录**非常活跃**，最近提交就在昨天：

```bash
gh api 'repos/BerriAI/litellm/commits?path=enterprise&per_page=5' \
   --jq '.[]|"\(.commit.author.date[0:10])  \(.commit.message|split("\n")[0])"'
```

| 日期 | 提交 |
|:---|:---|
| 2026-09-05 | fix(hide-secrets): stop redacting benign identifiers |
| 2026-09-05 | bump: litellm-enterprise 0.1.64 -> 0.1.65 |
| 2026-09-05 | fix(batches): register ownership for every batch create |
| 2026-09-03 | Merge branch 'litellm_internal_staging' |

它有**自己的版本号**（`litellm-enterprise 0.1.65`）并在独立迭代。

**这坐实了 `oss-due-diligence.md` §1.1 记下的那条风险不是理论上的**：
功能确实可能被放进或挪进这个目录。升级检查不是走过场。

**结论不变**（绝不引用 `enterprise/`），但**检查频率要提**：
从「每次升级检查」改成「每次升级检查 + 每季度主动扫一次目录结构」——
因为我们可能长期不升级，而缺口是在我们不动的时候变宽的。

---

## 对既有文档的修正

| 文档 | 原来 | 改成 |
|:---|:---|:---|
| `facts-to-verify.md` #16 | [待核] 维护活跃度（最新发布约 10 个月前） | **[已核]** 维护者停更 9.5 个月，社区仍在提 PR 但无人合并；CUDA 兼容有活口子 |
| `facts-to-verify.md` #15 | [待核] `enterprise/` 有无吞掉我们用的功能 | **[已核]** 该目录高度活跃、有独立版本号；风险确认存在，检查频率提到每季度 |

**#16 从「存疑」变成「已确认有具体问题 + 已有应对」——
这比原来的措辞更严重，但也更可执行。**
