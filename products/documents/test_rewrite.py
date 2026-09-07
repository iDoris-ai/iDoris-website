#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rewrite 的测试。

`documents.md` §4 的验收标准：

> 改写后的事实性内容不得增减（人工抽查 10 份，**不得出现原文没有的数字或承诺**）。

其中「数字」这一半是可以机械检查的，所以这里把它变成硬闸门而不是抽查。
「承诺」这一半只能靠关键词兜住最常见的几个 —— 穷尽做不到，
所以测试里也写清楚它的边界，免得有人以为这道闸门是完备的。

两头都要测：改写**本来就该和原文不一样**，
一个「和原文不同就拒绝」的实现也能让「不得编造」全绿，然后这个动作没用了。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docir import Block, DocIR, SourceInfo                   # noqa: E402
from rewrite import (                                        # noqa: E402
    COMMITMENT_MARKERS,
    FabricatedContentError,
    RewriteRejected,
    RewriteRequest,
    build_instruction,
    check_fabricated_numbers,
    check_length,
    check_new_commitments,
    numbers_in,
    rewrite,
)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def expect_raises(exc, fn, msg: str) -> None:
    try:
        fn()
    except exc:
        return
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("%s（抛的是 %s: %s）" % (msg, type(e).__name__, e))
        return
    FAILS.append(msg)


def ir(*texts: str) -> DocIR:
    return DocIR.from_blocks(
        doc_id="sha256:doc",
        source=SourceInfo(filename="spec.pdf", mime="application/pdf", pages=1),
        blocks=[Block(id="b%d" % (i + 1), type="paragraph", page=1,
                      bbox=(0, i * 10.0, 100, i * 10.0 + 8), text=t)
                for i, t in enumerate(texts)])


REQ = RewriteRequest(target_audience="酒店前台", tone="简洁口语")


# ══════════════════════════ 支点：不得编造数字

def test_fabricated_number_rejected() -> None:
    """原文没有的数字冒出来 —— 拒绝整份。

    这是这个动作最危险的地方：输出**本来就该和原文不一样**，
    所以多一个「3 年质保」读起来通顺、专业、符合语气要求，
    **没有任何东西会觉得不对劲** —— 然后它被发给客户。
    """
    d = ir("部署约 30 天完成，费用 45,000 泰铢。")
    expect_raises(FabricatedContentError,
                  lambda: rewrite(d, REQ, {"b1": "30 天部署，45,000 泰铢，含 3 年质保。"}),
                  "凭空冒出来的「3 年」没被拒")


def test_thai_digits_counted() -> None:
    """泰文数字一起数 —— 客户材料里两种写法都有。

    只认阿拉伯数字的话，用泰数字编造的金额会静默漏过，
    而金额正是最要命的那一类。
    """
    check(numbers_in("ราคา ๔๕,๐๐๐ บาท") == {"45000"},
          "泰文数字没被识别：%r" % numbers_in("ราคา ๔๕,๐๐๐ บาท"))
    d = ir("ค่าบริการ ๔๕,๐๐๐ บาท")
    expect_raises(FabricatedContentError,
                  lambda: rewrite(d, REQ, {"b1": "ค่าบริการ ๔๕,๐๐๐ บาท รับประกัน ๓ ปี"}),
                  "用泰数字编造的「๓ ปี」没被拒")


def test_same_numbers_in_different_format_pass() -> None:
    """正对照：同一个数字换个写法不算编造。

    「45,000」和「45000」是同一个数 —— 千分位是排版，不是事实。
    分不清的话，每次改写都会被拒，这个动作就没法用了。
    """
    d = ir("费用 45,000 泰铢。")
    try:
        r = rewrite(d, REQ, {"b1": "要 45000 泰铢。"})
        check(len(r.blocks) == 1, "结果块数不对")
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("千分位写法不同被判成编造数字（%s）" % e)


def test_dropped_number_is_noted_not_rejected() -> None:
    """数字变少：**不拒绝，但要说出来。**

    漏掉一个金额和编造一个金额，后果不同但都是问题。
    直接拒绝的话，正当的精简改写做不了；一声不吭的话，漏掉的金额没人知道。
    """
    d = ir("部署约 30 天完成，费用 45,000 泰铢。")
    r = rewrite(d, REQ, {"b1": "约 30 天完成部署。"})
    check(len(r.blocks) == 1, "正当的精简改写被拒了")
    check(any("45000" in n for n in r.notes),
          "丢掉的金额没被记进 notes：%r" % r.notes)


# ══════════════════════════ 支点：不得凭空承诺

def test_new_commitment_rejected() -> None:
    """改写是换一种说法，不是替客户做新的保证。"""
    d = ir("技术支持通过 LINE 提供。")
    for bad in ("有问题用 LINE 找我们，保证当天回复。",
                "Support via LINE. We guarantee same-day reply.",
                "ติดต่อผ่าน LINE เรารับประกันตอบกลับในวันเดียวกัน"):
        expect_raises(FabricatedContentError,
                      lambda b=bad: rewrite(d, REQ, {"b1": b}),
                      "凭空承诺没被拒：%r" % bad)


def test_commitment_markers_cover_three_languages() -> None:
    """承诺语清单必须**中英泰三套都有**。

    只查中文的话，英文和泰文的承诺会静默漏过 —— 而我们的客户材料
    三种语言都有，英文和泰文的对外文案恰恰是最常发出去的。
    """
    low = [m.lower() for m in COMMITMENT_MARKERS]
    check(any("保证" == m or "承诺" == m for m in low), "缺中文承诺语")
    check(any("guarantee" in m for m in low), "缺英文承诺语")
    check(any("รับประกัน" in m for m in low), "缺泰文承诺语")


def test_existing_commitment_may_be_rephrased() -> None:
    """正对照：原文**本来就有**承诺时，改写里保留它不算编造。

    否则任何一份带「保证」二字的原文都改写不了 ——
    而合同、服务说明里这类词本来就常见。
    """
    d = ir("我们保证在 30 天内完成部署。")
    try:
        rewrite(d, REQ, {"b1": "保证 30 天内部署好。"})
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("原文已有的承诺被判成编造（%s）—— 带「保证」的原文就改不了了" % e)


def test_commitment_check_is_case_insensitive() -> None:
    d = ir("Support is available on weekdays.")
    expect_raises(FabricatedContentError,
                  lambda: rewrite(d, REQ, {"b1": "Weekday support. We GUARANTEE a reply."}),
                  "大写的 GUARANTEE 绕过了检查 —— 改个大小写就能过的闸门等于没有")


def test_the_commitment_gate_is_not_claimed_to_be_complete() -> None:
    """关键词清单挡不住所有承诺 —— 这条测试把边界写下来。

    「我们会在当天回复您」不含任何标记词，但它同样是一个承诺。
    穷尽是做不到的，所以 rewrite 的输出**默认要过审批队列**。

    写下这条，是为了防止有人看到「有承诺检查」就以为这道闸门是完备的 ——
    那比没有闸门更危险。
    """
    # 原文刻意写长一点:这条要测的是**承诺闸门**,不能让长度闸门先把它挡下来。
    # (第一版就栽在这里 —— 断言根本没跑到,被长度检查接走了。)
    d = ir("技术支持通过 LINE 提供，工作日均有人值守，可咨询部署与使用问题。")
    sneaky = "有问题用 LINE 找我们，我们会在当天回复您。"
    check(check_new_commitments(d.blocks[0].text, sneaky) == set(),
          "这条测试的前提变了：该样例现在被关键词挡住了，说明清单扩了 —— "
          "更新这条测试，但别删掉它记录的那个边界")
    # 它能通过关键词闸门 —— 这是**已知边界**，不是 bug
    try:
        rewrite(d, REQ, {"b1": sneaky})
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("前提变了：%s" % e)


# ══════════════════════════ 受众与语气

def test_audience_and_tone_are_both_required() -> None:
    """**没有目标受众的「改写」是没有判据的。**

    给个默认值等于假装有判据 —— 那比报错更糟，因为它会一路走到客户手里。
    """
    for bad in (RewriteRequest(target_audience="", tone="简洁"),
                RewriteRequest(target_audience="  ", tone="简洁"),
                RewriteRequest(target_audience="前台", tone=""),
                RewriteRequest(target_audience="前台", tone="  ")):
        expect_raises(RewriteRejected, bad.validate,
                      "缺 audience/tone 的请求没被拒：%r" % bad)


def test_instruction_states_all_the_hard_limits() -> None:
    instr = build_instruction(REQ, source_len=100)
    check("酒店前台" in instr, "指示里没写受众")
    check("简洁口语" in instr, "指示里没写语气")
    check("120" in instr, "指示里没写长度上限")
    check("number" in instr.lower(), "指示里没禁止编造数字")
    check("guarantee" in instr.lower() or "promise" in instr.lower(),
          "指示里没禁止编造承诺")


# ══════════════════════════ 长度

def test_over_length_rejected() -> None:
    """模型倾向于把内容变长。超 120% 就拒。"""
    d = ir("短句。")
    long_text = "这是一段被模型扩写得远远超过原文长度的改写结果，充满了没有必要的修饰。"
    expect_raises(RewriteRejected, lambda: rewrite(d, REQ, {"b1": long_text}),
                  "超长改写没被拒")


def test_within_length_passes() -> None:
    """正对照：120% 以内必须放行。

    否则「一律拒绝」也能让上面全绿 —— 然后这个动作一次都跑不通。
    """
    d = ir("系统会在三十天内完成部署工作。")
    try:
        rewrite(d, REQ, {"b1": "三十天内部署完成。"})
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("长度合规的改写被拒了（%s）" % e)


def test_length_uses_normalized_text() -> None:
    """长度按归一化后算 —— 空白多少不该影响判定。

    **原文和改写两边都要测。** 第一版只在 `after` 里放了多余空白，
    于是「分母不归一化」的变异没被抓到 —— 而 PDF 提取出来的**原文**
    空白最不规整，分母错了整个比例就错了，超长的改写会被放行。
    """
    # 改写侧的空白不影响
    check(abs(check_length("abcd", "ab cd") - check_length("abcd", "ab   cd")) < 1e-9,
          "改写侧的空白数量影响了长度比")

    # **原文侧的空白也不该影响** —— 这一条是变异测试逼出来的
    tidy = check_length("ab cd", "abcd ef")
    messy = check_length("ab    cd", "abcd ef")
    check(abs(tidy - messy) < 1e-9,
          "原文侧的空白数量影响了长度比：%r vs %r —— "
          "PDF 提取出来的原文空白最不规整，分母错了整个比例就错，"
          "超长的改写会被放行" % (tidy, messy))

    # 端到端也验一次:原文带杂乱空白时,超长改写仍要被拒
    d = ir("短    句。")
    expect_raises(RewriteRejected,
                  lambda: rewrite(d, REQ,
                                  {"b1": "这是一段被模型扩写得远超原文长度的改写结果，"
                                         "充满了没有必要的修饰与铺陈。"}),
                  "原文带杂乱空白时，超长改写被放行了")


def test_ratio_must_be_above_one() -> None:
    expect_raises(RewriteRejected,
                  lambda: RewriteRequest(target_audience="a", tone="b",
                                         max_length_ratio=1.0).validate(),
                  "max_length_ratio=1.0 没被拒 —— 一个字都不许多等于禁止改写")


# ══════════════════════════ 完整性

def test_missing_block_rejects_whole_result() -> None:
    """少一块就拒绝整份 —— 和 translate 同一个判据。

    少一块而交付出去，客户会以为我们改写完了。
    """
    d = ir("第一段。", "第二段。")
    expect_raises(RewriteRejected, lambda: rewrite(d, REQ, {"b1": "一段。"}),
                  "缺块的改写没被拒")


def test_unknown_block_rejected() -> None:
    d = ir("第一段。")
    expect_raises(RewriteRejected,
                  lambda: rewrite(d, REQ, {"b1": "一段。", "b99": "凭空多出来的"}),
                  "文档里不存在的 block_id 没被拒")


def test_empty_rewrite_rejected() -> None:
    d = ir("第一段。")
    expect_raises(RewriteRejected, lambda: rewrite(d, REQ, {"b1": "   "}),
                  "空改写没被拒")


# ══════════════════════════ 单元

def test_check_helpers_unit() -> None:
    check(check_fabricated_numbers("有 30 天", "有 30 天和 5 年") == {"5"},
          "编造数字检测不对")
    check(check_fabricated_numbers("有 30 天", "有 30 天") == set(),
          "没编造却报了编造")
    check(check_new_commitments("普通说明", "我们保证") == {"保证"},
          "新增承诺检测不对")
    check(check_new_commitments("我们保证 X", "保证 Y") == set(),
          "原文已有的承诺被当成新增")


# ══════════════════════════ main

TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    for t in TESTS:
        t()
    if FAILS:
        print("✗ %d 个测试断言失败" % len(FAILS), file=sys.stderr)
        for f in FAILS:
            print("    " + f, file=sys.stderr)
        return 1
    print("✓ rewrite 测试全部通过（%d 个测试函数，含「不得编造」与「必须允许改」两头的对照）"
          % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
