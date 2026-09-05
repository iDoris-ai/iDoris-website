# iDoris Documents — DocIR 中间表示

> 设计见 [`../../docs/business/starter-kit/documents.md`](../../docs/business/starter-kit/documents.md) §3.1
> 状态：**隔离层 + `extract` 动作已完成**。其余五个动作尚未实现。

## 为什么这一层值得自己写

Docling 的输出是它自己的数据结构。**六个动作全部只依赖 DocIR，不直接依赖 Docling**——
Docling 换版本、甚至整个换掉，六个动作的代码都不用动。

> 这是**唯一一处值得我们自己造轮子的地方**：它是隔离层，不是重复实现。

## 两个字段是硬要求

`page` 与 `bbox` **必须**保留，且 `Block.validate()` 会拒绝越界或非法的：

- `search` 要回答「在哪份文件第几页」
- `extract` 要让客户能点回原文核对

> **没有出处的抽取结果没人敢用。**

`chunk_for_embedding()` 切块之后**仍然带 `block_ids` 与 `locators`**——
切碎了也要能回溯。

## 泰文的三个坑，这一层解决两个

**① 泰文没有词间空格。** 常规分词器按空格切，整段会被当成一个词，检索召回极差。
`_SENT_END` 刻意**不含空格**，按句末标点与 `ๆ` 断句，超长再按**字符数**硬切。

**② 泰文 PDF 的字形重排。** 入口统一做 Unicode **NFC 归一化**。
真实的坑是声调符（ccc=107）排在了元音符（ccc=103）前面——
肉眼看着一样，字符串比对全错，`extract` 的 schema 校验和 `search` 的向量检索都会错。

**③ 泰英混排的语言检测** → `lang_detected` 是**数组**、按 block 汇总，不是整篇一个值。
（这一条由解析层填，DocIR 只保证结构允许。）

## 怎么跑

```bash
python3 docir.py            # 烟测
python3 test_docir.py       # 完整测试（13 个测试函数）
./mutation_check.sh         # 变异测试 ← 最重要的那个
```

## 变异测试这次抓到的是**两个真实的测试漏洞**

前两次它抓到的是我自己写错的变异（变异没生效）。这次不同——**变异生效了，
是测试真的漏了**：

**漏洞 1：`test_nfc_normalization_on_ingest` 等于空转。**
它用 `NFD("กำ")` 造「未归一化」的输入，但 **SARA AM 根本不可分解**，
`NFD == NFC`。去掉整个归一化步骤，测试照样通过。
已改用真会被规范排序重排的序列（`ก + MAI TRI + SARA U`），
并加了一条前置断言：**先验证测试样本本身确实会被重排**，否则这个测试测不出任何东西。

**漏洞 2：「切成了多块」分辨不出边界规则。**
无空格的泰文长段会走「超长硬切」兜底——把边界规则改成「按空格切」，
照样能切出多块。已新增 `test_splits_at_sentence_boundary_not_arbitrary`：
用**每句都短于 `max_chars`** 的样本（硬切不会介入），断言**每一块都以句末标点收尾**。

> 这就是为什么变异测试值得写：单元测试全绿，只说明它们没报警，
> 不说明它们**能**报警。

## 一个在写测试时抓到的真 bug

`chunk_for_embedding` 的默认 `overlap` 曾写死成 `80`。当 `max_chars=80` 时，
它撞上自己的校验「`overlap` 必须 < `max_chars`」**直接抛错**——
**默认值在合法参数下自炸**。

已改成 `max_chars // 10`，并补了回归测试
（`test_default_overlap_never_self_rejects`），跑一圈 `max_chars`
从 50 到 800 断言都不炸，同时用负对照确认**显式**传非法 `overlap` 仍被拒。

## 还没做的

六个动作（`summarize` / `extract` / `compare` / `translate` / `rewrite` / `search`）。
按 `documents.md` §6，先做 `extract` 与 `translate`——演示效果最直接、技术风险最低。

`search` 排最后：它是六个里唯一「做不好会砸招牌」的——
**一个自信地答错的检索系统，比没有检索系统更糟。**
