#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docir.py 的测试。

重点是两条：**出处必须能回溯**、**泰文按字符不按空格切**。
后者是「本地化不是翻译」这句话最具体的兑现物 ——
用空格切泰文，整段会被当成一个词，检索召回极差。

每条断言配负对照。跑法：python3 test_docir.py
"""

import sys
import unicodedata

from docir import (
    Block,
    DocIR,
    DocIRError,
    SourceInfo,
    doc_id_for,
    has_thai,
    normalize_thai,
)

FAILS: list[str] = []

# 一段真实形状的泰文:**整段没有一个空格**，这正是问题所在。
THAI_LONG = ("เรียนลูกค้าที่เคารพทางโรงแรมขอแจ้งให้ทราบว่าเมนูอาหารเช้าจะมีการ"
             "เปลี่ยนแปลงในเดือนหน้าโดยจะเพิ่มรายการอาหารไทยและอาหารมังสวิรัติ"
             "หากท่านมีข้อสงสัยประการใดกรุณาติดต่อแผนกต้อนรับได้ตลอดเวลา")


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def expect_raises(exc, fn, msg: str) -> None:
    try:
        fn()
    except exc:
        return
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("%s（抛的是 %s）" % (msg, type(e).__name__))
        return
    FAILS.append(msg)


def blk(**kw) -> Block:
    base = dict(id="b1", type="paragraph", page=1, bbox=(10, 10, 200, 60),
                text="hello", lang=["en"], table=None)
    base.update(kw)
    return Block(**base)


def ir(blocks=None, pages=3) -> DocIR:
    return DocIR.from_blocks(
        "sha256:x", SourceInfo("f.pdf", "application/pdf", pages),
        blocks if blocks is not None else [blk()])


# ══════════════════════════════════════ 泰文分块：按字符不按空格

def test_thai_chunking_not_by_space() -> None:
    """泰文长段必须被切成多块，而不是因为「没有空格」被当成一整块。"""
    d = ir([blk(text=THAI_LONG, lang=["th"])])
    chunks = d.chunk_for_embedding(max_chars=80, overlap=10)

    check(len(chunks) > 1,
          "泰文分块破了：%d 字符的无空格泰文段落只切出 %d 块。"
          "常规按空格切会把整段当成一个词，检索召回极差"
          % (len(THAI_LONG), len(chunks)))
    check(all(len(c["text"]) <= 80 for c in chunks),
          "有块超过 max_chars：%r" % [len(c["text"]) for c in chunks])
    check(all(c["has_thai"] for c in chunks), "泰文块没被标记 has_thai")

    # 负对照:短泰文段落不该被切 —— 否则「见泰文就切碎」也能让上面绿
    short = ir([blk(text="สวัสดีครับ", lang=["th"])])
    check(len(short.chunk_for_embedding(max_chars=800)) == 1,
          "负对照失败：短泰文段落也被切碎了")

    # 负对照:英文按同样规则也要能切 —— 否则规则只对泰文生效就是特例硬编码
    en = ir([blk(text="Sentence one. " * 40, lang=["en"])])
    check(len(en.chunk_for_embedding(max_chars=100)) > 1,
          "负对照失败：英文长段没被切分")


def test_splits_at_sentence_boundary_not_arbitrary() -> None:
    """必须在句子边界断开，而不是靠「超长硬切」兜底。

    早先只断言「切成了多块」，但无空格的泰文长段会走硬切兜底 ——
    把边界规则改成「按空格切」照样能切出多块，测试分辨不出来。
    变异测试抓到了这一点。

    这里用**带句末标点**的样本：每句都短于 max_chars，所以硬切不会介入，
    只有边界规则本身能决定切在哪。
    """
    # 三句泰文，各自以 。 结尾。单句长度要 ≥50（chunk 的 max_chars 下限），
    # 这样硬切不会介入，只有边界规则本身能决定切在哪。
    sent = "เมนูอาหารเช้าใหม่จะเริ่มให้บริการตั้งแต่เดือนหน้าเป็นต้นไปนะคะ。"
    text = sent * 3
    d = ir([blk(text=text, lang=["th"])])
    chunks = d.chunk_for_embedding(max_chars=len(sent) + 5, overlap=0)

    check(len(chunks) >= 2, "带句末标点的多句文本没被切开：%d 块" % len(chunks))
    # 关键断言:每一块都应当以句末标点收尾（说明是在边界断的，不是拦腰砍的）
    bad = [c["text"] for c in chunks if not c["text"].rstrip().endswith("。")]
    check(not bad,
          "有块不是在句子边界断开的（拦腰砍了）：%r —— "
          "说明边界规则失效，只剩超长硬切在兜底" % bad)


def test_chunks_keep_provenance() -> None:
    """切块之后仍然能回溯出处 —— 否则 search 答不出「在第几页」。"""
    d = ir([blk(id="b7", page=2, text=THAI_LONG, lang=["th"])])
    chunks = d.chunk_for_embedding(max_chars=80)
    check(bool(chunks), "没有切出块")
    for c in chunks:
        check(c["block_ids"] == ["b7"], "block_ids 丢了：%r" % c["block_ids"])
        check(c["page"] == 2, "page 丢了：%r" % c["page"])
        check(c["locators"] and c["locators"][0].startswith("p2@"),
              "locator 丢了或格式错：%r" % c["locators"])


def test_chunk_params_validated() -> None:
    d = ir()
    expect_raises(DocIRError, lambda: d.chunk_for_embedding(max_chars=10),
                  "过小的 max_chars 没被拒 —— 切出来的块没有语义")
    expect_raises(DocIRError, lambda: d.chunk_for_embedding(max_chars=100, overlap=100),
                  "overlap >= max_chars 没被拒（会死循环或空块）")
    expect_raises(DocIRError, lambda: d.chunk_for_embedding(max_chars=100, overlap=-1),
                  "负 overlap 没被拒")


def test_default_overlap_never_self_rejects() -> None:
    """回归:默认 overlap 曾写死成 80，当 max_chars=80 时撞上自己的校验直接抛错。

    **默认值不该在合法参数下自炸。** 这个 bug 是写测试时被抓到的 ——
    自检里恰好没用到这个组合。
    """
    d = ir([blk(text=THAI_LONG, lang=["th"])])
    for mc in (50, 60, 80, 100, 800):
        try:
            got = d.chunk_for_embedding(max_chars=mc)
            check(bool(got), "max_chars=%d 时没切出块" % mc)
        except DocIRError as e:
            FAILS.append("默认 overlap 在 max_chars=%d 时自炸：%s" % (mc, e))

    # 负对照:显式传的非法 overlap 仍然必须被拒
    expect_raises(DocIRError, lambda: d.chunk_for_embedding(max_chars=80, overlap=80),
                  "显式传 overlap==max_chars 竟然被放行 —— 校验被改松了")


def test_figure_and_empty_skipped() -> None:
    d = ir([blk(id="f1", type="figure", text="图注"),
            blk(id="e1", text="   "),
            blk(id="p1", text="真实内容")])
    ids = {i for c in d.chunk_for_embedding() for i in c["block_ids"]}
    check(ids == {"p1"}, "figure 或空块没被跳过：%r" % ids)


# ══════════════════════════════════════ NFC 归一化

# 真会被 NFC 规范排序重排的泰文:声调符 MAI TRI(ccc=107) 排在了元音符 SARA U(ccc=103)
# 前面 —— 这正是 documents.md §3.3 第 2 条说的「元音符号与辅音顺序颠倒」。
# 肉眼看着一样，字符串比对全错。
THAI_MISORDERED = "ก\u0e4a\u0e38"          # ก + MAI TRI + SARA U（错序）
THAI_CANONICAL = "ก\u0e38\u0e4a"           # NFC 之后：SARA U 在前

def test_nfc_normalization_on_ingest() -> None:
    """入口统一归一化 —— 否则肉眼相同的泰文串比对不相等。

    早先这个测试用的是 NFD("กำ")，但 **SARA AM 根本不可分解**，
    NFD 与 NFC 相等 —— 测试等于空转，去掉归一化也照样通过。
    变异测试抓到了这一点。现在用真会被重排的序列。
    """
    check(THAI_MISORDERED != THAI_CANONICAL,
          "测试样本本身有问题：错序与规范序相同，这个测试测不出任何东西")
    check(unicodedata.normalize("NFC", THAI_MISORDERED) == THAI_CANONICAL,
          "测试样本有问题：NFC 没有把它重排成预期的规范序")

    d = ir([blk(text=THAI_MISORDERED, lang=["th"])])
    check(d.blocks[0].text == THAI_CANONICAL,
          "入口没做 NFC 归一化 —— 肉眼看着对的泰文串会比对不相等，"
          "extract 的 schema 校验和 search 的向量检索都会错")

    # 负对照:归一化不该改变已经是规范序的文本
    plain = "Total: 45,000 THB"
    check(normalize_thai(plain) == plain, "负对照失败：归一化改动了纯 ASCII 文本")
    check(normalize_thai(THAI_CANONICAL) == THAI_CANONICAL,
          "负对照失败：归一化改动了已经规范的泰文")


def test_has_thai() -> None:
    check(has_thai("สวัสดี"), "泰文没被识别")
    check(has_thai("Hello สวัสดี"), "混排里的泰文没被识别")
    check(not has_thai("Hello world"), "负对照失败：纯英文被判成含泰文")
    check(not has_thai("你好世界"), "负对照失败：中文被判成泰文")


# ══════════════════════════════════════ 结构校验

def test_locator_required_fields() -> None:
    """page 与 bbox 是硬要求 —— 没有它们，抽取结果客户点不回原文。"""
    expect_raises(DocIRError, lambda: ir([blk(page=0)]).validate(),
                  "page=0 没被拒")
    expect_raises(DocIRError, lambda: ir([blk(page=99)], pages=3).validate(),
                  "page 超出文档页数没被拒")
    expect_raises(DocIRError, lambda: ir([blk(bbox=(10, 10, 5, 60))]).validate(),
                  "非法 bbox（x1<x0）没被拒")
    expect_raises(DocIRError, lambda: ir([blk(bbox=(10, 10, 200))]).validate(),  # type: ignore[arg-type]
                  "bbox 只有 3 个数没被拒")

    # 负对照:合法的必须过
    try:
        ir([blk(page=3)], pages=3).validate()
    except DocIRError as e:
        FAILS.append("负对照失败：合法的最后一页被拒（%s）" % e)


def test_structural_validation() -> None:
    expect_raises(DocIRError, lambda: ir([]).validate(),
                  "空 blocks 没被拒 —— 解析失败会静默进入后续动作")
    expect_raises(DocIRError, lambda: ir([blk(id="x"), blk(id="x")]).validate(),
                  "重复 block id 没被拒 —— citation 会指向错误的块")
    expect_raises(DocIRError, lambda: ir([blk(type="weird")]).validate(),
                  "未知 block type 没被拒")
    expect_raises(DocIRError, lambda: ir([blk(type="table")]).validate(),
                  "type=table 却没有 table 数据，没被拒")
    expect_raises(DocIRError, lambda: ir([blk(table={"rows": []})]).validate(),
                  "非 table 类型带了 table 数据，没被拒")

    bad = ir()
    bad.doc_id = ""
    expect_raises(DocIRError, bad.validate, "空 doc_id 没被拒")
    bad2 = ir()
    bad2.source = SourceInfo("", "application/pdf", 1)
    expect_raises(DocIRError, bad2.validate, "空 filename 没被拒")
    bad3 = ir()
    bad3.source = SourceInfo("f.pdf", "application/pdf", 0)
    expect_raises(DocIRError, bad3.validate, "pages=0 没被拒")


# ══════════════════════════════════════ 语言与序列化

def test_lang_detected_is_list_per_block() -> None:
    """lang_detected 是数组、按 block 汇总 —— 泰英混排是常态，整篇一个值会误判。"""
    d = ir([blk(id="a", text="Hello", lang=["en"]),
            blk(id="b", text="สวัสดี", lang=["th"]),
            blk(id="c", text="你好", lang=["zh"])])
    check(d.lang_detected == ["en", "th", "zh"],
          "lang_detected 汇总错：%r" % d.lang_detected)

    # 负对照:单语文档不该出现多个语言
    single = ir([blk(lang=["en"]), blk(id="b2", lang=["en"])])
    check(single.lang_detected == ["en"],
          "负对照失败：单语文档的 lang_detected 是 %r" % single.lang_detected)


def test_roundtrip() -> None:
    d = ir([blk(id="t", type="table", text="x", table={"rows": [["a"]], "header": True})])
    back = DocIR.from_dict(d.to_dict())
    check(back.to_dict() == d.to_dict(), "to_dict/from_dict 往返不一致")
    check(isinstance(back.blocks[0].bbox, tuple), "往返后 bbox 不是 tuple")
    back.validate()   # 往返后仍应通过校验


def test_doc_id_stable() -> None:
    a, b = doc_id_for(b"same"), doc_id_for(b"same")
    check(a == b, "同样内容的 doc_id 不稳定")
    check(a != doc_id_for(b"different"), "不同内容的 doc_id 相同 —— 会串文档")
    check(a.startswith("sha256:"), "doc_id 缺前缀：%r" % a)


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    for t in TESTS:
        t()
    if FAILS:
        print("✗ %d 个测试断言失败" % len(FAILS), file=sys.stderr)
        for f in FAILS:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ docir 测试全部通过（%d 个测试函数，含泰文分块与出处回溯的负对照）"
          % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
