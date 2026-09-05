#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search 回答层的测试。

核心是 `documents.md` §4 的验收标准，逐字实现：

> 构造 20 个问题（其中 5 个答案不在文档里），
> **20 题全对且那 5 题都要如实回答「没有」**。

两头都要测。这类系统有两种坏法，后果差得很远：

| 坏法 | 表现 | 会不会被发现 |
|:---|:---|:---|
| 没命中也编一个答案 | 回答率 100%，读起来专业自信 | **不会** —— 它看起来就是对的 |
| 什么都答「没有」 | 回答率 0% | 会，客户第一天就投诉 |

所以「5 题说没有」和「15 题真答出来」必须一起测。
只测前者的话，一个永远说「没有」的实现也是满分。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from search import (                                          # noqa: E402
    MIN_SCORE,
    NOT_FOUND_TEXTS,
    NOT_FOUND_ZH,
    Answer,
    FabricatedAnswerError,
    InMemoryRetriever,
    RetrievedChunk,
    SearchRejected,
    answer,
    has_hit,
    not_found_answer,
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


# ══════════════════════════ §4 验收标准的 20 个问题

# 一份虚构的服务合同,切成 8 块。**虚构内容,不含真实客户信息。**
CHUNKS = [
    {"chunk_id": "c1", "text": "第一条 本合同自双方签字之日起生效，有效期一年。",
     "block_ids": ["b1"], "locators": ["p1@0,0"], "page": 1},
    {"chunk_id": "c2", "text": "第二条 甲方应于收到发票后 30 天内付款。",
     "block_ids": ["b2"], "locators": ["p1@0,20"], "page": 1},
    {"chunk_id": "c3", "text": "第三条 服务费用为每月 45,000 泰铢，含税。",
     "block_ids": ["b3"], "locators": ["p1@0,40"], "page": 1},
    {"chunk_id": "c4", "text": "第四条 违约金为合同金额的 5%。",
     "block_ids": ["b4"], "locators": ["p1@0,60"], "page": 1},
    {"chunk_id": "c5", "text": "第五条 乙方每周提供一次服务报告。",
     "block_ids": ["b5"], "locators": ["p2@0,0"], "page": 2},
    {"chunk_id": "c6", "text": "第六条 争议提交清迈仲裁委员会处理。",
     "block_ids": ["b6"], "locators": ["p2@0,20"], "page": 2},
    {"chunk_id": "c7", "text": "第七条 保密义务在合同终止后持续两年。",
     "block_ids": ["b7"], "locators": ["p2@0,40"], "page": 2},
    {"chunk_id": "c8", "text": "第八条 本合同以泰文版本为准。",
     "block_ids": ["b8"], "locators": ["p2@0,60"], "page": 2},
]

# 15 个答得出来的：(问题, 该引用的块, 答案文本)
ANSWERABLE = [
    ("合同有效期多久", "c1", "有效期一年。"),
    ("合同什么时候生效", "c1", "自双方签字之日起生效。"),
    ("付款期限是多少天", "c2", "收到发票后 30 天内付款。"),
    ("付款起算点是什么", "c2", "从收到发票起算。"),
    ("每月服务费多少", "c3", "每月 45,000 泰铢。"),
    ("服务费含税吗", "c3", "含税。"),
    ("违约金比例是多少", "c4", "合同金额的 5%。"),
    ("违约金怎么算", "c4", "按合同金额的 5% 计算。"),
    ("服务报告多久一次", "c5", "每周一次。"),
    ("谁提供服务报告", "c5", "乙方提供。"),
    ("争议在哪里处理", "c6", "清迈仲裁委员会。"),
    ("仲裁机构是哪家", "c6", "清迈仲裁委员会。"),
    ("保密义务持续多久", "c7", "合同终止后持续两年。"),
    ("以哪个语言版本为准", "c8", "以泰文版本为准。"),
    ("合同有几种语言版本", "c8", "以泰文版本为准。"),
]

# 5 个**答案不在文档里**的 —— 这 5 题必须如实说「没有」
NOT_IN_DOCS = [
    "保修期是多久",
    "可以提前解约吗，违约金怎么算",
    "服务包含几个人天",
    "数据存储在哪个国家",
    "有没有服务等级协议（SLA）",
]


def hit_scores(cid: str) -> dict[str, float]:
    """构造「只有 cid 命中」的分数。"""
    return {c["chunk_id"]: (0.85 if c["chunk_id"] == cid else 0.08) for c in CHUNKS}


COLD_SCORES = {c["chunk_id"]: 0.12 for c in CHUNKS}   # 全部低于阈值


def test_all_twenty_questions_from_the_acceptance_criteria() -> None:
    """§4 验收标准：20 题全对，其中 5 题必须说「没有」。"""
    answered = 0
    for q, cid, text in ANSWERABLE:
        hits = InMemoryRetriever(CHUNKS, scores=hit_scores(cid)).search(q, k=5)
        try:
            a = answer(q, hits, {"found": True, "text": text, "citations": [cid]})
        except Exception as e:                               # noqa: BLE001
            FAILS.append("答得出来的问题被拒了：%r（%s）" % (q, e))
            continue
        if not a.found:
            FAILS.append("答得出来的问题被判成「没有」：%r" % q)
            continue
        if [c.chunk_id for c in a.citations] != [cid]:
            FAILS.append("%r 引用错了块：%r" % (q, [c.chunk_id for c in a.citations]))
            continue
        answered += 1
    check(answered == 15,
          "15 个答得出来的问题只答出 %d 个 —— "
          "一个永远说「没有」的实现在下面那半也是满分，所以这一半必须一起测" % answered)

    said_no = 0
    for q in NOT_IN_DOCS:
        hits = InMemoryRetriever(CHUNKS, scores=COLD_SCORES).search(q, k=5)
        a = answer(q, hits, {"found": False, "text": ""})
        if a.found or a.text != NOT_FOUND_ZH:
            FAILS.append("答案不在文档里的问题没有如实说「没有」：%r → %r" % (q, a.text))
            continue
        said_no += 1
    check(said_no == 5, "5 个「文档里没有」的问题只说对 %d 个" % said_no)


def test_the_five_missing_questions_reject_a_confident_answer() -> None:
    """那 5 题如果模型硬要答，必须被拒。

    **这是这个模块要挡的核心情形。** 客户问「保修期多久」，文档里恰好没有 ——
    模型答一个「通常是 1 年」，读起来专业、语气自信、格式完整，而它是编的。
    客户拿这个去做决定，损失是真的。
    """
    for q in NOT_IN_DOCS:
        hits = InMemoryRetriever(CHUNKS, scores=COLD_SCORES).search(q, k=5)
        expect_raises(FabricatedAnswerError,
                      lambda h=hits, qq=q: answer(
                          qq, h, {"found": True, "text": "通常是一年。",
                                  "citations": ["c1"]}),
                      "没命中却给出自信答案，没被拒：%r" % q)


# ══════════════════════════ 阈值：这类系统最常见的坏法

def test_retrieval_returning_something_is_not_a_hit() -> None:
    """**「检索返回了东西」不等于「检索到了答案」。**

    向量检索总会返回 top-k，哪怕全都不相关 —— 相似度 0.11 的块也是 top-1。
    不设阈值的话「没命中就说没有」形同虚设：永远有命中，
    于是永远不会说「没有」。而这个坏法表现为**回答率 100%**，
    看起来像是做得好。
    """
    weak = [RetrievedChunk("c1", "无关内容", 0.11, ("b1",), ("p1@0,0"))]
    check(not has_hit(weak), "0.11 分被当成了命中 —— 阈值形同虚设")
    check(has_hit([RetrievedChunk("c1", "x", MIN_SCORE, (), ())]),
          "恰好等于阈值应当算命中")
    check(not has_hit([]), "空检索被当成了命中")


def test_threshold_is_configurable_and_documented_as_unverified() -> None:
    """阈值可传入 —— 接上真实嵌入模型后要重新标定。

    `MIN_SCORE` 目前是 [待核] 的占位值，不是标定过的。
    这条测试确保它至少是个**可覆盖**的参数，而不是写死在判断里。
    """
    mid = [RetrievedChunk("c1", "内容", 0.5, ("b1",), ("p1@0,0"))]
    check(has_hit(mid, min_score=0.4), "阈值 0.4 时 0.5 分应当算命中")
    check(not has_hit(mid, min_score=0.6), "阈值 0.6 时 0.5 分不该算命中 —— 阈值参数没生效")


# ══════════════════════════ 「没有」这句话不让模型自由发挥

def test_not_found_wording_is_fixed() -> None:
    """让模型自己写「没找到」，它会写成
    「我没有找到明确信息，**不过通常来说……**」—— 后半句正是要挡的东西。
    """
    hits = InMemoryRetriever(CHUNKS, scores=COLD_SCORES).search("保修期", k=5)
    expect_raises(SearchRejected,
                  lambda: answer("保修期多久", hits,
                                 {"found": False,
                                  "text": "文档中没有明确说明，不过通常是一年。"}),
                  "「没找到，不过通常来说……」被放行了")

    # 正对照:标准措辞必须放行(三种语言)
    for t in NOT_FOUND_TEXTS:
        try:
            answer("保修期多久", hits, {"found": False, "text": t})
        except Exception as e:                               # noqa: BLE001
            FAILS.append("标准措辞 %r 被拒了（%s）" % (t, e))


def test_not_found_supports_three_languages() -> None:
    """客户可能用中英泰任一种问 —— 回「没有」也要用对应语言。"""
    langs = {lang: not_found_answer("q", lang).text for lang in ("zh", "en", "th")}
    check(len(set(langs.values())) == 3, "三种语言的「没有」不该是同一句：%r" % langs)
    for t in langs.values():
        check(t in NOT_FOUND_TEXTS, "%r 不在标准措辞集合里" % t)


# ══════════════════════════ 出处

def test_answer_without_citation_rejected() -> None:
    """没有出处的答案必须拒 —— **包括不含数字的答案。**

    第一版只测了带数字的答案（「5%。」），于是「摘掉出处强制」这条变异
    没被抓到:答案被**数字校验**接住了（数字追不到出处 → 同样抛异常，
    而 FabricatedAnswerError 是 SearchRejected 的子类，expect_raises 分不出来）。

    但那不只是断言松，是**真的覆盖漏洞**：实测摘掉出处强制后，
    一条不含数字的答案（「以泰文版本为准。」）**带着零条出处被放行了**。
    合同问答里不含数字的答案很常见 —— 期限、机构、语言、责任方。
    """
    # 不含数字的答案:这一条只有出处强制能挡
    hits8 = InMemoryRetriever(CHUNKS, scores=hit_scores("c8")).search("语言版本", k=5)
    expect_raises(SearchRejected,
                  lambda: answer("以哪个语言版本为准", hits8,
                                 {"found": True, "text": "以泰文版本为准。",
                                  "citations": []}),
                  "不含数字、且没有出处的答案被放行了 —— "
                  "合同问答里不含数字的答案很常见（期限、机构、语言、责任方）")

    # 带数字的答案也要拒（会被两道闸门中的某一道接住,两道都该在）
    hits4 = InMemoryRetriever(CHUNKS, scores=hit_scores("c4")).search("违约金", k=5)
    expect_raises(SearchRejected,
                  lambda: answer("违约金是多少", hits4,
                                 {"found": True, "text": "5%。", "citations": []}),
                  "带数字、没有出处的答案被放行了")


def test_fabricated_citation_rejected() -> None:
    """编出处比不给出处更危险 —— 它看起来是可核对的。"""
    hits = InMemoryRetriever(CHUNKS, scores=hit_scores("c4")).search("违约金", k=5)
    expect_raises(FabricatedAnswerError,
                  lambda: answer("违约金是多少", hits,
                                 {"found": True, "text": "5%。", "citations": ["c99"]}),
                  "引用了没被检索到的块，没被拒")


def test_citation_must_be_among_retrieved_not_merely_existing() -> None:
    """出处必须在**这次检索的结果**里，不是「文档里有这块就行」。

    否则模型可以引用一个它其实没看到的块 —— 答案和出处对不上，
    而人点开出处会看到一段确实存在的文字，更容易信。
    """
    hits = InMemoryRetriever(CHUNKS, scores=hit_scores("c4")).search("违约金", k=2)
    ids = {c.chunk_id for c in hits}
    outside = next(c["chunk_id"] for c in CHUNKS if c["chunk_id"] not in ids)
    expect_raises(FabricatedAnswerError,
                  lambda: answer("违约金是多少", hits,
                                 {"found": True, "text": "5%。", "citations": [outside]}),
                  "引用了本次检索之外的块（%s），没被拒" % outside)


# ══════════════════════════ 数字必须能追到出处

def test_fabricated_number_in_answer_rejected() -> None:
    """答案里的每个数字都必须出现在被引用的块里。

    数字是最容易被「顺手补完整」的东西，也是后果最重的 ——
    客户会直接拿它去做决定。
    """
    hits = InMemoryRetriever(CHUNKS, scores=hit_scores("c4")).search("违约金", k=5)
    expect_raises(FabricatedAnswerError,
                  lambda: answer("违约金是多少", hits,
                                 {"found": True,
                                  "text": "违约金为 5%，上限 100,000 泰铢。",
                                  "citations": ["c4"]}),
                  "答案里凭空多出的「100,000」没被拒")


def test_numbers_from_cited_chunk_pass() -> None:
    """正对照：出处里有的数字必须放行。

    否则「凡有数字就拒」也能让上面全绿 —— 而合同问答几乎每一句都有数字。
    """
    hits = InMemoryRetriever(CHUNKS, scores=hit_scores("c3")).search("服务费", k=5)
    try:
        a = answer("每月服务费多少", hits,
                   {"found": True, "text": "每月 45,000 泰铢，含税。",
                    "citations": ["c3"]})
        check(a.found, "正当答案没被认作 found")
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("出处里有的数字被判成编造（%s）—— 合同问答几乎每句都有数字" % e)


def test_thai_digits_counted_in_answer() -> None:
    """泰文数字一起数 —— 用泰数字编造的金额同样要挡住。"""
    check(numbers_in("๔๕,๐๐๐ บาท") == {"45000"}, "泰文数字没被识别")
    chunks = [{"chunk_id": "t1", "text": "ค่าบริการ ๔๕,๐๐๐ บาท",
               "block_ids": ["b1"], "locators": ["p1@0,0"], "page": 1}]
    hits = InMemoryRetriever(chunks, scores={"t1": 0.9}).search("ค่าบริการ", k=5)
    expect_raises(FabricatedAnswerError,
                  lambda: answer("ค่าบริการเท่าไร", hits,
                                 {"found": True,
                                  "text": "ค่าบริการ ๔๕,๐๐๐ บาท และค่ามัดจำ ๑๐,๐๐๐ บาท",
                                  "citations": ["t1"]}),
                  "用泰数字编造的押金没被拒")


def test_number_across_multiple_citations() -> None:
    """引用多块时，数字可以来自其中任意一块。

    否则跨条款的问题（「付款期限和违约金分别是多少」）就答不了。
    """
    scores = {c["chunk_id"]: (0.9 if c["chunk_id"] in ("c2", "c4") else 0.05)
              for c in CHUNKS}
    hits = InMemoryRetriever(CHUNKS, scores=scores).search("付款 违约金", k=5)
    try:
        answer("付款期限和违约金分别是多少", hits,
               {"found": True, "text": "付款 30 天内，违约金 5%。",
                "citations": ["c2", "c4"]})
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("跨块的数字被判成编造（%s）—— 跨条款的问题就答不了了" % e)


# ══════════════════════════ 模型说答不了也是允许的

def test_model_may_decline_even_when_retrieval_hit() -> None:
    """检索命中但模型说答不了 —— 允许，且要留痕。

    模型比阈值更懂「这块内容其实不回答这个问题」。
    直接拒绝的话，我们等于强迫它在命中时必须编一个答案。
    """
    hits = InMemoryRetriever(CHUNKS, scores=hit_scores("c1")).search("保修期", k=5)
    a = answer("保修期多久", hits, {"found": False, "text": ""})
    check(not a.found, "模型说答不了，结果却是 found")
    check(a.text == NOT_FOUND_ZH, "回答措辞不对：%r" % a.text)
    check(any("留痕" in n or "命中" in n for n in a.notes),
          "命中却答不了这件事没留痕 —— 它是标定阈值的依据：%r" % a.notes)


def test_empty_question_rejected() -> None:
    expect_raises(SearchRejected, lambda: answer("  ", [], {"found": False}),
                  "空问题没被拒")


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
    print("✓ search 测试全部通过（%d 个测试函数，含 §4 验收标准的 20 题）" % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
