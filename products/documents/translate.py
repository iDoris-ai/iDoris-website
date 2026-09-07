#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris Documents — translate 动作：保留结构的翻译。

设计见 docs/business/starter-kit/documents.md §4 的 translate 一节。

## 两个坑，都在这里解决

**坑 1：人名、公司名、地名不该翻。**
「Baan Rimping」译成「House Rimping」，客户会立刻失去信任 ——
那是他们酒店的名字。对策：先标出专有名词，翻译时**指示保留原文**，
译后**校验它们确实还在**（`verify_terms_preserved`）。

**坑 2：泰文敬语体系译成英文会全丢，反向则容易用错。**
泰文的 ครับ/ค่ะ、层级用词（ท่าน vs คุณ vs เธอ）承载着社会关系，
英文没有对应物。反向翻译时，用错一级敬语，收件人会觉得不礼貌 ——
而写的人完全不知道。对策：`formality` 是**必填参数**，默认商务正式。

## 为什么按 block 翻而不是整篇

整篇翻译会丢掉表格与版式。按 block 翻，保留 DocIR 的结构，最后重组 ——
这也是 DocIR 隔离层存在的价值之一。

## 模型做什么、不做什么

**做**：把一个 block 的文本译成目标语言。
**不做**：决定哪些词不翻（我们给它术语表）、决定敬语级别（我们给它参数）、
重组文档结构（我们按 block id 拼回去）。

    python3 translate.py --self-test
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any

from docir import DocIR, Block, has_thai

LANGS = ("th", "en", "zh")

# 敬语级别。泰文是**必须**显式指定的 —— 没有「中立」这个选项，
# 不选就是选了一个，而选错的后果是收件人觉得不礼貌，写的人还不知道。
FORMALITY = ("business", "formal", "casual")
DEFAULT_FORMALITY = "business"


class TranslateRejected(ValueError):
    """译文不合格。**拒绝，不要「大概能用」。**"""


@dataclass(frozen=True)
class Term:
    """一条不该翻的专有名词。"""
    source: str              # 原文写法
    keep_as: str = ""        # 目标语里保留成什么；空表示原样保留
    gloss: str = ""          # 可选的括注译名

    def rendered(self) -> str:
        base = self.keep_as or self.source
        return "%s（%s）" % (base, self.gloss) if self.gloss else base


@dataclass
class Glossary:
    """术语表。**由客户确认，不由模型猜。**

    Discovery 的 90 天路线图 W1 就是建这张表（见 sample-discovery-hotel）——
    「≥80 条，前台确认过」是那一周的可验收产出。
    """
    terms: list[Term] = field(default_factory=list)

    def validate(self) -> None:
        seen: set[str] = set()
        for t in self.terms:
            if not t.source.strip():
                raise TranslateRejected("术语表里有空的 source")
            if t.source in seen:
                raise TranslateRejected("术语重复：%r" % t.source)
            seen.add(t.source)

    def found_in(self, text: str) -> list[Term]:
        return [t for t in self.terms if t.source in text]


@dataclass
class TranslatedBlock:
    block_id: str
    source_text: str
    translated: str
    page: int
    locator: str
    terms_kept: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"block_id": self.block_id, "translated": self.translated,
                "page": self.page, "locator": self.locator,
                "terms_kept": list(self.terms_kept)}


@dataclass
class TranslateResult:
    doc_id: str
    target_lang: str
    formality: str
    blocks: list[TranslatedBlock] = field(default_factory=list)

    def as_text(self) -> str:
        """按原文顺序重组。**结构由我们拼，不由模型拼。**"""
        return "\n\n".join(b.translated for b in self.blocks)

    def as_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "target_lang": self.target_lang,
                "formality": self.formality,
                "blocks": [b.as_dict() for b in self.blocks]}


def build_instruction(target_lang: str, formality: str,
                      terms: list[Term]) -> str:
    """给模型的指示。**把「不翻什么」和「多正式」写死，不让它自己决定。**"""
    lines = [
        "Translate the text into %s." % target_lang,
        "Keep the register: %s." % formality,
        "Do not add, remove, or reorder any information.",
    ]
    if terms:
        lines.append("Do NOT translate these proper nouns — keep them verbatim:")
        lines.extend("  - %s" % t.source for t in terms)
    if target_lang == "th":
        lines.append(
            "Thai politeness particles matter: use the register above consistently. "
            "Do not mix ครับ and ค่ะ within one document.")
    return "\n".join(lines)


def verify_terms_preserved(translated: str, terms: list[Term]) -> list[str]:
    """校验专有名词确实还在译文里。返回**丢失**的那些。

    这一步是硬要求：模型经常会「顺手」把人名地名也译了，
    而它不会报告自己这么做了。
    """
    return [t.source for t in terms
            if (t.keep_as or t.source) not in translated]


# 泰文敬语粒子。混用会显得不专业。
_PARTICLE_MALE = re.compile(r"ครับ|คับ")
_PARTICLE_FEMALE = re.compile(r"ค่ะ|คะ")


def check_thai_particles(text: str) -> str | None:
    """一份文档里混用 ครับ 与 ค่ะ 是最常见的泰文翻译事故。返回问题描述或 None。"""
    if _PARTICLE_MALE.search(text) and _PARTICLE_FEMALE.search(text):
        return ("同一份译文里同时出现 ครับ 与 ค่ะ —— "
                "泰文里这两者对应说话人的性别，混用会显得不专业")
    return None


def translate(ir: DocIR, target_lang: str,
              model_output: dict[str, str],
              glossary: Glossary | None = None,
              formality: str = DEFAULT_FORMALITY) -> TranslateResult:
    """把模型的逐 block 译文组装成结果，并校验两个坑。

    `model_output`：{block_id: 译文}。**模型只译单个 block，不管结构。**
    """
    if target_lang not in LANGS:
        raise TranslateRejected("target_lang 必须是 %s 之一，得到 %r"
                                % ("/".join(LANGS), target_lang))
    if formality not in FORMALITY:
        raise TranslateRejected(
            "formality 必须是 %s 之一，得到 %r —— "
            "没有「中立」这个选项，不选就是选了一个"
            % ("/".join(FORMALITY), formality))
    ir.validate()
    gl = glossary or Glossary()
    gl.validate()

    result = TranslateResult(ir.doc_id, target_lang, formality)
    translatable = [b for b in ir.blocks if b.type != "figure" and b.text.strip()]

    for b in translatable:
        if b.id not in model_output:
            raise TranslateRejected(
                "block %r 没有对应译文 —— 拒绝整份结果。"
                "漏译一段而交付出去，比不交付更糟：客户不会逐段核对" % b.id)
        txt = model_output[b.id]
        if not txt.strip():
            raise TranslateRejected("block %r 的译文是空的" % b.id)

        terms = gl.found_in(b.text)
        lost = verify_terms_preserved(txt, terms)
        if lost:
            raise TranslateRejected(
                "block %r 的译文里丢了专有名词：%s —— "
                "人名地名被译掉，客户会立刻失去信任"
                % (b.id, ", ".join(repr(x) for x in lost)))

        result.blocks.append(TranslatedBlock(
            block_id=b.id, source_text=b.text, translated=txt,
            page=b.page, locator=b.locator(),
            terms_kept=[t.source for t in terms]))

    extra = set(model_output) - {b.id for b in translatable}
    if extra:
        raise TranslateRejected(
            "模型给了文档里没有的 block 的译文：%s" % ", ".join(sorted(extra)))

    if target_lang == "th":
        problem = check_thai_particles(result.as_text())
        if problem:
            raise TranslateRejected(problem)

    return result


# ---------------------------------------------------------------- 自检

def _ir() -> DocIR:
    from docir import SourceInfo
    return DocIR.from_blocks(
        "sha256:m", SourceInfo("menu.pdf", "application/pdf", 1),
        [Block("b1", "heading", 1, (10, 10, 300, 30), "บ้านริมปิง เมนูใหม่", ["th"]),
         Block("b2", "paragraph", 1, (10, 40, 400, 90),
               "ยินดีต้อนรับสู่บ้านริมปิง เรามีเมนูใหม่ประจำเดือนนี้", ["th"]),
         Block("f1", "figure", 1, (10, 100, 200, 200), "รูปอาหาร", ["th"])])


_GL = Glossary([Term("บ้านริมปิง", keep_as="Baan Rimping")])


def self_test() -> int:
    fails: list[str] = []

    good = {"b1": "Baan Rimping — new menu",
            "b2": "Welcome to Baan Rimping. We have a new menu this month."}
    r = translate(_ir(), "en", good, _GL)
    if len(r.blocks) != 2:
        fails.append("figure 应被跳过，得到 %d 块" % len(r.blocks))
    if r.blocks[0].locator != "p1@10,10":
        fails.append("locator 丢了：%r" % r.blocks[0].locator)
    if r.blocks[0].terms_kept != ["บ้านริมปิง"]:
        fails.append("terms_kept 没记录：%r" % r.blocks[0].terms_kept)

    # 专有名词被译掉 → 必须拒绝
    bad = dict(good, b1="Riverside House — new menu")
    try:
        translate(_ir(), "en", bad, _GL)
        fails.append("专有名词被译掉却通过了")
    except TranslateRejected:
        pass

    # 漏译 → 必须拒绝
    try:
        translate(_ir(), "en", {"b1": good["b1"]}, _GL)
        fails.append("漏译一段却通过了")
    except TranslateRejected:
        pass

    # 敬语粒子混用 → 必须拒绝
    try:
        translate(_ir(), "th", {"b1": "ยินดีครับ", "b2": "ขอบคุณค่ะ"}, Glossary())
        fails.append("ครับ/ค่ะ 混用却通过了")
    except TranslateRejected:
        pass

    # formality 必填且受限
    try:
        translate(_ir(), "en", good, _GL, formality="随便")
        fails.append("非法 formality 没被拒")
    except TranslateRejected:
        pass

    instr = build_instruction("en", "business", _GL.terms)
    if "บ้านริมปิง" not in instr or "Do NOT translate" not in instr:
        fails.append("指示里没写清哪些词不翻")

    if fails:
        print("✗ translate 自检失败", file=sys.stderr)
        for f in fails:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ translate 自检通过（专有名词保留 · 漏译拒绝 · 敬语一致 · 按 block 重组）")
    return 0


if __name__ == "__main__":
    sys.exit(self_test())
