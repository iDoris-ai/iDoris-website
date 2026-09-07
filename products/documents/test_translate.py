#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""translate.py 的测试。

最要紧的三条：**专有名词不被译掉**、**漏译必须拒绝**、**敬语不混用**。

每条断言配负对照。跑法：python3 test_translate.py
"""

import sys

from docir import Block, DocIR, SourceInfo
from translate import (
    DEFAULT_FORMALITY,
    Glossary,
    Term,
    TranslateRejected,
    build_instruction,
    check_thai_particles,
    translate,
    verify_terms_preserved,
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


def ir() -> DocIR:
    return DocIR.from_blocks(
        "sha256:m", SourceInfo("menu.pdf", "application/pdf", 1),
        [Block("b1", "heading", 1, (10, 10, 300, 30), "บ้านริมปิง เมนูใหม่", ["th"]),
         Block("b2", "paragraph", 1, (10, 40, 400, 90),
               "ยินดีต้อนรับสู่บ้านริมปิง เรามีเมนูใหม่", ["th"]),
         Block("f1", "figure", 1, (10, 100, 200, 200), "รูปอาหาร", ["th"])])


GL = Glossary([Term("บ้านริมปิง", keep_as="Baan Rimping")])
GOOD = {"b1": "Baan Rimping — new menu",
        "b2": "Welcome to Baan Rimping. We have a new menu."}


# ══════════════════════════════════════ 专有名词不被译掉

def test_proper_nouns_preserved() -> None:
    """人名地名被译掉，客户会立刻失去信任 —— 那是他们酒店的名字。"""
    expect_raises(TranslateRejected,
                  lambda: translate(ir(), "en", dict(GOOD, b1="Riverside House — new menu"), GL),
                  "专有名词被译掉却通过了")

    # 负对照:保留了的必须通过 —— 否则「什么都拒绝」也能让上面绿
    try:
        r = translate(ir(), "en", GOOD, GL)
        check(r.blocks[0].terms_kept == ["บ้านริมปิง"],
              "terms_kept 没记录：%r" % r.blocks[0].terms_kept)
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：保留了专有名词的译文被拒（%s）" % e)

    # 负对照:术语表为空时不该因此拒绝
    try:
        translate(ir(), "en", {"b1": "anything", "b2": "anything else"}, Glossary())
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：空术语表时被拒（%s）" % e)


def test_verify_terms_preserved_unit() -> None:
    ts = [Term("บ้านริมปิง", keep_as="Baan Rimping"), Term("เชียงใหม่")]
    check(verify_terms_preserved("Baan Rimping in เชียงใหม่", ts) == [],
          "两个都在却报丢失")
    check(verify_terms_preserved("Riverside House in Chiang Mai", ts) ==
          ["บ้านริมปิง", "เชียงใหม่"], "丢失的没被全部报出")
    check(verify_terms_preserved("Baan Rimping in Chiang Mai", ts) == ["เชียงใหม่"],
          "只丢一个时报错")


# ══════════════════════════════════════ 漏译必须拒绝

def test_missing_block_rejected() -> None:
    """漏译一段而交付出去，比不交付更糟：客户不会逐段核对。"""
    expect_raises(TranslateRejected,
                  lambda: translate(ir(), "en", {"b1": GOOD["b1"]}, GL),
                  "漏译一段却通过了")
    # 空译文必须被**空译文这道检查**拦下。
    # 用 b1 会被「专有名词丢失」顺手拦掉 —— 那样即使空译文检查被删掉，
    # 测试照样通过，这条断言就分辨不出任何东西。变异测试抓到了这一点。
    # 所以用一个**不含专有名词**的文档来测。
    plain = DocIR.from_blocks(
        "sha256:p", SourceInfo("p.pdf", "application/pdf", 1),
        [Block("p1", "paragraph", 1, (10, 10, 400, 40), "เมนูใหม่ประจำเดือน", ["th"])])
    expect_raises(TranslateRejected,
                  lambda: translate(plain, "en", {"p1": "   "}, Glossary()),
                  "空译文没被拒（且该文档不含专有名词，只有空译文检查能拦它）")

    # 负对照:同一文档给出非空译文必须通过
    try:
        translate(plain, "en", {"p1": "New menu of the month"}, Glossary())
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：非空译文被拒（%s）" % e)
    expect_raises(TranslateRejected,
                  lambda: translate(ir(), "en", dict(GOOD, zz="多出来的"), GL),
                  "文档里没有的 block 的译文没被拒")

    # 负对照:figure 不该被要求翻译
    try:
        translate(ir(), "en", GOOD, GL)      # GOOD 里没有 f1
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：figure 被要求翻译（%s）" % e)


def test_structure_rebuilt_by_us() -> None:
    """结构由我们按 block 拼回去，不由模型拼 —— 整篇翻译会丢表格与版式。"""
    r = translate(ir(), "en", GOOD, GL)
    check(len(r.blocks) == 2, "figure 应被跳过，得到 %d 块" % len(r.blocks))
    check(r.blocks[0].block_id == "b1" and r.blocks[1].block_id == "b2",
          "重组顺序错")
    check(r.as_text().startswith("Baan Rimping"), "as_text 重组结果不对")
    for b in r.blocks:
        check(b.locator.startswith("p1@"), "locator 丢了：%r" % b.locator)
        check(b.source_text, "原文没被保留 —— 出事时无法对照")


# ══════════════════════════════════════ 敬语一致

def test_thai_particles_not_mixed() -> None:
    """一份文档里混用 ครับ 与 ค่ะ 是最常见的泰文翻译事故。"""
    expect_raises(TranslateRejected,
                  lambda: translate(ir(), "th",
                                    {"b1": "ยินดีครับ", "b2": "ขอบคุณค่ะ"}, Glossary()),
                  "ครับ/ค่ะ 混用却通过了")

    # 负对照:统一用一种必须通过
    try:
        translate(ir(), "th", {"b1": "ยินดีครับ", "b2": "ขอบคุณครับ"}, Glossary())
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：统一用 ครับ 却被拒（%s）" % e)

    # 负对照:译成英文时不该跑这条检查
    try:
        translate(ir(), "en", {"b1": "Yes ครับ", "b2": "Thanks ค่ะ"}, Glossary())
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：英文译文也被套用了泰文敬语检查（%s）" % e)


def test_check_particles_unit() -> None:
    check(check_thai_particles("ครับ ... ค่ะ") is not None, "混用没被检出")
    check(check_thai_particles("ครับ ... ครับ") is None, "负对照失败：统一用被误报")
    check(check_thai_particles("Hello world") is None, "负对照失败：无泰文被误报")


# ══════════════════════════════════════ 参数强制

def test_formality_required_and_bounded() -> None:
    """没有「中立」这个选项 —— 不选就是选了一个，而选错的后果收件人才知道。"""
    expect_raises(TranslateRejected,
                  lambda: translate(ir(), "en", GOOD, GL, formality="随便"),
                  "非法 formality 没被拒")
    r = translate(ir(), "en", GOOD, GL)
    check(r.formality == DEFAULT_FORMALITY,
          "默认 formality 不是 business，得到 %r" % r.formality)
    check(DEFAULT_FORMALITY == "business", "默认应为商务正式")


def test_target_lang_bounded() -> None:
    expect_raises(TranslateRejected, lambda: translate(ir(), "fr", GOOD, GL),
                  "未支持的语言没被拒")
    for lang in ("en", "zh"):
        try:
            translate(ir(), lang, GOOD, GL)
        except Exception as e:                               # noqa: BLE001
            FAILS.append("负对照失败：支持的语言 %r 被拒（%s）" % (lang, e))


def test_glossary_validation() -> None:
    expect_raises(TranslateRejected,
                  lambda: translate(ir(), "en", GOOD, Glossary([Term("  ")])),
                  "空 source 的术语没被拒")
    expect_raises(TranslateRejected,
                  lambda: translate(ir(), "en", GOOD,
                                    Glossary([Term("x"), Term("x")])),
                  "重复术语没被拒")


def test_instruction_states_what_not_to_translate() -> None:
    instr = build_instruction("en", "business", GL.terms)
    check("บ้านริมปิง" in instr, "指示里没列出不该翻的词")
    check("Do NOT translate" in instr, "指示里没写明不要翻译")
    check("business" in instr, "指示里没写敬语级别")

    th = build_instruction("th", "formal", [])
    check("ครับ" in th and "ค่ะ" in th,
          "译成泰文时的指示没提敬语粒子一致性")

    # 负对照:译成英文时不该出现泰文粒子的指示
    en = build_instruction("en", "business", [])
    check("ครับ" not in en, "负对照失败：英文指示里混进了泰文粒子规则")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    for t in TESTS:
        t()
    if FAILS:
        print("✗ %d 个测试断言失败" % len(FAILS), file=sys.stderr)
        for f in FAILS:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ translate 测试全部通过（%d 个测试函数，含专有名词与敬语的负对照）"
          % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
