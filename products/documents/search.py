#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris Documents — search 动作的**回答层**。

设计见 docs/business/starter-kit/documents.md §4「search — 检索问答」。

## 这个 PR 做什么、不做什么

设计文档把 `search` 排在最后，理由是：

> 它是六个里唯一「做不好会砸招牌」的 —— **一个自信地答错的检索系统，
> 比没有检索系统更糟。**

但「砸招牌」的原因**不是检索质量，是回答纪律**。这两件事可以分开做，
而且应该分开做：

| | 状态 |
|:---|:---|
| 向量检索（pgvector、嵌入模型、泰文分块调优） | **仍然阻塞**（`dev-plan.md` 阶段 D） |
| **回答纪律**（没有就说没有、答案必须能追到出处） | 本模块，现在就能建、能测 |

所以检索被放在 `Retriever` 协议后面，`InMemoryRetriever` 只用于测试。
**这个模块不声称 search 端到端能用了** —— 它声称的是：
等检索接上之后，模型不会拿通用知识去补客户文档里没有的东西。

## 三条不可破的规则

1. **没命中就说没有。** 检索为空、或最高分低于阈值时，
   唯一可接受的输出是「这批文件里没有」。模型给任何别的东西都拒绝。

   这是整个模块的支点。客户问「合同里写的违约金是多少」，
   文档里恰好没有 —— 模型用通用知识答一个「通常是 5%–10%」，
   **读起来专业、语气自信、格式完整**，而它是编的。
   客户拿这个数去谈判，损失是真的。

2. **答案里的每个数字都必须出现在被引用的块里。**
   由代码逐个核，不是叮嘱模型。这一条和 `rewrite` 是同一个判据：
   数字是最容易被「顺手补完整」的东西，也是后果最重的。

3. **每条回答都要带出处，且出处必须是真的检索到的块。**
   编出处比不给出处更危险 —— 它看起来是可核对的，人会以为已经核过了。

## 为什么阈值这一条单独拎出来

「检索返回了东西」不等于「检索到了答案」。向量检索**总会**返回 top-k，
哪怕全都不相关 —— 相似度 0.11 的块也是 top-1。

不设阈值的话，规则 1 形同虚设：永远有命中，于是永远不会说「没有」。
**这是这类系统最常见的坏法**，而且它表现为「回答率 100%」，
看起来像是做得好。

用法:
    r = InMemoryRetriever(ir.chunk_for_embedding())
    hits = r.search("违约金是多少", k=5)
    ans = answer("违约金是多少", hits, model_output)

    python3 search.py --self-test
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any, Protocol

from docir import DocIR


class SearchRejected(ValueError):
    """回答不合格。**拒绝，不发给客户。**"""


class FabricatedAnswerError(SearchRejected):
    """答案里有追不到出处的内容。**这个模块存在的全部理由。**"""


# 命中阈值。低于这个分数一律视为没命中。
#
# **[待核] 0.35 这个值没有外部依据** —— 它是一个占位的保守值。
# 核法:接上真实嵌入模型后,用 §4 验收标准的 20 个问题标定 ——
# 那 5 个「答案不在文档里」的问题,最高分必须落在阈值之下。
# 谁核:Dev,接 pgvector 的那一步。
#
# 在标定之前**宁可偏高**:偏高的后果是多答几次「没有」(客户会追问,我们能补),
# 偏低的后果是拿不相关的块编一个答案(客户不会追问,因为它看起来是对的)。
MIN_SCORE = 0.35

# 没命中时的标准回答。**写死** —— 让模型自由发挥这句话,
# 它会写成「我在文档中没有找到明确信息，不过通常来说……」,
# 后半句正是我们要挡的东西。
NOT_FOUND_TH = "ไม่พบข้อมูลนี้ในเอกสารชุดนี้"
NOT_FOUND_EN = "This information is not in these documents."
NOT_FOUND_ZH = "这批文件里没有这条信息。"
NOT_FOUND_TEXTS = frozenset({NOT_FOUND_TH, NOT_FOUND_EN, NOT_FOUND_ZH})

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def numbers_in(text: str) -> set[str]:
    """文本里的数字，归一化。**泰文数字一起数。**"""
    return {n.replace(",", "") for n in _NUM.findall(text.translate(_THAI_DIGITS))}


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    text: str
    score: float
    block_ids: tuple[str, ...]
    locators: tuple[str, ...]
    page: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"chunk_id": self.chunk_id, "score": round(self.score, 4),
                "block_ids": list(self.block_ids), "locators": list(self.locators),
                "page": self.page}


class Retriever(Protocol):
    """检索后端。**真实实现是 pgvector，那一步仍然阻塞。**

    把它放在协议后面，是为了让回答纪律现在就能建、能测 ——
    而不是等检索做完再一起做，那样两件事的 bug 会混在一起。
    """

    def search(self, query: str, k: int = 5) -> list[RetrievedChunk]: ...


class InMemoryRetriever:
    """**仅用于测试。** 词面重合度打分，不是真检索。

    刻意不假装它是个真检索器 —— 它的分数没有语义，
    只是为了让回答层的测试能构造「高分命中」和「低分不命中」两种情形。
    """

    def __init__(self, chunks: list[dict[str, Any]],
                 scores: dict[str, float] | None = None) -> None:
        self._chunks = chunks
        self._scores = scores or {}

    def search(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        out: list[RetrievedChunk] = []
        q = set(query.lower())
        for i, c in enumerate(self._chunks):
            cid = c.get("chunk_id") or "c%d" % i
            if cid in self._scores:
                score = self._scores[cid]
            else:
                t = set(c["text"].lower())
                score = len(q & t) / len(q | t) if (q | t) else 0.0
            out.append(RetrievedChunk(
                chunk_id=cid, text=c["text"], score=score,
                block_ids=tuple(c.get("block_ids", ())),
                locators=tuple(c.get("locators", ())),
                page=c.get("page", 0)))
        out.sort(key=lambda x: x.score, reverse=True)
        return out[:k]


@dataclass
class Answer:
    question: str
    found: bool
    text: str
    citations: list[RetrievedChunk] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"question": self.question, "found": self.found, "text": self.text,
                "citations": [c.as_dict() for c in self.citations],
                "notes": self.notes}


def has_hit(retrieved: list[RetrievedChunk], min_score: float = MIN_SCORE) -> bool:
    """有没有真的命中。

    **「检索返回了东西」不等于「检索到了答案」。**
    向量检索总会返回 top-k，哪怕全都不相关 —— 相似度 0.11 的块也是 top-1。
    """
    return bool(retrieved) and max(c.score for c in retrieved) >= min_score


def not_found_answer(question: str, lang: str = "zh") -> Answer:
    text = {"th": NOT_FOUND_TH, "en": NOT_FOUND_EN}.get(lang, NOT_FOUND_ZH)
    return Answer(question=question, found=False, text=text)


def answer(question: str, retrieved: list[RetrievedChunk],
           model_output: dict[str, Any], min_score: float = MIN_SCORE,
           lang: str = "zh") -> Answer:
    """把模型的回答校验成可以发给客户的东西。

    `model_output` 形如：
        {"found": True, "text": "违约金为合同金额的 5%",
         "citations": ["c3"]}

    **模型只负责组织语言。** 有没有命中、能不能答、数字对不对，
    全部在这里判。
    """
    if not question.strip():
        raise SearchRejected("空问题")

    by_id = {c.chunk_id: c for c in retrieved}
    claimed_found = bool(model_output.get("found"))
    text = str(model_output.get("text", "")).strip()
    cited_ids = [str(x) for x in (model_output.get("citations") or [])]

    # ── 规则 1:没命中就说没有 ────────────────────────────────────
    if not has_hit(retrieved, min_score):
        if claimed_found:
            best = max((c.score for c in retrieved), default=0.0)
            raise FabricatedAnswerError(
                "检索没有命中（最高分 %.3f < 阈值 %.2f，共 %d 个候选），"
                "模型却给出了答案：%r\n"
                "**这是这个模块要挡的核心情形。** 客户问「合同里的违约金是多少」，"
                "文档里恰好没有 —— 模型用通用知识答一个「通常是 5%%–10%%」，"
                "读起来专业、语气自信、格式完整，而它是编的。"
                "客户拿这个数去谈判，损失是真的。"
                % (best, min_score, len(retrieved), text[:80]))
        # 「没有」这句话也写死,不让模型自由发挥 ——
        # 它会写成「我没有找到明确信息,不过通常来说……」,后半句正是要挡的。
        if text and text not in NOT_FOUND_TEXTS:
            raise SearchRejected(
                "没命中时的回答必须用标准措辞，得到：%r\n"
                "让模型自己写这句话，它会写成「没有找到明确信息，不过通常来说……」"
                "—— 后半句正是我们要挡的东西" % text[:80])
        return not_found_answer(question, lang)

    # ── 命中,但模型说没有:允许,且要留痕 ──────────────────────────
    if not claimed_found:
        a = not_found_answer(question, lang)
        a.notes.append(
            "检索有命中（最高分 %.3f）但模型判断答不了 —— 这是允许的，"
            "模型比阈值更懂「这块内容其实不回答这个问题」。留痕以便标定阈值"
            % max(c.score for c in retrieved))
        return a

    # ── 规则 3:出处必须真实 ──────────────────────────────────────
    if not cited_ids:
        raise SearchRejected(
            "模型声称找到了答案却没给出处 —— **没有出处的答案没人敢用**")
    unknown = [c for c in cited_ids if c not in by_id]
    if unknown:
        raise FabricatedAnswerError(
            "模型引用了没有被检索到的块：%s\n"
            "**编出处比不给出处更危险** —— 它看起来是可核对的，"
            "人会以为已经核过了" % unknown)
    citations = [by_id[c] for c in dict.fromkeys(cited_ids)]

    if not text:
        raise SearchRejected("模型声称找到了答案却没给正文")

    # ── 规则 2:答案里的数字必须出现在被引用的块里 ────────────────
    cited_text = "\n".join(c.text for c in citations)
    fabricated = numbers_in(text) - numbers_in(cited_text)
    if fabricated:
        raise FabricatedAnswerError(
            "答案里的数字 %s 在被引用的块里找不到。\n"
            "答案：%r\n引用：%s\n"
            "数字是最容易被「顺手补完整」的东西，也是后果最重的 ——"
            "客户会直接拿它去做决定。"
            % (sorted(fabricated), text[:80], [c.chunk_id for c in citations]))

    return Answer(question=question, found=True, text=text, citations=citations)


# ---------------------------------------------------------------- 自检

def _chunks() -> list[dict[str, Any]]:
    return [
        {"chunk_id": "c1", "text": "第四条 违约金为合同金额的 5%。",
         "block_ids": ["b4"], "locators": ["p1@0,30"], "page": 1},
        {"chunk_id": "c2", "text": "第二条 甲方应于收到发票后 30 天内付款。",
         "block_ids": ["b2"], "locators": ["p1@0,10"], "page": 1},
    ]


def self_test() -> int:
    fails: list[str] = []
    r = InMemoryRetriever(_chunks(), scores={"c1": 0.9, "c2": 0.1})
    hits = r.search("违约金", k=5)

    a = answer("违约金是多少", hits,
               {"found": True, "text": "违约金为合同金额的 5%。", "citations": ["c1"]})
    if not a.found or not a.citations:
        fails.append("正常路径没答出来：%r" % a.as_dict())

    # 没命中却给答案 —— 必须拒
    cold = InMemoryRetriever(_chunks(), scores={"c1": 0.1, "c2": 0.05}).search("x")
    try:
        answer("保修期多久", cold,
               {"found": True, "text": "通常是 1 年。", "citations": ["c1"]})
        fails.append("没命中却给答案，没被拒 —— 这个模块的支点是死的")
    except FabricatedAnswerError:
        pass

    # 没命中 → 标准措辞
    a2 = answer("保修期多久", cold, {"found": False, "text": ""})
    if a2.found or a2.text != NOT_FOUND_ZH:
        fails.append("没命中时的回答不对：%r" % a2.as_dict())

    # 编数字 —— 必须拒
    try:
        answer("违约金是多少", hits,
               {"found": True, "text": "违约金为 5%，上限 100,000 泰铢。",
                "citations": ["c1"]})
        fails.append("答案里编造的数字没被拒")
    except FabricatedAnswerError:
        pass

    if fails:
        print("✗ %d 项失败" % len(fails), file=sys.stderr)
        for f in fails:
            print("    " + f, file=sys.stderr)
        return 1
    print("✓ search 自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else (print(__doc__) or 0))
