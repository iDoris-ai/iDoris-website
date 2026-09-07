#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""summarize 的测试。

这个模块只有一条真正要紧的属性：**合并不会悄悄丢掉一条决议。**

难点在于它有两种坏法，而只测一种的话另一种照样全绿：

| 坏法 | 表现 | 会不会被发现 |
|:---|:---|:---|
| 合并丢内容 | 输出完整通顺，少一条决议 | **不会**，客户照着执行 |
| 什么都不许变 | key_points 也压不了，去重也不做 | 会，但摘要没用了 |

所以每条「必须保住」的断言都配一条「必须允许变」的正对照。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docir import Block, DocIR, SourceInfo                   # noqa: E402
from summarize import (                                      # noqa: E402
    COMPRESSIBLE_FIELDS,
    LOSSLESS_FIELDS,
    MergeLostContentError,
    PartialSummary,
    Summary,
    SummarizeRejected,
    SummaryItem,
    check_owners_verbatim,
    merge,
    summarize_chunk,
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


def out(**sections):
    base = {"key_points": [], "decisions": [], "action_items": [], "open_questions": []}
    base.update(sections)
    return {"doc_type": "meeting_minutes", "sections": base}


def parts():
    d = ir()
    p1 = summarize_chunk(d, 0, out(
        key_points=[{"text": "讨论了付款周期", "block_id": "b1"}],
        decisions=[{"text": "付款周期 30 天改为 60 天", "block_id": "b1"}]))
    p2 = summarize_chunk(d, 1, out(
        key_points=[{"text": "菜单翻译分工", "block_id": "b2"}],
        action_items=[{"text": "完成英文菜单翻译", "block_id": "b2",
                       "owner": "Nid", "due": "Friday"}]))
    p3 = summarize_chunk(d, 2, out(
        action_items=[{"text": "确认菜品名称", "block_id": "b3",
                       "owner": "Boon", "due": "Wednesday"}]))
    return d, [p1, p2, p3]


# ══════════════════════════ 支点：合并不丢决议

def test_merge_keeps_every_decision_and_action_item() -> None:
    _, ps = parts()
    m = merge(ps)
    check(len(m.sections["decisions"]) == 1,
          "决议丢了：%r" % m.sections["decisions"])
    check(len(m.sections["action_items"]) == 2,
          "待办丢了：%r" % m.sections["action_items"])
    texts = {i.text for i in m.sections["action_items"]}
    check(texts == {"完成英文菜单翻译", "确认菜品名称"}, "待办内容不对：%r" % texts)


def test_the_reconciliation_actually_fires() -> None:
    """负对照：**手工造一个丢了内容的合并结果**，对账必须炸。

    没有这条，一个 `pass` 的对账函数也能让上面那条全绿 ——
    因为正常路径本来就不会丢。
    """
    _, ps = parts()
    m = merge(ps)

    from summarize import _assert_nothing_lost                # noqa: PLC0415

    for name in ("decisions", "action_items"):
        broken = Summary(doc_id=m.doc_id, doc_type=m.doc_type,
                         sections=dict(m.sections, **{name: []}))
        expect_raises(MergeLostContentError,
                      lambda b=broken: _assert_nothing_lost(ps, b),
                      "对账没抓到被清空的 %s —— 这个模块的支点是死的" % name)

    # 只丢一条(不是清空)也必须抓到 —— 真实的丢法从来不是整段消失
    only_one = Summary(
        doc_id=m.doc_id, doc_type=m.doc_type,
        sections=dict(m.sections, action_items=m.sections["action_items"][:1]))
    expect_raises(MergeLostContentError,
                  lambda: _assert_nothing_lost(ps, only_one),
                  "对账没抓到「少了一条」—— 真实的丢法就是这样，不是整段消失")


def test_every_lossless_field_is_reconciled() -> None:
    """LOSSLESS_FIELDS 里的**每一个**字段都要真的被对账，不能只兜住 decisions。

    这个集合是模块的支点。从里面拿掉一个字段，那个字段就可以在合并时静默消失，
    而其余测试全都不会变红。
    """
    from summarize import _assert_nothing_lost, SKELETONS     # noqa: PLC0415

    d = ir()
    for doc_type, skeleton in SKELETONS.items():
        for name in skeleton:
            if name not in LOSSLESS_FIELDS:
                continue
            p = PartialSummary(
                doc_id=d.doc_id, doc_type=doc_type, chunk_index=0,
                sections={name: [SummaryItem(text="要保住的一条", block_id="b1")]})
            empty = Summary(doc_id=d.doc_id, doc_type=doc_type, sections={name: []})
            expect_raises(MergeLostContentError,
                          lambda p=p, e=empty: _assert_nothing_lost([p], e),
                          "字段 %s（%s 骨架）丢了内容却没被对账抓到" % (name, doc_type))


# ══════════════════════════ 正对照：不能靠「什么都不许变」蒙混

def test_key_points_can_be_compressed() -> None:
    """key_points 是**唯一**允许压缩的。

    没有这条正对照，一个「任何变化都报错」的实现也能让上面全绿 ——
    然后长文档的摘要压不动，这个动作就没用了。
    """
    _, ps = parts()
    squeezed = [SummaryItem(text="讨论了付款周期与菜单翻译分工", block_id="b1")]
    m = merge(ps, compressed_key_points=squeezed)
    check(len(m.sections["key_points"]) == 1,
          "key_points 压缩没生效：%r" % m.sections["key_points"])
    # 压缩 key_points 的同时，决议一条都不能少
    check(len(m.sections["decisions"]) == 1,
          "压缩 key_points 时把决议弄丢了：%r" % m.sections["decisions"])
    check(len(m.sections["action_items"]) == 2,
          "压缩 key_points 时把待办弄丢了：%r" % m.sections["action_items"])


def test_overlapping_chunks_dedup_is_not_loss() -> None:
    """重叠块产生的同一条要去重，且去重不算「丢」。

    分块是带 overlap 的，同一条决议必然在相邻两块里各出现一次。
    不去重的话，一页纪要上同一条决议会印两遍 —— 客户会觉得我们没在看。
    """
    d = ir()
    same = {"text": "付款周期 30 天改为 60 天", "block_id": "b1"}
    p1 = summarize_chunk(d, 0, out(decisions=[same]))
    p2 = summarize_chunk(d, 1, out(decisions=[dict(same)]))
    m = merge([p1, p2])
    check(len(m.sections["decisions"]) == 1,
          "重叠块的同一条决议没去重，印了 %d 遍" % len(m.sections["decisions"]))


def test_whitespace_only_difference_is_the_same_item() -> None:
    """只差空白的两条是同一条。

    这条看着琐碎，实际是对账**能不能工作**的前提：
    如果身份用的是原始串，合并时多一个空格就被当成「另一条」，
    对账里 before 的那条永远找不到对应，于是要么永远炸、要么永远过 ——
    两种都等于没有对账。
    """
    d = ir()
    p1 = summarize_chunk(d, 0, out(decisions=[
        {"text": "付款周期 30 天改为 60 天", "block_id": "b1"}]))
    p2 = summarize_chunk(d, 1, out(decisions=[
        {"text": "付款周期 30 天改为  60 天 ", "block_id": "b1"}]))
    m = merge([p1, p2])
    check(len(m.sections["decisions"]) == 1,
          "只差空白的两条没被当成同一条：%r" % m.sections["decisions"])

    # 负对照：真正不同的内容不能被合并掉
    p3 = summarize_chunk(d, 2, out(decisions=[
        {"text": "付款周期 30 天改为 90 天", "block_id": "b1"}]))
    m2 = merge([p1, p3])
    check(len(m2.sections["decisions"]) == 2,
          "两条不同的决议（60 天 / 90 天）被合并成了一条 —— 这是丢内容")


# ══════════════════════════ 责任人与期限逐字保留

def test_owner_and_due_are_part_of_identity() -> None:
    """同一句话、不同责任人，是**两条不同的待办**。

    「完成翻译 / Nid」和「完成翻译 / Boon」被当成同一条的话，
    合并会吃掉一个人的活，而摘要看起来完全正常。
    """
    d = ir()
    p1 = summarize_chunk(d, 0, out(action_items=[
        {"text": "完成英文菜单翻译", "block_id": "b2", "owner": "Nid", "due": "Friday"}]))
    p2 = summarize_chunk(d, 1, out(action_items=[
        {"text": "完成英文菜单翻译", "block_id": "b2", "owner": "Boon", "due": "Friday"}]))
    m = merge([p1, p2])
    check(len(m.sections["action_items"]) == 2,
          "不同责任人的同一句话被合并成一条 —— 有人的活被吃掉了：%r"
          % [i.as_dict() for i in m.sections["action_items"]])

    # 期限不同也是两条
    p3 = summarize_chunk(d, 2, out(action_items=[
        {"text": "完成英文菜单翻译", "block_id": "b2", "owner": "Nid", "due": "Monday"}]))
    m2 = merge([p1, p3])
    check(len(m2.sections["action_items"]) == 2,
          "不同期限的同一句话被合并成一条 —— 期限被改了没人知道")


def test_check_owners_verbatim_detects_rewriting() -> None:
    _, ps = parts()
    m = merge(ps)
    check(check_owners_verbatim(ps, m) == [], "正常合并被误报为改写")

    tampered = Summary(
        doc_id=m.doc_id, doc_type=m.doc_type,
        sections=dict(m.sections, action_items=[
            SummaryItem(text="完成英文菜单翻译", block_id="b2",
                        owner="the team", due="Friday"),
            m.sections["action_items"][1],
        ]))
    problems = check_owners_verbatim(ps, tampered)
    check(len(problems) == 1 and "责任人" in problems[0],
          "把 Nid 改写成 the team 没被发现：%r —— "
          "「谁承诺了什么」转述一次就变味一次" % problems)


# ══════════════════════════ 出处

def test_fabricated_block_id_rejected() -> None:
    """指向不存在的 block_id 必须拒绝。

    **编出处比不给出处更危险**，因为它看起来是可核对的 ——
    人会以为已经核过了。
    """
    d = ir()
    expect_raises(SummarizeRejected,
                  lambda: summarize_chunk(d, 0, out(decisions=[
                      {"text": "x", "block_id": "b99"}])),
                  "编造的 block_id 没被拒")


def test_missing_block_id_rejected() -> None:
    d = ir()
    expect_raises(SummarizeRejected,
                  lambda: summarize_chunk(d, 0, out(decisions=[{"text": "x"}])),
                  "没带 block_id 的决议没被拒 —— 指不回原文的决议没人敢执行")
    expect_raises(SummarizeRejected,
                  lambda: summarize_chunk(d, 0, out(decisions=[
                      {"text": "x", "block_id": "  "}])),
                  "空白 block_id 没被拒")


# ══════════════════════════ 骨架与类型

def test_unknown_doc_type_not_guessed() -> None:
    d = ir()
    expect_raises(SummarizeRejected,
                  lambda: summarize_chunk(d, 0, {"doc_type": "invoice",
                                                 "sections": {}}),
                  "不认识的 doc_type 被放行了 —— 不猜")


def test_unknown_type_uses_full_skeleton_and_is_flagged() -> None:
    """认不出来时用最全的骨架，并**显式标记**，不假装认得。"""
    d = ir()
    p = summarize_chunk(d, 0, {"doc_type": "unknown", "sections": {
        "key_points": [], "decisions": [{"text": "x", "block_id": "b1"}],
        "action_items": [], "open_questions": []}})
    check(p.type_certain is False, "unknown 类型没被标记为不确定")
    m = merge([p])
    check(m.type_certain is False, "合并后丢掉了「类型不确定」这个标记")
    check(len(m.sections["decisions"]) == 1, "unknown 骨架下决议没保住")


def test_extra_section_rejected() -> None:
    """多出的小节一律拒绝 —— 和 extract 同一个判据。"""
    d = ir()
    expect_raises(SummarizeRejected,
                  lambda: summarize_chunk(d, 0, {"doc_type": "meeting_minutes",
                                                 "sections": {"gossip": []}}),
                  "骨架外的小节没被拒 —— 多字段是模型自由发挥的第一个信号")


def test_contract_skeleton_differs_from_meeting() -> None:
    """不同类型套不同骨架 —— 通用摘要对会议记录会漏掉「谁承诺了什么」。"""
    d = ir()
    p = summarize_chunk(d, 0, {"doc_type": "contract", "sections": {
        "key_points": [], "obligations": [{"text": "乙方按月付款", "block_id": "b1"}],
        "dates_and_amounts": [], "open_questions": []}})
    check("obligations" in p.sections, "合同骨架没有 obligations")
    m = merge([p])
    check(len(m.sections["obligations"]) == 1, "合同的 obligations 没被保住")
    check("decisions" not in m.sections,
          "合同骨架里混进了会议记录的 decisions —— 骨架没有按类型分")


# ══════════════════════════ 合并的边界

def test_mixed_documents_rejected() -> None:
    """不同文档的分块摘要不能合并 —— 会把两份文档的决议混在一起。"""
    d1 = ir()
    d2 = DocIR.from_blocks(
        doc_id="sha256:other",
        source=SourceInfo(filename="other.pdf", mime="application/pdf", pages=1),
        blocks=[Block(id="b1", type="paragraph", page=1, bbox=(0, 0, 10, 10),
                      text="another document")])
    p1 = summarize_chunk(d1, 0, out(decisions=[{"text": "a", "block_id": "b1"}]))
    p2 = summarize_chunk(d2, 0, out(decisions=[{"text": "b", "block_id": "b1"}]))
    expect_raises(SummarizeRejected, lambda: merge([p1, p2]),
                  "两份不同文档的摘要被合并了")


def test_empty_merge_rejected() -> None:
    expect_raises(SummarizeRejected, lambda: merge([]), "空的合并没被拒")


def test_type_disagreement_is_recorded_not_swallowed() -> None:
    """各块类型判断不一致时，取多数但**把分歧记下来**。

    默默取第一个的话，一份混合文档（前半会议记录、后半合同附件）
    会被整份套错骨架，而没人知道发生过分歧。
    """
    d = ir()
    p1 = summarize_chunk(d, 0, out(decisions=[{"text": "a", "block_id": "b1"}]))
    p2 = summarize_chunk(d, 1, out(decisions=[{"text": "b", "block_id": "b1"}]))
    p3 = summarize_chunk(d, 2, {"doc_type": "contract", "sections": {
        "key_points": [], "obligations": [], "dates_and_amounts": [],
        "open_questions": []}})
    m = merge([p1, p2, p3])
    check(m.doc_type == "meeting_minutes", "没有取多数：%r" % m.doc_type)
    check(any("不一致" in n for n in m.notes),
          "分歧被吞掉了，notes=%r —— 混合文档会被整份套错骨架" % m.notes)


def test_field_sets_do_not_overlap() -> None:
    """可压缩与不可压缩不能有交集 —— 否则同一个字段两条规则打架。"""
    check(LOSSLESS_FIELDS & COMPRESSIBLE_FIELDS == frozenset(),
          "字段既可压缩又不可丢：%r" % (LOSSLESS_FIELDS & COMPRESSIBLE_FIELDS))
    check("key_points" not in LOSSLESS_FIELDS,
          "key_points 被列为不可丢 —— 那就压不了，长文档摘要没用了")
    check("decisions" in LOSSLESS_FIELDS, "decisions 不在不可丢集合里")
    check("action_items" in LOSSLESS_FIELDS, "action_items 不在不可丢集合里")


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
    print("✓ summarize 测试全部通过（%d 个测试函数，含「必须保住」与「必须允许变」两头的对照）"
          % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
