#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris Documents — summarize 动作。

设计见 docs/business/starter-kit/documents.md §4「summarize — 摘要」。

## 这个动作真正的风险只有一个

不是「摘要写得不够好」—— 那个人一眼能看出来。
是**长文档分块摘要、合并时悄悄丢掉一条决议**。

30 页会议记录切成 8 块，每块各自摘要都对，合并成一页时少了
「王总同意把付款周期从 30 天改成 60 天」这一条。
输出看起来完整、通顺、专业，**没有任何东西会报错**，
而客户是照着这份纪要去执行的。

所以设计文档里写死了对策：

> 合并阶段把各块的 `decisions` 和 `action_items` **全量带上**，
> 只压缩 `key_points`。

这个模块把那句话变成**代码兜住的不变式**，而不是提示词里的一句叮嘱。

## 四条不可破的规则

1. **合并不丢决议。** 任何一块摘要里出现过的 `decision` / `action_item`，
   合并结果里必须还在。少一条就抛异常，不是打日志。
   —— 由 `merge()` 末尾的对账断言保证，模型说什么都不算数。

2. **每条决议和待办都要能回溯。** 必须带 `block_id`，且该 id 必须真的在
   DocIR 里存在。**指不回原文的决议没人敢照着执行。**

3. **待办的责任人和期限逐字保留。** 模型可以压缩 `key_points` 的措辞，
   但「谁承诺了什么、什么时候」不允许改写 —— 转述一次就变味一次。

4. **认不出文档类型就不套骨架。** 会议记录、合同、报告的要点结构完全不同；
   拿通用骨架去套会议记录，第一个丢的就是「谁承诺了什么」。
   认不出来就用通用骨架并**显式标记**，不假装认得。

## 分工:模型做什么、我们做什么

| | 谁做 |
|:---|:---|
| 判断文档类型 | 模型（我们校验它给的值在枚举里） |
| 提炼要点/决议/待办 | 模型 |
| **合并多块摘要** | **我们的代码** |
| **对账:决议有没有丢** | **我们的代码** |
| 校验出处 id 真实存在 | 我们的代码 |

合并这一步刻意不交给模型 —— 让模型合并，就等于让它自己判断
「哪条决议可以省略」，而这正是我们要防的那件事。

用法:
    part = summarize_chunk(ir, chunk_ids, model_output)
    final = merge([part1, part2, ...])

    python3 summarize.py --self-test
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any

from docir import Block, DocIR, SourceInfo


class SummarizeRejected(ValueError):
    """摘要结果不合格。**拒绝，让人看，而不是发出去。**"""


class MergeLostContentError(SummarizeRejected):
    """合并把决议或待办弄丢了。**这是这个模块存在的全部理由。**"""


# 文档类型 → 骨架。通用摘要对会议记录会漏掉「谁承诺了什么」。
DOC_TYPES = ("meeting_minutes", "contract", "report", "unknown")

SKELETONS: dict[str, tuple[str, ...]] = {
    "meeting_minutes": ("key_points", "decisions", "action_items", "open_questions"),
    "contract":        ("key_points", "obligations", "dates_and_amounts", "open_questions"),
    "report":          ("key_points", "findings", "recommendations", "open_questions"),
    # 认不出来时用最全的一套,并在结果里标出来 —— 不假装认得。
    "unknown":         ("key_points", "decisions", "action_items", "open_questions"),
}

# **合并时必须全量保留**的字段。只有 key_points 允许压缩。
#
# 这个集合是整个模块的支点。往里加字段是安全的方向(更多东西被保住);
# 往外拿字段要非常小心 —— 拿掉哪个,哪个就可以在合并时静默消失。
LOSSLESS_FIELDS = frozenset({
    "decisions", "action_items", "obligations", "dates_and_amounts",
    "findings", "recommendations", "open_questions",
})

COMPRESSIBLE_FIELDS = frozenset({"key_points"})


@dataclass(frozen=True)
class SummaryItem:
    """摘要里的一条。`text` 是内容，`block_id` 指回原文。"""
    text: str
    block_id: str
    owner: str = ""        # 仅 action_items:责任人
    due: str = ""          # 仅 action_items:期限（原文串，不解析）

    def key(self) -> tuple[str, str, str, str]:
        """对账用的身份。

        **用归一化后的文本，不用原始串** —— 否则合并时多一个空格
        就被当成「另一条」，对账永远通过，等于没对账。
        """
        return (_norm(self.text), self.block_id, _norm(self.owner), _norm(self.due))

    def as_dict(self) -> dict[str, Any]:
        d = {"text": self.text, "block_id": self.block_id}
        if self.owner:
            d["owner"] = self.owner
        if self.due:
            d["due"] = self.due
        return d


_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


@dataclass
class PartialSummary:
    """一块的摘要。"""
    doc_id: str
    doc_type: str
    chunk_index: int
    sections: dict[str, list[SummaryItem]] = field(default_factory=dict)
    type_certain: bool = True

    def items_of(self, name: str) -> list[SummaryItem]:
        return self.sections.get(name, [])


@dataclass
class Summary:
    doc_id: str
    doc_type: str
    sections: dict[str, list[SummaryItem]] = field(default_factory=dict)
    type_certain: bool = True
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "doc_type": self.doc_type,
            "type_certain": self.type_certain,
            "sections": {k: [i.as_dict() for i in v] for k, v in self.sections.items()},
            "notes": self.notes,
        }


# ---------------------------------------------------------------- 单块

def summarize_chunk(ir: DocIR, chunk_index: int,
                    model_output: dict[str, Any]) -> PartialSummary:
    """把模型对**一块**的输出变成经过校验的 PartialSummary。

    `model_output` 形如：
        {"doc_type": "meeting_minutes",
         "sections": {"decisions": [{"text": "...", "block_id": "b3"}], ...}}
    """
    ir.validate()
    known: dict[str, Block] = {b.id: b for b in ir.blocks}

    doc_type = model_output.get("doc_type", "")
    if doc_type not in DOC_TYPES:
        raise SummarizeRejected(
            "模型给的 doc_type=%r 不在 %s 里 —— **不猜**。"
            "拿通用骨架去套会议记录，第一个丢的就是「谁承诺了什么」"
            % (doc_type, list(DOC_TYPES)))

    skeleton = SKELETONS[doc_type]
    raw_sections = model_output.get("sections")
    if not isinstance(raw_sections, dict):
        raise SummarizeRejected("模型输出缺 sections 或类型不对：%r" % type(raw_sections))

    extra = sorted(set(raw_sections) - set(skeleton))
    if extra:
        # 多出的小节一律拒绝 —— 和 extract 同一个判据:
        # 模型开始自由发挥时,第一个信号就是多字段。
        raise SummarizeRejected(
            "模型输出了 %s 骨架里没有的小节 %s —— 拒绝整份。"
            "多字段是模型开始自由发挥的第一个信号" % (doc_type, extra))

    sections: dict[str, list[SummaryItem]] = {}
    for name in skeleton:
        items: list[SummaryItem] = []
        for raw in raw_sections.get(name, []):
            if not isinstance(raw, dict):
                raise SummarizeRejected("%s 里有非对象条目：%r" % (name, raw))
            text = str(raw.get("text", "")).strip()
            bid = str(raw.get("block_id", "")).strip()
            if not text:
                raise SummarizeRejected("%s 里有空条目" % name)
            if not bid:
                raise SummarizeRejected(
                    "%s 的条目没带 block_id：%r —— "
                    "指不回原文的决议没人敢照着执行" % (name, text[:40]))
            if bid not in known:
                raise SummarizeRejected(
                    "%s 的条目指向不存在的 block_id=%r —— "
                    "模型编了个出处。编出处比不给出处更危险，"
                    "因为它看起来是可核对的" % (name, bid))
            items.append(SummaryItem(
                text=text, block_id=bid,
                owner=str(raw.get("owner", "")).strip(),
                due=str(raw.get("due", "")).strip()))
        sections[name] = items

    return PartialSummary(doc_id=ir.doc_id, doc_type=doc_type,
                          chunk_index=chunk_index, sections=sections,
                          type_certain=doc_type != "unknown")


# ---------------------------------------------------------------- 合并

def merge(parts: list[PartialSummary],
          compressed_key_points: list[SummaryItem] | None = None) -> Summary:
    """把多块摘要合并成一份。

    **合并这一步刻意由我们的代码做，不交给模型。**
    让模型合并，就等于让它自己判断「哪条决议可以省略」——
    而那正是这个模块要防的事。

    `compressed_key_points`：只有 key_points 允许交给模型压缩。
    传 None 就把各块的 key_points 直接拼起来（去重）。

    末尾对账：任何一块里出现过的不可丢字段，合并结果里必须还在。
    少一条就抛 MergeLostContentError。
    """
    if not parts:
        raise SummarizeRejected("没有任何分块摘要可合并")

    doc_ids = {p.doc_id for p in parts}
    if len(doc_ids) != 1:
        raise SummarizeRejected(
            "这些分块摘要来自不同文档：%s —— 合并会把两份文档的决议混在一起"
            % sorted(doc_ids))

    # 文档类型:各块可能判得不一样。**取多数,并把分歧记下来**,
    # 不是默默取第一个。
    types = [p.doc_type for p in parts]
    doc_type = max(set(types), key=types.count)
    notes: list[str] = []
    if len(set(types)) > 1:
        notes.append(
            "各块对文档类型判断不一致：%s，取多数 %r。"
            "分歧本身值得人看一眼 —— 可能是一份混合文档"
            % ({t: types.count(t) for t in sorted(set(types))}, doc_type))

    skeleton = SKELETONS[doc_type]
    merged: dict[str, list[SummaryItem]] = {}

    for name in skeleton:
        seen: set[tuple[str, str, str, str]] = set()
        out: list[SummaryItem] = []
        for p in sorted(parts, key=lambda x: x.chunk_index):
            for item in p.items_of(name):
                k = item.key()
                if k in seen:
                    continue          # 重叠块产生的同一条,去重不算丢
                seen.add(k)
                out.append(item)
        merged[name] = out

    # key_points 是唯一允许压缩的。
    if compressed_key_points is not None:
        if "key_points" not in skeleton:
            raise SummarizeRejected(
                "%s 骨架里没有 key_points，但传了压缩结果" % doc_type)
        merged["key_points"] = list(compressed_key_points)

    result = Summary(doc_id=parts[0].doc_id, doc_type=doc_type,
                     sections=merged,
                     type_certain=all(p.type_certain for p in parts),
                     notes=notes)

    _assert_nothing_lost(parts, result)
    return result


def _assert_nothing_lost(parts: list[PartialSummary], result: Summary) -> None:
    """对账：不可丢字段里的每一条，合并结果里必须还在。

    **这是整个模块的支点。**

    不查这一下的话，丢一条决议的表现是:输出完整、通顺、专业,
    没有任何东西报错,而客户照着执行。
    """
    lost: list[str] = []
    for name in LOSSLESS_FIELDS:
        before: dict[tuple[str, str, str, str], SummaryItem] = {}
        for p in parts:
            for item in p.items_of(name):
                before[item.key()] = item
        after = {i.key() for i in result.sections.get(name, [])}
        for k, item in before.items():
            if k not in after:
                lost.append("%s：%r（出处 %s）" % (name, item.text[:60], item.block_id))

    if lost:
        raise MergeLostContentError(
            "合并把 %d 条内容弄丢了 —— 这些字段只准原样带上，不准压缩：\n  %s\n"
            "丢一条决议的表现是：输出完整、通顺、专业，没有任何东西报错，"
            "而客户是照着这份纪要去执行的。" % (len(lost), "\n  ".join(lost)))


def check_owners_verbatim(parts: list[PartialSummary], result: Summary) -> list[str]:
    """规则 3 的检查：待办的责任人和期限必须逐字保留。

    返回被改写过的条目说明；空列表 = 都没被动过。
    `merge()` 已经用 key() 兜住了这一条（owner/due 参与身份），
    这个函数是给人看的诊断，以及给 rewrite 之类后续动作复用。
    """
    problems: list[str] = []
    for name in ("action_items", "obligations"):
        before = {(_norm(i.text), i.block_id): i for p in parts for i in p.items_of(name)}
        for item in result.sections.get(name, []):
            src = before.get((_norm(item.text), item.block_id))
            if src is None:
                continue
            if _norm(src.owner) != _norm(item.owner):
                problems.append("%s 的责任人被改写：%r → %r"
                                % (item.text[:40], src.owner, item.owner))
            if _norm(src.due) != _norm(item.due):
                problems.append("%s 的期限被改写：%r → %r"
                                % (item.text[:40], src.due, item.due))
    return problems


# ---------------------------------------------------------------- 自检

def _ir() -> DocIR:
    return DocIR.from_blocks(
        doc_id="sha256:test",
        source=SourceInfo(filename="meeting.pdf", mime="application/pdf", pages=2),
        blocks=[
            Block(id="b1", type="paragraph", page=1, bbox=(0, 0, 100, 20),
                  text="ที่ประชุมเห็นชอบให้ปรับรอบชำระเงินจาก 30 วัน เป็น 60 วัน"),
            Block(id="b2", type="paragraph", page=1, bbox=(0, 30, 100, 50),
                  text="Nid will finish the English menu translation by Friday."),
            Block(id="b3", type="paragraph", page=2, bbox=(0, 0, 100, 20),
                  text="Boon to confirm dish names by Wednesday."),
        ])


def self_test() -> int:
    fails: list[str] = []
    ir = _ir()

    def out(**sections):
        return {"doc_type": "meeting_minutes", "sections": sections}

    p1 = summarize_chunk(ir, 0, out(
        key_points=[{"text": "讨论了付款周期", "block_id": "b1"}],
        decisions=[{"text": "付款周期 30 天改为 60 天", "block_id": "b1"}],
        action_items=[], open_questions=[]))
    p2 = summarize_chunk(ir, 1, out(
        key_points=[{"text": "菜单翻译分工", "block_id": "b2"}],
        decisions=[],
        action_items=[{"text": "完成英文菜单翻译", "block_id": "b2",
                       "owner": "Nid", "due": "Friday"}],
        open_questions=[]))

    m = merge([p1, p2])
    if len(m.sections["decisions"]) != 1:
        fails.append("决议数不对：%r" % m.sections["decisions"])
    if len(m.sections["action_items"]) != 1:
        fails.append("待办数不对：%r" % m.sections["action_items"])

    # 负对照:如果对账是死的,这里应当抛
    broken = Summary(doc_id=m.doc_id, doc_type=m.doc_type,
                     sections=dict(m.sections, decisions=[]))
    try:
        _assert_nothing_lost([p1, p2], broken)
        fails.append("对账没抓到被删掉的决议 —— 这个模块的支点是死的")
    except MergeLostContentError:
        pass

    # 编出处必须被拒
    try:
        summarize_chunk(ir, 0, out(key_points=[], decisions=[
            {"text": "x", "block_id": "b99"}], action_items=[], open_questions=[]))
        fails.append("指向不存在 block_id 的条目没被拒")
    except SummarizeRejected:
        pass

    if fails:
        print("✗ %d 项失败" % len(fails), file=sys.stderr)
        for f in fails:
            print("    " + f, file=sys.stderr)
        return 1
    print("✓ summarize 自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else (print(__doc__) or 0))
