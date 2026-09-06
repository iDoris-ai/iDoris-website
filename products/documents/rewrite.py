#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris Documents — rewrite 动作（按受众与语气改写）。

设计见 docs/business/starter-kit/documents.md §4「rewrite — 改写」。

## 这个动作最危险的地方是它看起来最无害

`extract` 错了，字段对不上原文，人一核 citation 就发现。
`compare` 漏了，覆盖对账会炸。
而 `rewrite` 的输出**本来就该和原文不一样** —— 这正是它的用途。

所以模型多写一句「我们承诺 48 小时内响应」，或者把「约 30 天」写成
「30 个工作日」，**没有任何东西会觉得不对劲**。它读起来通顺、专业、
符合要求的语气。然后这段话被发给客户，成了一个我们没打算做出的承诺。

## 三条不可破的规则

1. **改写后不得出现原文没有的数字。** 由代码逐个核，不是叮嘱模型。
   数字是最容易被「顺手改得更好看」的东西：「约 30 天」→「30 个工作日」，
   读起来更专业，但那是两回事。

2. **不得凭空长出承诺语。** 「保证」「承诺」「一定」「全额退款」这类词，
   原文没有就不许有。改写是换一种说法，不是替客户做新的保证。

3. **`target_audience` 与 `tone` 缺一不做。**
   设计文档的原话：**没有目标受众的「改写」是没有判据的。**
   给个默认值等于假装有判据 —— 那比报错更糟，因为它会一路走到客户手里。

## 长度约束

模型倾向于把内容变长。设计里定的是超出 120% 就重跑一次 ——
`check_length()` 给出判据，**重跑是调用方的事**，这里不自动重试：
一个会自己偷偷重试的函数，会把「模型不稳定」这件事藏起来。

## 分工

| | 谁做 |
|:---|:---|
| 改写文字 | 模型 |
| **核对数字有没有凭空冒出来** | **我们的代码** |
| **核对有没有新的承诺语** | **我们的代码** |
| **长度判据** | **我们的代码** |
| 受众/语气是否给全 | 我们的代码 |

用法:
    req = RewriteRequest(target_audience="酒店前台", tone="简洁口语")
    result = rewrite(ir, req, {"b1": "改写后的文字", ...})

    python3 rewrite.py --self-test
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any

from docir import Block, DocIR, SourceInfo


class RewriteRejected(ValueError):
    """改写结果不合格。**拒绝，让人看，而不是发出去。**"""


class FabricatedContentError(RewriteRejected):
    """改写里出现了原文没有的数字或承诺。**这个模块存在的全部理由。**"""


# 长度上限倍数。设计文档 §4 定的。
MAX_LENGTH_RATIO = 1.2

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_WS = re.compile(r"\s+")

# 承诺语。**中英泰三套** —— 客户材料三种语言都有，
# 只查中文的话，英文和泰文的承诺会静默漏过。
#
# 这个清单不追求穷尽 —— 穷尽是做不到的。它挡的是最常见、
# 后果最重的那几个词。剩下的靠人审，所以 rewrite 的输出默认要过审批队列。
COMMITMENT_MARKERS: tuple[str, ...] = (
    # 中文
    "保证", "承诺", "必定", "一定会", "全额退款", "无条件", "包退", "包换",
    # 英文（小写比对）
    "guarantee", "guaranteed", "we promise", "commit to", "full refund",
    "no questions asked", "unconditional",
    # 泰文
    "รับประกัน", "รับรอง", "คืนเงินเต็มจำนวน",
)


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


def numbers_in(text: str) -> set[str]:
    """文本里的数字，归一化（去千分位、泰数字转阿拉伯）。

    **泰文数字必须一起数** —— 客户材料里两种写法都有。
    """
    return {n.replace(",", "") for n in _NUM.findall(text.translate(_THAI_DIGITS))}


def commitments_in(text: str) -> set[str]:
    low = text.lower()
    return {m for m in COMMITMENT_MARKERS if m.lower() in low}


@dataclass
class RewriteRequest:
    """改写请求。**两个字段都必填，没有默认值。**"""
    target_audience: str
    tone: str
    max_length_ratio: float = MAX_LENGTH_RATIO

    def validate(self) -> None:
        if not self.target_audience.strip():
            raise RewriteRejected(
                "target_audience 必填 —— **没有目标受众的「改写」是没有判据的**。"
                "给个默认值等于假装有判据，那比报错更糟：它会一路走到客户手里")
        if not self.tone.strip():
            raise RewriteRejected(
                "tone 必填 —— 没有语气要求就无法判断改写得对不对")
        if self.max_length_ratio <= 1.0:
            raise RewriteRejected(
                "max_length_ratio 必须 > 1.0，得到 %r —— "
                "改写后一个字都不许多，等于禁止改写" % self.max_length_ratio)


@dataclass
class RewrittenBlock:
    block_id: str
    before: str
    after: str
    length_ratio: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"block_id": self.block_id, "before": self.before,
                "after": self.after, "length_ratio": round(self.length_ratio, 3)}


@dataclass
class RewriteResult:
    doc_id: str
    target_audience: str
    tone: str
    blocks: list[RewrittenBlock] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "target_audience": self.target_audience,
                "tone": self.tone, "blocks": [b.as_dict() for b in self.blocks],
                "notes": self.notes}


def build_instruction(req: RewriteRequest, source_len: int) -> str:
    """给模型的指示。**把受众、语气、长度、禁止项全写死。**"""
    req.validate()
    return "\n".join([
        "Rewrite the text for this audience: %s" % req.target_audience,
        "Tone: %s" % req.tone,
        "Hard limit: at most %d characters (%.0f%% of the source). "
        "Going over is a rejection, not a warning."
        % (int(source_len * req.max_length_ratio), req.max_length_ratio * 100),
        "Do NOT introduce any number that is not in the source text.",
        "Do NOT introduce any guarantee, promise, or refund commitment "
        "that is not in the source text.",
        "Keep every proper noun exactly as written.",
    ])


def check_fabricated_numbers(before: str, after: str) -> set[str]:
    """改写里冒出来的、原文没有的数字。"""
    return numbers_in(after) - numbers_in(before)


def check_new_commitments(before: str, after: str) -> set[str]:
    """改写里冒出来的、原文没有的承诺语。"""
    return commitments_in(after) - commitments_in(before)


def check_length(before: str, after: str, ratio: float = MAX_LENGTH_RATIO) -> float:
    """返回长度比。判据给出来，**重跑是调用方的事**。

    一个会自己偷偷重试的函数，会把「模型不稳定」这件事藏起来。
    """
    b = len(_norm(before))
    return len(_norm(after)) / b if b else 0.0


def rewrite(ir: DocIR, req: RewriteRequest,
            model_output: dict[str, str]) -> RewriteResult:
    """把模型的改写结果逐块校验。

    `model_output`：{block_id: 改写后的文字}

    **少一个块就拒绝整份** —— 和 translate 同一个判据：
    少一块而交付出去，客户会以为我们改写完了。
    """
    ir.validate()
    req.validate()
    blocks = {b.id: b for b in ir.blocks}

    unknown = sorted(set(model_output) - set(blocks))
    if unknown:
        raise RewriteRejected(
            "模型输出了文档里不存在的 block_id：%s —— 拒绝整份" % unknown)
    missing = sorted(set(blocks) - set(model_output))
    if missing:
        raise RewriteRejected(
            "缺 %d 个块的改写：%s —— 拒绝整份。"
            "少一块而交付出去，客户会以为我们改写完了" % (len(missing), missing))

    result = RewriteResult(doc_id=ir.doc_id,
                           target_audience=req.target_audience, tone=req.tone)

    for b in ir.blocks:
        after = model_output[b.id]
        if not after.strip():
            raise RewriteRejected("块 %s 的改写是空的" % b.id)

        fake_nums = check_fabricated_numbers(b.text, after)
        if fake_nums:
            raise FabricatedContentError(
                "块 %s 的改写里出现了原文没有的数字：%s\n"
                "原文：%r\n改写：%r\n"
                "数字是最容易被「顺手改得更好看」的东西 ——「约 30 天」写成"
                "「30 个工作日」读起来更专业，但那是两回事。"
                % (b.id, sorted(fake_nums), b.text[:60], after[:60]))

        new_promises = check_new_commitments(b.text, after)
        if new_promises:
            raise FabricatedContentError(
                "块 %s 的改写里出现了原文没有的承诺语：%s\n改写：%r\n"
                "改写是换一种说法，不是替客户做新的保证。"
                "这句话会被发给客户，成为一个我们没打算做出的承诺。"
                % (b.id, sorted(new_promises), after[:80]))

        ratio = check_length(b.text, after, req.max_length_ratio)
        if ratio > req.max_length_ratio:
            raise RewriteRejected(
                "块 %s 的改写是原文的 %.0f%%，超过上限 %.0f%% —— 拒绝。"
                "模型倾向于把内容变长；重跑一次是调用方的事，"
                "这里不自动重试（会把「模型不稳定」藏起来）"
                % (b.id, ratio * 100, req.max_length_ratio * 100))

        # 数字变少也值得看一眼 —— 不拒绝,但要说出来。
        # 漏掉一个金额和编造一个金额,后果不同但都是问题。
        lost = numbers_in(b.text) - numbers_in(after)
        if lost:
            result.notes.append(
                "块 %s 的改写丢掉了原文里的数字 %s —— 不拒绝，但值得看一眼："
                "漏掉一个金额和编造一个金额，后果不同但都是问题"
                % (b.id, sorted(lost)))

        result.blocks.append(RewrittenBlock(block_id=b.id, before=b.text,
                                            after=after, length_ratio=ratio))
    return result


# ---------------------------------------------------------------- 自检

def _ir() -> DocIR:
    return DocIR.from_blocks(
        doc_id="sha256:doc",
        source=SourceInfo(filename="spec.pdf", mime="application/pdf", pages=1),
        blocks=[
            Block(id="b1", type="paragraph", page=1, bbox=(0, 0, 100, 10),
                  text="系统在收到请求后约 30 天内完成部署，费用 45,000 泰铢。"),
            Block(id="b2", type="paragraph", page=1, bbox=(0, 20, 100, 30),
                  text="技术支持通过 LINE 提供。"),
        ])


def self_test() -> int:
    fails: list[str] = []
    ir = _ir()
    req = RewriteRequest(target_audience="酒店前台", tone="简洁口语")

    ok = rewrite(ir, req, {
        "b1": "部署约 30 天完成，费用 45,000 泰铢。",
        "b2": "有问题用 LINE 找我们。",
    })
    if len(ok.blocks) != 2:
        fails.append("块数不对：%d" % len(ok.blocks))

    # 编造数字必须被拒
    try:
        rewrite(ir, req, {"b1": "部署 30 天完成，费用 45,000 泰铢，含 3 年质保。",
                          "b2": "有问题用 LINE 找我们。"})
        fails.append("凭空冒出来的数字没被拒")
    except FabricatedContentError:
        pass

    # 凭空承诺必须被拒
    try:
        rewrite(ir, req, {"b1": "部署约 30 天完成，费用 45,000 泰铢。",
                          "b2": "有问题用 LINE 找我们，保证当天回复。"})
        fails.append("凭空冒出来的承诺没被拒")
    except FabricatedContentError:
        pass

    # 受众/语气缺一不做
    for bad in (RewriteRequest(target_audience="", tone="简洁"),
                RewriteRequest(target_audience="前台", tone="  ")):
        try:
            bad.validate()
            fails.append("缺字段的请求没被拒：%r" % bad)
        except RewriteRejected:
            pass

    if fails:
        print("✗ %d 项失败" % len(fails), file=sys.stderr)
        for f in fails:
            print("    " + f, file=sys.stderr)
        return 1
    print("✓ rewrite 自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else (print(__doc__) or 0))
