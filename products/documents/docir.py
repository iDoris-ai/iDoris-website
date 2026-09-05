#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris Documents — DocIR：文档中间表示。

设计见 docs/business/starter-kit/documents.md §3.1。

## 为什么这一层值得自己写

Docling 的输出是它自己的数据结构。**六个动作全部只依赖 DocIR，不直接依赖 Docling** ——
Docling 换版本、甚至整个换掉，六个动作的代码都不用动。

这是**唯一一处值得我们自己造轮子的地方**：它是隔离层，不是重复实现。

## 两个字段是硬要求，不是可选

`page` 与 `bbox` 必须保留：
  - `search` 要回答「在哪份文件第几页」
  - `extract` 要让客户能点回原文核对

**没有出处的抽取结果没人敢用。** 所以 `Block` 强制要求 locator。

## 泰文的三个坑，在这一层解决两个

见 documents.md §3.3：

1. **泰文没有词间空格** → `chunk_for_embedding()` 对泰文按**字符数**切、
   按句子边界断，不按空格。常规分词器会把整句切成一块，检索召回极差。
2. **泰文 PDF 的字形重排** → 入库前统一做 **Unicode NFC 归一化**。
   部分泰文 PDF 提取出来元音符号与辅音顺序颠倒，肉眼看着对、字符串比对全错。
3. 泰英混排的语言检测 → `lang_detected` 是**数组**、按 block 标注，
   不是整篇一个值。（这一条由解析层填，DocIR 只保证结构允许。）

用法：
    ir = DocIR.from_blocks(doc_id="sha256:...", source=Source(...), blocks=[...])
    ir.validate()
    chunks = ir.chunk_for_embedding(max_chars=800)

    python3 docir.py --self-test
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable


BLOCK_TYPES = ("heading", "paragraph", "table", "list", "figure")

# 泰文字符范围。用来判断一个块要不要走「按字符数切」的路径。
_THAI_RE = re.compile(r"[฀-๿]")

# 句子边界。泰文常用 ๆ 与空行分句；中英用常规标点。
# **刻意不含空格** —— 泰文没有词间空格，用空格切会把整句切成一块。
_SENT_END = re.compile(r"(?<=[。．.!?！？;；\n])|(?<=ๆ )")


class DocIRError(ValueError):
    """DocIR 结构不合法。**在入库前炸，不要等到 search 召回为空才发现。**"""


def normalize_thai(text: str) -> str:
    """Unicode NFC 归一化。

    泰文 PDF 提取常出现元音符号与辅音顺序颠倒 —— 肉眼看着对、字符串比对全错。
    NFC 把它们归到规范序，这样 extract 的 schema 校验和 search 的向量检索
    才有可比性。

    对非泰文文本这是无害操作（NFC 是幂等的）。
    """
    return unicodedata.normalize("NFC", text)


def has_thai(text: str) -> bool:
    return bool(_THAI_RE.search(text))


@dataclass(frozen=True)
class SourceInfo:
    filename: str
    mime: str
    pages: int

    def validate(self) -> None:
        if not self.filename:
            raise DocIRError("source.filename 必填")
        if self.pages < 1:
            raise DocIRError("source.pages 必须 ≥1，得到 %r" % self.pages)


@dataclass
class Block:
    id: str
    type: str
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    lang: list[str] = field(default_factory=list)
    table: dict[str, Any] | None = None

    def validate(self, max_page: int) -> None:
        if not self.id:
            raise DocIRError("block 缺 id")
        if self.type not in BLOCK_TYPES:
            raise DocIRError("block %r 的 type %r 非法（可用：%s）"
                             % (self.id, self.type, ", ".join(BLOCK_TYPES)))
        # 出处是硬要求 —— 没有它，extract 的结果客户点不回原文
        if not 1 <= self.page <= max_page:
            raise DocIRError("block %r 的 page %r 超出 1..%d —— "
                             "没有正确页码的块，抽取结果就无法回溯"
                             % (self.id, self.page, max_page))
        if len(self.bbox) != 4:
            raise DocIRError("block %r 的 bbox 需要 4 个数" % self.id)
        x0, y0, x1, y1 = self.bbox
        if not (x1 > x0 and y1 > y0):
            raise DocIRError("block %r 的 bbox 不是有效矩形：%r" % (self.id, self.bbox))
        if self.type == "table" and self.table is None:
            raise DocIRError("block %r 声明 type=table 却没有 table 数据" % self.id)
        if self.type != "table" and self.table is not None:
            raise DocIRError("block %r 的 type 是 %r 却带了 table 数据"
                             % (self.id, self.type))

    def locator(self) -> str:
        """给 citation 用的定位串。"""
        return "p%d@%.0f,%.0f" % (self.page, self.bbox[0], self.bbox[1])


@dataclass
class DocIR:
    doc_id: str
    source: SourceInfo
    blocks: list[Block]
    lang_detected: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ 构造

    @classmethod
    def from_blocks(cls, doc_id: str, source: SourceInfo,
                    blocks: Iterable[Block]) -> "DocIR":
        norm: list[Block] = []
        langs: set[str] = set()
        for b in blocks:
            # 归一化在入口做一次，之后全链路可比对
            nb = Block(id=b.id, type=b.type, page=b.page, bbox=tuple(b.bbox),  # type: ignore[arg-type]
                       text=normalize_thai(b.text), lang=list(b.lang), table=b.table)
            norm.append(nb)
            langs.update(nb.lang)
        return cls(doc_id=doc_id, source=source, blocks=norm,
                   lang_detected=sorted(langs))

    # ------------------------------------------------------------ 校验

    def validate(self) -> None:
        if not self.doc_id:
            raise DocIRError("doc_id 必填")
        self.source.validate()
        if not self.blocks:
            raise DocIRError("blocks 不能为空 —— 空文档说明解析失败，"
                             "不该静默进入后续动作")
        seen: set[str] = set()
        for b in self.blocks:
            if b.id in seen:
                raise DocIRError("block id 重复：%r —— citation 会指向错误的块" % b.id)
            seen.add(b.id)
            b.validate(self.source.pages)

    # ------------------------------------------------------------ 分块

    def chunk_for_embedding(self, max_chars: int = 800,
                            overlap: int | None = None) -> list[dict[str, Any]]:
        """切块供向量检索用。

        **对泰文按字符数切、按句子边界断，不按空格。**
        这是 documents.md §3.3 第 1 条的实现 —— 常规分词器按空格切，
        而泰文没有词间空格，整段会被当成一个词，检索召回极差。

        每个块都带 `block_ids` 与 `locators` —— **切块之后仍然能回溯出处**。
        """
        if max_chars < 50:
            raise DocIRError("max_chars 太小（%d），切出来的块没有语义" % max_chars)
        # 默认取 max_chars 的 10%。写死成常数会在小 max_chars 时撞上
        # 「overlap >= max_chars」这条自己的校验 —— 默认值不该在合法参数下自炸。
        if overlap is None:
            overlap = max(0, max_chars // 10)
        if not 0 <= overlap < max_chars:
            raise DocIRError("overlap 必须在 0..max_chars 之间，得到 %r" % overlap)

        chunks: list[dict[str, Any]] = []
        for b in self.blocks:
            if b.type == "figure" or not b.text.strip():
                continue
            for piece in _split_text(b.text, max_chars, overlap):
                chunks.append({
                    "text": piece,
                    "block_ids": [b.id],
                    "locators": [b.locator()],
                    "page": b.page,
                    "has_thai": has_thai(piece),
                })
        return chunks

    # ------------------------------------------------------------ 序列化

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["blocks"] = [dict(x, bbox=list(x["bbox"])) for x in d["blocks"]]
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DocIR":
        return cls(
            doc_id=d["doc_id"],
            source=SourceInfo(**d["source"]),
            blocks=[Block(id=b["id"], type=b["type"], page=b["page"],
                          bbox=tuple(b["bbox"]), text=b["text"],
                          lang=list(b.get("lang", [])), table=b.get("table"))
                    for b in d["blocks"]],
            lang_detected=list(d.get("lang_detected", [])),
        )


def _hard_split(s: str, max_chars: int, overlap: int) -> list[str]:
    """按字符硬切。步长至少 1，避免 overlap 接近 max_chars 时死循环。"""
    step = max(1, max_chars - overlap)
    return [s[i:i + max_chars] for i in range(0, len(s), step)]


def _split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """按句子边界切，超长再按字符硬切。**不按空格。**

    **不变式：返回的每一块长度都 ≤ max_chars。** 这一条由函数末尾的断言守住。

    早先有个 bug：拼接 `cur = cur[-overlap:] + s` 之后没有再检查长度，
    当 `overlap + len(s) > max_chars` 时会产出远超上限的块
    （max_chars=50 切出过 86 字）。超长块喂进 embedding 会被模型端**静默截断**，
    检索召回变差而没有任何东西报错。现在拼接后立刻兜底硬切。
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    sents = [s for s in _SENT_END.split(text) if s and s.strip()]
    out: list[str] = []
    cur = ""
    for s in sents:
        if len(s) > max_chars:                # 单句就超长（泰文长段常见）→ 硬切
            if cur:
                out.append(cur)
                cur = ""
            out.extend(_hard_split(s, max_chars, overlap))
            continue
        if len(cur) + len(s) <= max_chars:
            cur += s
        else:
            out.append(cur)
            cur = (cur[-overlap:] if overlap else "") + s
            # 带上 overlap 之后可能已经超长 —— 立刻兜底，
            # 不能等到下一轮直接 append 出去。
            if len(cur) > max_chars:
                pieces = _hard_split(cur, max_chars, overlap)
                out.extend(pieces[:-1])
                cur = pieces[-1]
    if cur.strip():
        out.append(cur)

    result = [c.strip() for c in out if c.strip()]
    # 不变式兜底。走到这里还超长说明上面漏了一条路径 —— 与其把超长块发出去
    # 让 embedding 静默截断，不如在这里炸。
    over = [len(c) for c in result if len(c) > max_chars]
    if over:
        raise DocIRError(
            "内部错误：切出了超过 max_chars=%d 的块 %s —— "
            "超长块会被 embedding 静默截断，检索召回变差且不报错" % (max_chars, over))
    return result


def doc_id_for(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------- 自检

def _sample() -> DocIR:
    return DocIR.from_blocks(
        doc_id="sha256:demo", source=SourceInfo("quote.pdf", "application/pdf", 3),
        blocks=[
            Block("b1", "heading", 1, (10, 10, 200, 30), "ใบเสนอราคา", ["th"]),
            Block("b2", "paragraph", 1, (10, 40, 400, 120),
                  "เรียน คุณลูกค้า ขอบคุณที่ให้ความสนใจ เรายินดีเสนอราคาดังนี้", ["th"]),
            Block("b3", "paragraph", 2, (10, 10, 400, 60),
                  "Total amount: 45,000 THB. Valid for 30 days.", ["en"]),
            Block("b4", "table", 2, (10, 80, 400, 200), "房型 价格",
                  ["zh"], table={"rows": [["Deluxe", "3500"]], "header": True}),
        ])


def self_test() -> int:
    fails: list[str] = []
    ir = _sample()
    ir.validate()

    if ir.lang_detected != ["en", "th", "zh"]:
        fails.append("lang_detected 应按 block 汇总并排序，得到 %r" % ir.lang_detected)

    # 出处可回溯
    if ir.blocks[0].locator() != "p1@10,10":
        fails.append("locator 格式错：%r" % ir.blocks[0].locator())

    # NFC 归一化
    decomposed = "ก" + "ำ"          # 组合形式
    if normalize_thai(decomposed) != unicodedata.normalize("NFC", decomposed):
        fails.append("NFC 归一化没生效")

    # 分块保留出处
    chunks = ir.chunk_for_embedding(max_chars=100, overlap=10)
    if not chunks:
        fails.append("分块结果为空")
    if not all(c["locators"] for c in chunks):
        fails.append("有分块丢了 locators —— 切块之后就回溯不了出处")

    # 校验必须真的拦
    for label, mut in (
        ("重复 block id", lambda d: d.blocks.append(d.blocks[0])),
        ("空 blocks", lambda d: d.blocks.clear()),
    ):
        bad = _sample()
        mut(bad)
        try:
            bad.validate()
            fails.append("校验失效：%s 没被拒" % label)
        except DocIRError:
            pass

    # 往返
    if DocIR.from_dict(ir.to_dict()).to_dict() != ir.to_dict():
        fails.append("to_dict/from_dict 往返不一致")

    if fails:
        print("✗ docir 自检失败", file=sys.stderr)
        for f in fails:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ docir 自检通过（结构校验 · NFC 归一化 · 分块保留出处 · 往返）")
    return 0


if __name__ == "__main__":
    sys.exit(self_test())
