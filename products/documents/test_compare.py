#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compare 的测试。

核心是 `documents.md` §4 写下的验收标准，逐字实现：

> 人工构造 10 处差异（含 2 处顺序调换、2 处数字微调），**全部要被找出**。

外加覆盖不变式的两头对照 —— 一个「什么都报成 modified」的实现
也能让「全部找出」通过，所以必须同时测「没变的不能被报成变了」。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docir import Block, DocIR, SourceInfo                   # noqa: E402
from compare import (                                        # noqa: E402
    CompareRejected,
    CompareResult,
    CoverageError,
    compare,
    numbers_in,
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


def doc(doc_id: str, texts: list[str], prefix: str) -> DocIR:
    return DocIR.from_blocks(
        doc_id=doc_id,
        source=SourceInfo(filename=doc_id + ".pdf", mime="application/pdf", pages=1),
        blocks=[Block(id="%s%d" % (prefix, i + 1), type="paragraph", page=1,
                      bbox=(0, i * 10.0, 100, i * 10.0 + 8), text=t)
                for i, t in enumerate(texts)])


# ══════════════════════════ 验收标准：10 处差异全部找出

# 旧合同 12 条。
OLD_CLAUSES = [
    "第一条 本合同自双方签字之日起生效",
    "第二条 甲方应于收到发票后 30 天内付款",                    # ① 数字微调
    "第三条 乙方负责货物运输及保险",
    "第四条 违约金为合同金额的 5%",                            # ② 数字微调
    "第五条 保密义务在合同终止后持续两年",
    "第六条 争议提交清迈仲裁委员会",                            # ③ 顺序调换
    "第七条 甲方有权随时终止本合同",                            # ④ 整条删除
    "第八条 乙方应提供质量检验报告",
    "第九条 本合同一式两份",                                   # ⑤ 顺序调换
    "第十条 附件为合同不可分割部分",
    "第十一条 不可抗力条款适用泰国法律",                        # ⑥ 措辞修改
    "第十二条 通知以书面形式送达",
]

# 新合同:①②数字变、③⑤位置换、④删除、⑥措辞改、⑦⑧新增两条、
# ⑨⑩ 两条被改写(非数字)
NEW_CLAUSES = [
    "第一条 本合同自双方签字之日起生效",
    "第二条 甲方应于收到发票后 60 天内付款",                    # ① 30→60
    "第三条 乙方负责货物运输及保险",
    "第四条 违约金为合同金额的 8%",                            # ② 5→8
    "第五条 保密义务在合同终止后持续两年",
    "第九条 本合同一式两份",                                   # ⑤ 上移
    "第八条 乙方应提供质量检验报告",
    "第六条 争议提交清迈仲裁委员会",                            # ③ 下移
    "第十条 附件为合同不可分割部分",
    "第十一条 不可抗力条款适用泰王国法律",                      # ⑥ 泰国→泰王国
    "第十二条 通知应以书面形式送达指定地址",                    # ⑨ 措辞改写
    "第十三条 双方可协商延长履约期限",                          # ⑦ 新增
    "第十四条 本合同以泰文版本为准",                            # ⑧ 新增
]

# 模型给出的配对。⑩ 刻意**漏配**第七条 —— 测「模型漏了会怎样」。
MODEL_PAIRS = [
    {"old_block_id": "o1", "new_block_id": "n1", "note": "未变"},
    {"old_block_id": "o2", "new_block_id": "n2", "note": "付款周期变更", "risk": "low"},
    {"old_block_id": "o3", "new_block_id": "n3", "note": "未变"},
    {"old_block_id": "o4", "new_block_id": "n4", "note": "违约金比例变更", "risk": "low"},
    {"old_block_id": "o5", "new_block_id": "n5", "note": "未变"},
    {"old_block_id": "o6", "new_block_id": "n8", "note": "位置调整"},
    {"old_block_id": "o8", "new_block_id": "n7", "note": "未变"},
    {"old_block_id": "o9", "new_block_id": "n6", "note": "位置调整"},
    {"old_block_id": "o10", "new_block_id": "n9", "note": "位置调整"},
    {"old_block_id": "o11", "new_block_id": "n10", "note": "措辞修改", "risk": "medium"},
    {"old_block_id": "o12", "new_block_id": "n11", "note": "措辞修改", "risk": "low"},
    {"old_block_id": None, "new_block_id": "n12", "note": "新增条款"},
    {"old_block_id": None, "new_block_id": "n13", "note": "新增条款"},
    # o7 故意不配 —— 模型漏了
]


def full_compare() -> CompareResult:
    return compare(doc("sha256:old", OLD_CLAUSES, "o"),
                   doc("sha256:new", NEW_CLAUSES, "n"),
                   [dict(p) for p in MODEL_PAIRS])


def test_all_ten_constructed_differences_are_found() -> None:
    """`documents.md` §4 的验收标准，逐条核。"""
    r = full_compare()

    # ①② 两处数字微调 —— 必须被找出，且**强制 high**
    nums = [d for d in r.of_kind("modified") if d.risk_forced]
    check(len(nums) == 2,
          "两处数字微调没被强制升为 high：%r"
          % [(d.before.block_id, d.risk, d.risk_forced[:20]) for d in r.of_kind("modified")])
    forced_ids = {d.before.block_id for d in nums}
    check(forced_ids == {"o2", "o4"},
          "被强制升级的不是那两条数字改动：%r" % forced_ids)

    # ③⑤ 两处顺序调换 —— 必须是 moved，不是 removed + added
    moved = {d.before.block_id for d in r.of_kind("moved")}
    check("o6" in moved and "o9" in moved,
          "顺序调换没被识别为 moved：%r" % moved)
    check(not any(d.before and d.before.block_id in ("o6", "o9")
                  for d in r.of_kind("removed")),
          "顺序调换被报成了删除 —— 客户读到「删除」会去追问为什么把这条拿掉了")

    # ④ 整条删除
    removed = {d.before.block_id for d in r.of_kind("removed")}
    check("o7" in removed, "被删除的第七条没出现在 removed 里：%r" % removed)

    # ⑥⑨ 措辞修改
    modified = {d.before.block_id for d in r.of_kind("modified")}
    check("o11" in modified and "o12" in modified,
          "措辞修改没被识别为 modified：%r" % modified)

    # ⑦⑧ 两条新增
    added = {d.after.block_id for d in r.of_kind("added")}
    check({"n12", "n13"} <= added, "新增条款没被找全：%r" % added)


def test_model_omission_becomes_a_removal_not_silence() -> None:
    """模型漏配的那一条，必须冒出来，而不是无声无息。

    这是最要紧的一条：**模型漏配和真删除，在这里是一样的处理。**
    宁可多报一条「已按删除处理」让人去看，也不能让它消失。
    """
    r = full_compare()
    omitted = [d for d in r.of_kind("removed") if d.before.block_id == "o7"]
    check(len(omitted) == 1, "模型漏配的 o7 消失了 —— 差异清单看起来干净，但漏了一条")
    check("未提及" in omitted[0].note, "漏配没被标出来源：%r" % omitted[0].note)
    check(any("o7" in n for n in r.notes),
          "漏配没进 notes —— 人看不到「这条是我们补的，不是模型找出来的」")


# ══════════════════════════ 支点：覆盖对账

def test_coverage_reconciliation_actually_fires() -> None:
    """负对照：**手工造一个漏了块的结果**，对账必须炸。

    没有这条，一个 `pass` 的对账函数也能让上面全绿 ——
    因为正常路径本来就不漏。
    """
    from compare import _assert_full_coverage                 # noqa: PLC0415

    old, new = doc("sha256:old", OLD_CLAUSES, "o"), doc("sha256:new", NEW_CLAUSES, "n")
    r = full_compare()

    for cut in (1, 5, len(r.diffs) - 1):
        broken = CompareResult(old.doc_id, new.doc_id, diffs=r.diffs[:cut])
        expect_raises(CoverageError,
                      lambda b=broken: _assert_full_coverage(old, new, b),
                      "只保留 %d 条差异时覆盖对账没炸 —— 这个模块的支点是死的" % cut)

    # 完整的结果必须通过 —— 否则「永远炸」也能让上面全绿
    try:
        _assert_full_coverage(old, new, r)
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("完整结果被覆盖对账误判为漏项（%s）" % e)


def test_double_counting_rejected() -> None:
    """同一个块被交代两次也要抓 —— 重复计入会掩盖漏项。

    差异总数对得上、但其实是「A 报了两次、B 一次没报」，
    只数总数的对账会放过去。
    """
    from compare import _assert_full_coverage                 # noqa: PLC0415

    old, new = doc("sha256:old", OLD_CLAUSES, "o"), doc("sha256:new", NEW_CLAUSES, "n")
    r = full_compare()
    dupe = CompareResult(old.doc_id, new.doc_id, diffs=r.diffs + [r.diffs[0]])
    expect_raises(CoverageError,
                  lambda: _assert_full_coverage(old, new, dupe),
                  "同一个块被交代两次没被抓到 —— 重复计入会掩盖漏项")


def test_pairing_same_block_twice_rejected_at_pairing_time() -> None:
    """模型把同一个块配对两次，要**在配对这一步**拒，并说清是配重了。

    这条测试原先只断言「抛了 CompareRejected」—— 而 CoverageError 是它的子类，
    所以把早期拦截整个摘掉，测试照样绿：后面的覆盖对账会接住。
    变异测试报出「这条属性没有被兜住」，查下来是测试断言得太松。

    两条路径都会拒绝，所以那不是正确性 bug；但早期拦截的价值正是
    **它能说清是模型把同一条配了两次**，而不是让人去查覆盖对账为什么不平。
    诊断信息本身就是要守的属性，所以断言到消息这一层。
    """
    old, new = doc("sha256:old", ["a", "b"], "o"), doc("sha256:new", ["a", "b"], "n")
    try:
        compare(old, new, [{"old_block_id": "o1", "new_block_id": "n1"},
                           {"old_block_id": "o1", "new_block_id": "n2"}])
        FAILS.append("同一个旧块被配对两次没被拒")
        return
    except CoverageError as e:
        FAILS.append("配重是被覆盖对账兜住的，不是配对这一步（%s）—— "
                     "报错该说清是模型配重了，而不是让人去查覆盖对账为什么不平" % e)
        return
    except CompareRejected as e:
        check("配对了两次" in str(e),
              "拒绝了但没说清原因：%s" % e)


# ══════════════════════════ 正对照：不能靠「什么都报成变了」蒙混

def test_identical_documents_report_no_changes() -> None:
    """两份内容相同的文档，必须全是 unchanged。

    没有这条，一个「什么都报成 modified」的实现也能让「10 处全找出」通过 ——
    然后客户拿到一份「每条都改了」的清单，等于没有清单。
    """
    same = list(OLD_CLAUSES)
    old, new = doc("sha256:old", same, "o"), doc("sha256:new", same, "n")
    r = compare(old, new, [{"old_block_id": "o%d" % (i + 1),
                            "new_block_id": "n%d" % (i + 1)}
                           for i in range(len(same))])
    kinds = {d.kind for d in r.diffs}
    check(kinds == {"unchanged"},
          "内容完全相同的两份文档报出了变更：%r —— "
          "「每条都改了」的清单等于没有清单" % sorted(kinds))
    check(r.high_risk() == [], "没有变化却报出了 high 风险：%r" % r.high_risk())


def test_whitespace_only_difference_is_unchanged() -> None:
    """只差空白不算改动 —— PDF 解析出来的空白本来就不稳定。

    否则每次重新解析同一份文档都会报出一堆「改动」，清单立刻失去可信度。
    """
    old = doc("sha256:old", ["甲方应于 30 天内付款"], "o")
    new = doc("sha256:new", ["甲方应于  30 天内付款 "], "n")
    r = compare(old, new, [{"old_block_id": "o1", "new_block_id": "n1"}])
    check(r.diffs[0].kind == "unchanged",
          "只差空白被报成了 %r —— PDF 的空白本来就不稳定" % r.diffs[0].kind)


# ══════════════════════════ 数字

def test_numeric_change_forces_high_risk() -> None:
    """数字变了一律 high，**模型说 low 也不算数**。"""
    old = doc("sha256:old", ["违约金为合同金额的 5%"], "o")
    new = doc("sha256:new", ["违约金为合同金额的 8%"], "n")
    r = compare(old, new, [{"old_block_id": "o1", "new_block_id": "n1",
                            "note": "小改动", "risk": "low"}])
    check(r.diffs[0].risk == "high",
          "模型说 low，数字却变了，风险没被强制升级：%r" % r.diffs[0].risk)
    check(r.diffs[0].risk_forced != "", "强制升级没留下说明，人不知道为什么变 high")


def test_thai_digits_are_counted() -> None:
    """泰文数字必须一起数。

    客户的合同里两种写法都有。只认阿拉伯数字的话，
    **泰数字写的金额改动会静默漏过** —— 而金额正是最要命的那一类。
    """
    check(numbers_in("ราคา ๔๕,๐๐๐ บาท") == ["45000"],
          "泰文数字没被识别：%r" % numbers_in("ราคา ๔๕,๐๐๐ บาท"))
    old = doc("sha256:old", ["ราคารวม ๓๐,๐๐๐ บาท"], "o")
    new = doc("sha256:new", ["ราคารวม ๕๐,๐๐๐ บาท"], "n")
    r = compare(old, new, [{"old_block_id": "o1", "new_block_id": "n1", "risk": "low"}])
    check(r.diffs[0].risk == "high",
          "泰文数字的金额改动没被强制升为 high —— 金额是最要命的那一类")


def test_non_numeric_change_not_force_escalated() -> None:
    """负对照：措辞改动不该被强制升级。

    否则「一律 high」也能让上面全绿 —— 然后 high 就不再意味着什么，
    人会开始忽略它，而这比不标风险更糟。
    """
    old = doc("sha256:old", ["不可抗力条款适用泰国法律"], "o")
    new = doc("sha256:new", ["不可抗力条款适用泰王国法律"], "n")
    r = compare(old, new, [{"old_block_id": "o1", "new_block_id": "n1", "risk": "medium"}])
    check(r.diffs[0].risk == "medium",
          "非数字改动被强制升级了：%r —— 一律 high 会让 high 失去意义"
          % r.diffs[0].risk)
    check(r.diffs[0].risk_forced == "", "非数字改动留下了强制升级说明")


# ══════════════════════════ 出处

def test_bidirectional_citation_required() -> None:
    """modified / moved / unchanged 必须两头都指得回去。"""
    from compare import Diff, BlockRef                        # noqa: PLC0415

    for kind in ("unchanged", "modified", "moved"):
        d = Diff(kind=kind, before=BlockRef("old", "o1", 1), after=None)
        expect_raises(CompareRejected, d.validate,
                      "%s 只带了一头的出处却通过了校验 —— 客户没法核对改了什么" % kind)


def test_fabricated_block_id_rejected() -> None:
    old, new = doc("sha256:old", ["a"], "o"), doc("sha256:new", ["a"], "n")
    expect_raises(CompareRejected,
                  lambda: compare(old, new, [{"old_block_id": "o99",
                                              "new_block_id": "n1"}]),
                  "编造的 block_id 没被拒 —— 编出处比不给出处更危险")


def test_same_document_rejected() -> None:
    """对比自己没有意义，多半是传错了文件。"""
    d = doc("sha256:same", ["a"], "o")
    expect_raises(CompareRejected, lambda: compare(d, d, []),
                  "同一份文档跟自己对比没被拒")


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
    print("✓ compare 测试全部通过（%d 个测试函数，含 §4 验收标准的 10 处构造差异）"
          % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
