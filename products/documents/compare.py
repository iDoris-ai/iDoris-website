#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris Documents — compare 动作（新旧文档对比）。

设计见 docs/business/starter-kit/documents.md §4「compare — 文档对比」。

## 这是六个动作里唯一「漏一条就可能造成损失」的

典型用法是**新旧合同版本对比**。漏掉一条条款变更，客户签下去，
损失是真金白银 —— 而且事后没人能说清是哪一步漏的。

所以这个模块的形状和别的动作不同：它的核心不是「让模型比得更准」，
而是**用我们的代码保证没有任何一条被静默丢掉**。

## 覆盖不变式:这个模块的支点

> **两份文档里的每一个块，都必须在输出里被交代掉，且只被交代一次。**

不是「模型说它比完了」，是我们数一遍。旧文档 N 个块、新文档 M 个块，
输出里的 `unchanged` / `modified` / `moved` / `removed` / `added`
加起来必须正好盖住这 N + M 个块。

差一个就抛异常。**这是唯一能让「漏一条」变成不可能的办法** ——
靠提示词叮嘱、靠人工抽查、靠模型自己声明「已完整比对」，都做不到。

## 顺序调换必须是 moved，不能是 removed + added

设计文档特别点了这一条：直接把两份全文丢给模型比对，会漏掉顺序调换的条款。

而更糟的是**它不会表现为「漏掉」**，会表现为「第 7 条被删除、第 12 条新增」——
看起来是两处变更，实际是零处变更。客户读到「删除」两个字的反应，
和读到「位置调整」完全不同：前者会去追问为什么把这条拿掉了。

所以 `moved` 是独立的一类，由**内容相同、位置不同**机械判定，不问模型。

## 数字变化一律标高风险

「30 天」改成「60 天」、「45,000」改成「54,000」——
这类改动字面上只差一两个字符，在一屏差异清单里最容易被眼睛滑过去,
而它恰恰是**最可能造成损失**的那一类。

所以:凡是 before/after 的数字集合不同，`risk` 强制为 `high`，模型说什么都不算数。

## 分工

| | 谁做 |
|:---|:---|
| 判断两段文字是不是「同一条的两个版本」 | 模型 |
| 描述改了什么、有什么风险 | 模型 |
| **覆盖对账:有没有漏** | **我们的代码** |
| **顺序调换判定** | **我们的代码** |
| **数字变化判定与风险升级** | **我们的代码** |
| 双向出处校验 | 我们的代码 |

用法:
    result = compare(old_ir, new_ir, model_pairs)

    python3 compare.py --self-test
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any

from docir import Block, DocIR, SourceInfo


class CompareRejected(ValueError):
    """对比结果不合格。**拒绝，让人看，而不是发出去。**"""


class CoverageError(CompareRejected):
    """有块没被交代。**这是这个模块存在的全部理由。**"""


RISK_LEVELS = ("low", "medium", "high")

# 差异分类。顺序有意义:moved 排在 removed/added 前面 ——
# 一条内容既没变又换了位置,它是 moved,不是「删了又加」。
KINDS = ("unchanged", "modified", "moved", "removed", "added")

_WS = re.compile(r"\s+")
# 数字:含千分位与小数。泰文数字另算(见 _THAI_DIGITS)。
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


def numbers_in(text: str) -> list[str]:
    """文本里的数字，归一化后返回（去千分位、泰数字转阿拉伯）。

    **泰文数字必须一起数** —— 客户的合同里两种写法都有，
    只认阿拉伯数字的话，泰数字的金额改动会静默漏过。
    """
    t = text.translate(_THAI_DIGITS)
    return sorted(n.replace(",", "") for n in _NUM.findall(t))


@dataclass(frozen=True)
class BlockRef:
    doc_id: str
    block_id: str
    page: int

    def as_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "block_id": self.block_id, "page": self.page}


@dataclass
class Diff:
    kind: str
    before: BlockRef | None = None      # 旧文档的出处
    after: BlockRef | None = None       # 新文档的出处
    before_text: str = ""
    after_text: str = ""
    note: str = ""                      # 模型写的说明
    risk: str = "low"
    risk_forced: str = ""               # 我们强制升级过就记在这里

    def validate(self) -> None:
        if self.kind not in KINDS:
            raise CompareRejected("未知差异类型 %r（可用：%s）" % (self.kind, list(KINDS)))
        if self.risk not in RISK_LEVELS:
            raise CompareRejected("未知风险等级 %r" % self.risk)
        # 双向出处:改动类必须两头都指得回去
        if self.kind in ("unchanged", "modified", "moved"):
            if self.before is None or self.after is None:
                raise CompareRejected(
                    "%s 必须带**双向**出处 —— 只指一头的差异，"
                    "客户没法核对到底改了什么" % self.kind)
        elif self.kind == "removed":
            if self.before is None or self.after is not None:
                raise CompareRejected("removed 只应有旧文档出处")
        elif self.kind == "added":
            if self.after is None or self.before is not None:
                raise CompareRejected("added 只应有新文档出处")

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "before": self.before.as_dict() if self.before else None,
            "after": self.after.as_dict() if self.after else None,
            "before_text": self.before_text,
            "after_text": self.after_text,
            "note": self.note,
            "risk": self.risk,
            "risk_forced": self.risk_forced,
        }


@dataclass
class CompareResult:
    old_doc_id: str
    new_doc_id: str
    diffs: list[Diff] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[Diff]:
        return [d for d in self.diffs if d.kind == kind]

    def high_risk(self) -> list[Diff]:
        return [d for d in self.diffs if d.risk == "high"]

    def as_dict(self) -> dict[str, Any]:
        return {"old_doc_id": self.old_doc_id, "new_doc_id": self.new_doc_id,
                "diffs": [d.as_dict() for d in self.diffs], "notes": self.notes}


# ---------------------------------------------------------------- 主流程

def compare(old: DocIR, new: DocIR,
            model_pairs: list[dict[str, Any]]) -> CompareResult:
    """把模型给的配对变成经过校验的差异清单。

    `model_pairs` 每条形如：
        {"old_block_id": "o3", "new_block_id": "n5",
         "note": "付款周期由 30 天改为 60 天", "risk": "medium"}

    只配对的一头留空表示删除/新增：
        {"old_block_id": "o7", "new_block_id": None, "note": "整条删除"}

    **模型只负责配对和描述。** 分类（unchanged/modified/moved）、
    数字风险升级、覆盖对账全部在这里做。
    """
    old.validate()
    new.validate()
    if old.doc_id == new.doc_id:
        raise CompareRejected(
            "两边是同一份文档（doc_id=%r）—— 对比自己没有意义，"
            "多半是传错了文件" % old.doc_id)

    ob: dict[str, Block] = {b.id: b for b in old.blocks}
    nb: dict[str, Block] = {b.id: b for b in new.blocks}
    o_order = {b.id: i for i, b in enumerate(old.blocks)}
    n_order = {b.id: i for i, b in enumerate(new.blocks)}

    result = CompareResult(old_doc_id=old.doc_id, new_doc_id=new.doc_id)
    used_old: set[str] = set()
    used_new: set[str] = set()

    for pair in model_pairs:
        oid = pair.get("old_block_id") or None
        nid = pair.get("new_block_id") or None
        note = str(pair.get("note", "")).strip()
        risk = str(pair.get("risk", "low")).strip() or "low"

        if oid is None and nid is None:
            raise CompareRejected("配对两头都是空：%r" % pair)

        for bid, table, label in ((oid, ob, "旧"), (nid, nb, "新")):
            if bid is not None and bid not in table:
                raise CompareRejected(
                    "配对指向%s文档里不存在的 block_id=%r —— 模型编了个出处。"
                    "**编出处比不给出处更危险**，因为它看起来是可核对的"
                    % (label, bid))
        for bid, used, label in ((oid, used_old, "旧"), (nid, used_new, "新")):
            if bid is not None:
                if bid in used:
                    raise CompareRejected(
                        "%s文档的块 %r 被配对了两次 —— 同一条不能既算这样又算那样，"
                        "否则覆盖对账会被凑数蒙混过去" % (label, bid))
                used.add(bid)

        d = _build_diff(oid, nid, ob, nb, o_order, n_order,
                        old.doc_id, new.doc_id, note, risk)
        d.validate()
        result.diffs.append(d)

    # 没被模型提到的块 —— **不是「就当没变」,是删除/新增。**
    # 模型漏配的表现就是这里冒出来一堆,而不是无声无息。
    for bid in old.blocks:
        if bid.id not in used_old:
            result.diffs.append(_build_diff(bid.id, None, ob, nb, o_order, n_order,
                                            old.doc_id, new.doc_id,
                                            "模型未提及，按删除处理", "medium"))
            result.notes.append(
                "旧文档的块 %s 模型没有提及，已按「删除」计入并标 medium —— "
                "漏配对和真删除在这里是一样的处理，宁可多报" % bid.id)
    for bid in new.blocks:
        if bid.id not in used_new:
            result.diffs.append(_build_diff(None, bid.id, ob, nb, o_order, n_order,
                                            old.doc_id, new.doc_id,
                                            "模型未提及，按新增处理", "medium"))
            result.notes.append(
                "新文档的块 %s 模型没有提及，已按「新增」计入并标 medium" % bid.id)

    _assert_full_coverage(old, new, result)
    return result


def _build_diff(oid: str | None, nid: str | None,
                ob: dict[str, Block], nb: dict[str, Block],
                o_order: dict[str, int], n_order: dict[str, int],
                old_doc_id: str, new_doc_id: str,
                note: str, risk: str) -> Diff:
    before = (BlockRef(old_doc_id, oid, ob[oid].page) if oid else None)
    after = (BlockRef(new_doc_id, nid, nb[nid].page) if nid else None)
    btext = ob[oid].text if oid else ""
    ntext = nb[nid].text if nid else ""

    if oid is None:
        kind = "added"
    elif nid is None:
        kind = "removed"
    else:
        same_text = _norm(btext) == _norm(ntext)
        if not same_text:
            kind = "modified"
        else:
            # 内容一样 —— 位置变了就是 moved,不是 unchanged。
            #
            # **这一条由我们判,不问模型。** 模型很容易把顺序调换报成
            # 「第 7 条删除 + 第 12 条新增」:看起来是两处变更、实际是零处。
            # 客户读到「删除」会去追问为什么把这条拿掉了。
            kind = "moved" if _position_changed(oid, nid, o_order, n_order) else "unchanged"

    d = Diff(kind=kind, before=before, after=after,
             before_text=btext, after_text=ntext, note=note, risk=risk)

    # 数字变了就强制 high。**模型说什么都不算数。**
    if kind == "modified":
        bn, nn = numbers_in(btext), numbers_in(ntext)
        if bn != nn:
            if d.risk != "high":
                d.risk_forced = (
                    "数字有变化（%s → %s），风险由 %s 强制升为 high。"
                    "这类改动字面上只差一两个字符，在一屏差异清单里最容易被眼睛滑过去，"
                    "而它恰恰是最可能造成损失的那一类"
                    % (bn or "无", nn or "无", d.risk))
            d.risk = "high"
    return d


def _position_changed(oid: str, nid: str,
                      o_order: dict[str, int], n_order: dict[str, int]) -> bool:
    """位置有没有变。

    用**序号**比，不用 block_id 比 —— id 是解析器给的，两份文档之间没有可比性。
    """
    return o_order[oid] != n_order[nid]


def _assert_full_coverage(old: DocIR, new: DocIR, result: CompareResult) -> None:
    """覆盖对账：两份文档的每个块都被交代掉，且只交代一次。

    **这是这个模块的支点。**

    不查这一下的话，漏一条条款变更的表现是：差异清单看起来干净、专业、
    条理清楚 —— 少的那条不会以任何形式出现。客户签下去，损失是真金白银，
    而且事后没人能说清是哪一步漏的。
    """
    covered_old: dict[str, int] = {}
    covered_new: dict[str, int] = {}
    for d in result.diffs:
        if d.before is not None:
            covered_old[d.before.block_id] = covered_old.get(d.before.block_id, 0) + 1
        if d.after is not None:
            covered_new[d.after.block_id] = covered_new.get(d.after.block_id, 0) + 1

    problems: list[str] = []
    for doc, covered, label in ((old, covered_old, "旧"), (new, covered_new, "新")):
        for b in doc.blocks:
            n = covered.get(b.id, 0)
            if n == 0:
                problems.append("%s文档的块 %s（第 %d 页）没有出现在任何一条差异里：%r"
                                % (label, b.id, b.page, b.text[:40]))
            elif n > 1:
                problems.append("%s文档的块 %s 被交代了 %d 次 —— 重复计入会掩盖漏项"
                                % (label, b.id, n))
        stray = sorted(set(covered) - {b.id for b in doc.blocks})
        if stray:
            problems.append("%s文档的差异里出现了不属于它的块：%s" % (label, stray))

    if problems:
        raise CoverageError(
            "覆盖对账没过，%d 处：\n  %s\n"
            "漏一条条款变更的表现是：差异清单看起来干净、专业、条理清楚 —— "
            "少的那条不会以任何形式出现。这是六个动作里唯一「漏一条就可能造成损失」的。"
            % (len(problems), "\n  ".join(problems)))


# ---------------------------------------------------------------- 自检

def _doc(doc_id: str, texts: list[str], prefix: str) -> DocIR:
    return DocIR.from_blocks(
        doc_id=doc_id,
        source=SourceInfo(filename=doc_id + ".pdf", mime="application/pdf", pages=1),
        blocks=[Block(id="%s%d" % (prefix, i + 1), type="paragraph", page=1,
                      bbox=(0, i * 10.0, 100, i * 10.0 + 8), text=t)
                for i, t in enumerate(texts)])


def self_test() -> int:
    fails: list[str] = []

    old = _doc("sha256:old", ["甲方应于 30 天内付款", "乙方负责运输", "保密条款"], "o")
    new = _doc("sha256:new", ["甲方应于 60 天内付款", "保密条款", "乙方负责运输"], "n")

    r = compare(old, new, [
        {"old_block_id": "o1", "new_block_id": "n1", "note": "付款周期变更", "risk": "low"},
        {"old_block_id": "o2", "new_block_id": "n3", "note": "位置调整"},
        {"old_block_id": "o3", "new_block_id": "n2", "note": "位置调整"},
    ])

    mod = r.of_kind("modified")
    if len(mod) != 1:
        fails.append("modified 数不对：%r" % [d.note for d in mod])
    elif mod[0].risk != "high":
        fails.append("数字变化没被强制升为 high：%r" % mod[0].risk)

    if len(r.of_kind("moved")) != 2:
        fails.append("顺序调换没被识别为 moved：%r"
                     % [(d.kind, d.before.block_id) for d in r.diffs])
    if r.of_kind("removed") or r.of_kind("added"):
        fails.append("顺序调换被报成了删除+新增 —— 看起来是变更，实际是零处变更")

    # 负对照:覆盖对账要真的会炸
    broken = CompareResult(old.doc_id, new.doc_id, diffs=r.diffs[:1])
    try:
        _assert_full_coverage(old, new, broken)
        fails.append("覆盖对账没抓到漏掉的块 —— 这个模块的支点是死的")
    except CoverageError:
        pass

    if fails:
        print("✗ %d 项失败" % len(fails), file=sys.stderr)
        for f in fails:
            print("    " + f, file=sys.stderr)
        return 1
    print("✓ compare 自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else (print(__doc__) or 0))
