# 核查记录 · 2026-09-07 · Voice V0：基础在哪、是什么、缺什么

> 核 `facts-to-verify.md` 的 **P0 第 3 条**（Voice 组件现状），
> 并**改正** `verification-2026-09-06-voice-stack.md` 的适用范围。
> 线索来自 iDoris 侧的 `docs/agent/voice-v0-findings.md`（PR #5），
> **但本文的每条结论都自己重核过** —— 其中**两条与来件不一致，以本文为准**。
> 核的人：Dev。**证据命令都写在下面，可复现。**

---

## 结论先说

**「Voice 已有基础」这个假设是真的 —— 但基础不在我们以为的地方，
也不是我们以为的技术栈。**

它在 [`iDoris-ai/AgentEar`](https://github.com/iDoris-ai/AgentEar)，
一个已发布 `.app` 的 macOS 常驻程序（v0.4.2 · 2026-09-03）。

| 我们原来的假设 | 实际 |
|:---|:---|
| 基础在 iDoris 主仓库 | 在 **AgentEar**（iDoris 主仓库那 24 个文件全是文档，零代码）|
| 主链路 = faster-whisper × CTranslate2 | 主链路 = **SenseVoiceSmall q8 GGUF + FunASR llamacpp runtime + fsmn-vad** |
| 泰语是主链路顺带的 | 泰语是**另一条独立引擎**（whisper.cpp + 显式指定语言）|
| 泰语准确率无人测过 | **已经测过两批**（见 §3）—— 但没测我们要的那一层 |

> ⚠️ **本文的证据等级分三档，不要混读**：
> **[已核]** = 我跑了命令、看到了输出（仓库元数据、发布产物清单、文档原文）。
> **[AgentEar 自述]** = 我读到了他们的文档这么写，**但我们没有复测**。
> **[待核]** = 没有证据。
>
> **凡涉及「能不能跑起来」的，我们一律只有 [AgentEar 自述] 或 [待核]** ——
> 我没有 Apple Silicon 机器上的安装实测，也没有 Linux 实装。
> 这条分档是这次评审加的：**「产物存在」不等于「跑得起来」**，
> 正是 `architecture.md` §5 第 9 条说的那种绿灯。

**所以 V0 判「已完成」，但 V1/V2 的对象全部要换。**

> 🧭 **定位（jason 2026-09-07，不是核出来的，是拍板的）**：
> **AgentEar 是外部输入法组件**，未来还包括**独立的、可插入任意 agent 的
> 「说话器官」**。
>
> **所以我们对它的身份是「消费者」，不是「拥有者」** —— 这解释了为什么
> §8 那套许可与 `NOTICE` 义务是真义务而不是形式：**它是外部依赖。**
> 也意味着 Voice 这条线将来不止是入口（听），还可能是出口（说，见
> AgentEar `ADR-0005 tts-selection`）。

---

## 1. [已核] 主链路不是 faster-whisper

```bash
gh api 'repos/iDoris-ai/AgentEar/contents/README.md' --jq '.content' | base64 -d \
  | grep -inE "sensevoice|fsmn|gguf"
# → 80: curl ... SenseVoiceSmall-GGUF/resolve/main/sensevoice-small-q8.gguf
# → 81: curl ... fsmn-vad-GGUF/resolve/main/fsmn-vad.gguf
# → 335: **ASR:SenseVoiceSmall q8**(242 MiB,Apache-2.0),经四模型实测横比后选定
```

选型有 ADR（`docs/decisions/0001-asr-model-selection.md`），
四模型横比实测，**不是拍脑袋**。关键权衡记的是：
CER 四家相差不到 1 个百分点（准确率区分不出来），**差异全在工程形态** ——
SenseVoice 常驻内存是 Fun-ASR-Nano 的 27%、冷启动 0.2s vs 11.45s、单二进制零 Python。

**许可 Apache-2.0，可商用。** 与我们已核过的 whisper 权重是两件事，
`voice.md` §3 的许可表要整张换掉。

### ⚠️ 这一条推翻了 `verification-2026-09-06-voice-stack.md` 的适用范围

那份核查**本身没错**（faster-whisper 停更 9.5 个月、CUDA 兼容有活口子，
证据都还成立），**但它核的不是我们的主链路**。

**处理方式：不删，标注适用范围。** 理由——泰语支线走 whisper.cpp，
whisper 生态的维护状况仍然与我们相关，只是不再是「主链路存亡」级别的事。

---

## 2. [已核·与来件不一致] SenseVoice「即将停止维护」——**这条不成立**

iDoris 来件把它列为「换了个对象的新风险」。**核实后要划掉。**

来件引的是 AgentEar 的 `docs/asr-selection.md` §1，
**而那句话已经被同仓库的 ADR-0001 §3「更正一处早先的错误」撤销了**：

```bash
gh api 'repos/iDoris-ai/AgentEar/contents/docs/decisions/0001-asr-model-selection.md' \
  --jq '.content' | base64 -d | sed -n '108,120p'
```

> `asr-selection.md` §1 称 SenseVoice「官方标注即将停止维护」，
> 来源是厂商博客（funasr.com）的二手说法。**核实后不成立：**
> - GitHub `QwenAudio/SenseVoice`：未 archive，最后提交 2026-07-27，8951 stars
> - HF `SenseVoiceSmall-GGUF`：下载量 5755，**高于** Fun-ASR-Nano-GGUF 的 4813
>
> 这曾是排除 SenseVoice 的主要理由，它站不住。

**教训（值得记下来）**：一份文档被同仓库的另一份文档更正过之后，
**旧的那份还在原地躺着**。引用二手结论时，要顺手看一眼有没有 ADR 改过它。
我们自己的 `verification-*.md` 有同样的形状——所以本文第 §1 节
明确写了「要去改哪份旧文档的哪一段」，而不是只写新结论。

**真实剩下的上游风险只有一条**（这条成立）：
主链路依赖 `modelscope/FunASR` 的 **runtime 发布产物**
（tag 形如 `runtime-llamacpp-v0.2.6`），而不是自己编译。
产物停发 = 主链路断供。**对策与 faster-whisper 同形：锁版本 + 留一份产物副本。**

---

## 3. [已核·与来件不一致] 泰语 CER：AgentEar **已经有数字**，而且不止一批

来件写「AgentEar 那边也还没有这个数，所以你们的 V2 更该做」。
**前半句错，后半句对 —— 但理由完全不同。**

```bash
gh api 'repos/iDoris-ai/AgentEar/contents/docs/data/thai-cer-stats.txt' \
  --jq '.content' | base64 -d
```

**第一批：FLEURS 朗读语料，n=80，六个模型横比，自助法 4000 次算 95% CI**

| 模型 | CER | 95% CI |
|:---|---:|:---|
| `ggml-medium-q8_0` | **0.0608** | [0.0441, 0.0789] |
| `ggml-distill-q5_0` | 0.0622 | [0.0411, 0.0861] |
| `ggml-turbo-q5_0` | 0.0948 | [0.0726, 0.1187] |

**第二批：code-switch 语料 22 条**（`docs/data/thai-corpus-arm-2026-09/RESULTS.md`）

| 场景 | CER |
|:---|---:|
| 纯泰语对照组（6 条） | **3.9%**（3 条逐字全对）|
| 泰语夹英文技术词 | **31.1%** |
| 同上 + 一段 initial prompt | **18.4%** |

夹英文的失败是**系统性的**：39 个英文词里 36 个被音译成泰文字母，不是随机错。

### 所以 V2 不是「从零建评测」，是「补他们没覆盖的那一层」

**他们测过的**：朗读语料、安静环境、单人。
**他们没测的、也正是我们客户的场景**：会议室多人、电话、餐厅/大堂噪声。

而且 AgentEar 自己标注了一处污染，我们不能直接拿他们的数字对客户说：

> ⚠️ FLEURS 被 Thonburian（`medium`/`distill` 的出处）的模型卡
> **声明为训练数据**，`turbo` 未声明。turbo 的劣势有多少来自域外，测不出来。

**「6.08%」这个数不能写进销售话术** —— 它是朗读语料上的、且模型可能见过。
我们要交付给客户的仍然是 `voice.md` §4.1 那 20 段真实场景音频的数字。

**可以直接复用的**（V2 因此变便宜，不是变贵）：
`scripts/cer-thai.py`、`scripts/cer-stats.py`（含自助法 CI 与配对比较）、
`docs/data/thai-corpus-arm-2026-09/reference.tsv` 的 ground-truth 格式、
以及 `docs/thai-recorder.html` 这个采录页。

---

## 4. [已核] 平台限制：真正不成立的是 **Intel Mac**，不是「非 Apple Silicon」

这条会改我们对客户的承诺，所以逐条查了上游产物，**结论比来件窄**。

来件说「Apple Silicon 限定，因为上游 FunASR 只发 `macos-arm64`」。
前半句对，后半句的**推理范围过宽**：

```bash
gh api 'repos/modelscope/FunASR/releases/tags/runtime-llamacpp-v0.2.6' \
  --jq '.assets[].name' | grep -iE "macos|linux|windows"
```

| 平台 | v0.1.9 | v0.2.6 |
|:---|:---|:---|
| `macos-arm64` | ✅ | ✅ |
| **macOS x64（Intel）** | ❌ | ❌ |
| `linux-x64` / `linux-x64-avx2` / `linux-x64-vulkan` / `linux-arm64` | ✅ | ✅ |
| `windows-x64` / `-avx2` / `-vulkan` / `-cuda` | ✅ | ✅ |

### ⚠️ 这张表证明的到底是什么

**它证明的是「在我查的两个 tag 里，官方预编译产物有哪些」——仅此而已。**
它**不能**证明任何一个平台上装得起来、跑得起来，也**不能**证明 Intel 上
从源码编不出来。这是两件事，此前本文把它们混为一谈了。

**所以准确的说法是三层，每层各自标清证据等级**：

| 层 | 说法 | 证据等级 |
|:---|:---|:---|
| **Apple Silicon Mac**（M1+ / macOS 11+）| 有官方 `.app`，AgentEar 自述下载即用 | **[AgentEar 自述]** —— 我们没装过 |
| **Linux / Windows x64** | 官方**有** runtime 产物；但 AgentEar 的 app 壳是 macOS 的，要我们自己组装 | **[待核]** —— 从没试过，**不构成交付承诺** |
| **Intel Mac** | 所查的 `v0.1.9` 与 `v0.2.6` 两个 tag 里**没有** macOS x64 产物 | **[已核]**（仅限「无官方预编译产物」）；**能否自行从源码编译 = [待核]** |

**原来写的「runtime 层是通的」「Intel Mac 无解」两句都收回** ——
前者把「有产物」说成了「能跑」，后者把「没有官方产物」说成了「不可能」。

### 对 `starter-kit/README.md` §5 例外条款的影响

原文：「数据敏感度高的客户，Voice 可以单独部署在他们机器上」。

**这句现在只在两种情况下成立**：客户用 Apple Silicon Mac（开箱即用），
或客户有 Linux/Windows x64 机器且我们愿意付组装成本（**未实测**）。

清迈的小生意用什么机器，BD 比我清楚 —— 但**这条得先被知道，再决定怎么措辞**，
不能继续无条件写在对外文档里。

---

## 5. [已核] 一个我们没预料到的好消息：iDoris 会有两个真实消费者

AgentEar 的理解层（M2，**默认关**）已经在消费
`POST /v1/chat/completions` @ `127.0.0.1:8793`，**用的模型正是 Ornith**
—— iDoris 选定的常驻核心。

```bash
gh api 'repos/iDoris-ai/AgentEar/contents/scripts/setup-llm.sh' \
  --jq '.content' | base64 -d | grep -n 'HF_REPO'
# → 25: HF_REPO="mlx-community/Ornith-1.0-9B-6bit"
```

它目前要求用户自备本地 LLM（app 不打包那 7.8 GB 权重），
且设计上是「**连接优先、拉起是兜底**」—— 先按 `llm_url` 去连，
连得上就用，谁把服务起起来的不关 AgentEar 的事。

**对我们的含义**：iDoris 侧接 AgentEar 只需改一个 URL。
所以 Gateway/Router 的文本纵切会**在我们把三个模块改薄之前**先拿到真实流量，
一轮问题会先被别人踩过。这降低了 `todo.md` 那条移交路径的风险。

---

## 6. 对既有文档的修正（本 PR 一并改掉）

| 文档 | 原来 | 改成 |
|:---|:---|:---|
| `facts-to-verify.md` P0 #3 | [待核] Voice 组件现状 | **[已核 2026-09-07]** 基础在 AgentEar；技术栈四项全部与假设不符 |
| `starter-kit/voice.md` §1 | [待核] 基于源文档一句话的推断 | **[已核]** 现状盘点，指向 AgentEar |
| `starter-kit/voice.md` §3 | faster-whisper 三层许可表 | SenseVoice（主）+ whisper.cpp（泰语支线）两条链路 |
| `starter-kit/voice.md` §4.1 | 从零建泰语评测 | 补 AgentEar 未覆盖的**真实场景**层，复用其脚本 |
| `starter-kit/README.md` §5 | 「Voice 可以单独部署在他们机器上」 | 加平台前提（Apple Silicon 开箱 / Linux 要组装 / Intel Mac 不行）|
| `PRODUCT-FORM-AND-ROADMAP.md` V0–V2 | V0 硬阻塞，V1 锁 faster-whisper×ctranslate2 | V0 **已完成**；V1 对象换成 AgentEar 的 `vendor/bin` 产物版本 |
| `verification-2026-09-06-voice-stack.md` | 结论适用于主链路 | 加适用范围批注 —— **结论仍成立，但对象降级为泰语支线的相邻生态** |

---

## 7. [待核] 剩下的

| # | 事 | 核法 | 谁 | 什么时候 |
|:--|:---|:---|:---|:---|
| 1 | Linux x64 上把 FunASR runtime 跑起来的真实成本 | 拿一台 Linux 机器实装一次 | Dev | 只有在遇到非 Mac 客户时才做 —— 现在做是浪费 |
| 2 | 会议室/电话/噪声场景的泰语 CER | `voice.md` §4.1 的 20 段 | Dev | V2 |
| ~~3~~ | ~~AgentEar 的成果能不能直接用~~ | ✅ **[已核 2026-09-07]，见 §8** | — | — |

---

## 8. [已核] AgentEar 的成果可以用 —— **但有一个会咬人的条件**

原来这条列为 [待核]（「同一个组织不等于代码可以直接搬」）。
**iDoris 侧指出 AgentEar 已经核完了，我逐条复核，成立。**

| 项 | 许可 | 依据（我复核过的位置）|
|:---|:---|:---|
| AgentEar 本体 | **Apache-2.0** | 仓库 `LICENSE`（GitHub API `.license.spdx_id`）|
| FunASR llamacpp runtime | **MIT** | `NOTICE`，注明版本 `runtime-llamacpp-v0.1.9` |
| SenseVoiceSmall q8 GGUF | **Apache-2.0** | `NOTICE` |
| FSMN-VAD GGUF | **Apache-2.0** | `NOTICE` |
| **泰语 GGML（转换后权重）** | **MIT** | ADR-0004 §（上游 `biodatlab/distill-whisper-th-large-v3`）|

**我最担心的那条已经被挡掉了**：`plan-i18n-thai.md` §4 本来就立了一条门禁
——「**在确认再分发义务之前不要开始托管**」，然后 ADR-0004 里确认了 MIT 这条，
Release 说明已注明出处、revision 与许可。

> ⚠️ **一处措辞要改准**：ADR-0004 写的是「MIT 再分发只需保留版权声明」，
> **这句不完整** —— MIT 要求同时保留**版权声明与许可声明全文**
> （"the above copyright notice and this permission notice shall be included"）。
> 我们自己写 `NOTICE` 时按**两样都带**来做，不要照抄这句。
>
> ⚠️ **还有一处版本对不上**：AgentEar 的 `NOTICE` 记的 runtime 版本是
> **`v0.1.9`**，而 §4 的平台推理查的是 `v0.2.6`。两者都查过、结论一致，
> 但**我们自己锁版本时要锁哪一个，是 V1 要明确的事，不能想当然沿用**。

> 值得学的是**门禁的形状**：不是「记得核一下许可」，
> 而是「**核完之前不许开始托管**」—— 把待核项挂在一个具体动作前面，
> 而不是挂在待办列表里。

### 🔴 附带条件：**选 `medium` 就要重核 NOTICE，而 `medium` 恰好是 CER 最好的那个**

ADR-0004 的原话：

> 上游 `biodatlab/distill-whisper-th-large-v3` 是 **MIT**，再分发只需保留版权声明……
> **如果日后换成 Apache-2.0 的 `medium`，NOTICE 义务要重新过一遍。**

三个候选的上游许可**不一样**，这是最容易踩的地方：

| 代号 | HF 仓库 | 许可 | 我们表里的 CER |
|:---|:---|:---|---:|
| `medium` | `biodatlab/whisper-th-medium-combined` | **Apache-2.0** | **0.0608（最好）** |
| `distill` | `biodatlab/distill-whisper-th-large-v3` | **MIT** | 0.0622（AgentEar 选定）|
| `turbo` | `typhoon-ai/typhoon-whisper-turbo` | MIT | 0.0948 |

### ⚠️ 但更该说的是：**别为那 0.14 个百分点去选 `medium`**

**说清楚数字**：6.08% 是 `medium` 的 CER **成绩**，不是它领先的幅度。
它与 `distill`（6.22%）的差是 **0.14 个百分点**（绝对 0.0014，相对约 2%）。
ADR-0004 自己的配对比较写着：

> `medium` q8_0 − `distill` q5_0：Δ95%CI = **[−0.0142, +0.0099]** —— **未检出差异**

**为一个测不出来的差异，换来三样成本**：
① 多占 425 MB 内存（`medium` q8_0 峰值 RSS 1137 MB vs `distill` 712 MB，[AgentEar 自述]）；
② **要重新过一遍再分发审查**（Apache-2.0 的 NOTICE 义务是**条件性的** ——
   LICENSE §4(d) 只在上游确实带了 `NOTICE` 文件时才触发。所以准确说法是
   「**换模型要重做一次许可与 NOTICE 审查**」，不是「一定多一份固定负担」）；
③ FLEURS 污染对 `medium`/`distill` 是同向的，这个排名本来就不中立。

### ⚠️ 但「未检出差异」也不等于「一样好」——这条我自己也差点踩

AgentEar 的 `thai-cer-stats.txt` 结尾原话写得很清楚，值得照抄：

> 注：「未检出差异」≠「无差异」≠「等效」。
> 要声称等效需先定非劣界，再看 CI 上界是否落在界内。

那个区间 `[−0.0142, +0.0099]` **允许 `medium` 好上 1.42 个百分点**。
所以正确的说法不是「它们一样」，而是「**这次实验（n=80，朗读语料）
分不出它们**」。我们据此选 `distill`，理由是**内存与许可这两项确定的差异**，
**不是**因为准确率已被证明相同。

**结论：默认跟随 AgentEar 的 `distill` q5_0。**
只有当 §4.1 的**真实场景**评测里 `medium` 拉开**可检出**的差距时，才谈换 ——
**而那时第一件事是重做许可与 NOTICE 审查，不是先上线。**
