#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract.py 与 thai_dates.py 的测试。

最要紧的三条：**schema 强制拒绝**、**citation 强制**、**不确定不猜**。

每条断言配负对照。跑法：python3 test_extract.py
"""

import sys

from docir import Block, DocIR, SourceInfo
from extract import (
    Citation,
    ExtractionRejected,
    FieldSpec,
    Schema,
    SchemaError,
    extract,
    parse_money,
    parse_number,
)
from thai_dates import BE_OFFSET, DateAmbiguous, resolve_or_raise, resolve_year

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
        "sha256:q", SourceInfo("quote.pdf", "application/pdf", 2),
        [Block("b1", "paragraph", 1, (10, 10, 400, 40), "ใบเสนอราคา Q-2026-014", ["th"]),
         Block("b2", "paragraph", 1, (10, 50, 400, 90), "วันที่ 12 มีนาคม พ.ศ. 2567", ["th"]),
         Block("b3", "paragraph", 2, (10, 10, 400, 50), "ยอดรวม 45,000 บาท", ["th"])])


SCHEMA = Schema([FieldSpec("quote_no", "string"),
                 FieldSpec("issue_year", "date"),
                 FieldSpec("total", "money")])

GOOD = [{"name": "quote_no", "raw": "Q-2026-014", "block_id": "b1"},
        {"name": "issue_year", "raw": "2567", "block_id": "b2"},
        {"name": "total", "raw": "45,000 บาท", "block_id": "b3"}]


# ══════════════════════════════════════ 泰历：不确定就不猜

def test_buddhist_era_conversion() -> None:
    check(resolve_year("2567").year_ce == 2024, "佛历 2567 → 公历 2024 算错")
    check(resolve_year("2567").era == "BE", "2567 应判为佛历")
    check(resolve_year("1450").era == "CE", "1450 应判为公历")
    check(BE_OFFSET == 543, "佛历偏移量应为 543")

    # 负对照:确定的年份**不该**被标成 ambiguous
    check(resolve_year("2567").is_certain, "负对照失败：确定的佛历被标成不确定")
    check(resolve_year("1450").is_certain, "负对照失败：确定的公历被标成不确定")


def test_ambiguous_year_is_not_guessed() -> None:
    """歧义区间必须标 ambiguous，**绝不猜**。

    2024 既可能是公历 2024，也可能是佛历 2024（= 公历 1481）。
    猜错 543 年，客户一眼看得出，然后不再相信这份文档里任何一个数字。
    """
    r = resolve_year("2024")
    check(r.era == "ambiguous", "2024 无上下文时应判 ambiguous，得到 %r" % r.era)
    check(r.year_ce is None, "ambiguous 时不该给出 year_ce，得到 %r" % r.year_ce)
    check("543" in r.evidence, "说明里应写明相差 543 年，得到 %r" % r.evidence)

    expect_raises(DateAmbiguous, lambda: resolve_or_raise("2024"),
                  "resolve_or_raise 对 ambiguous 没抛错 —— 会静默给出猜测值")

    # 有旁证时必须能判定 —— 否则「永远 ambiguous」也能让上面绿
    check(resolve_year("2024", "วันที่ 5 ค.ศ. 2024").era == "CE",
          "负对照失败：有公历标记时仍判 ambiguous")
    check(resolve_year("2024", "พ.ศ. 2024").year_ce == 1481,
          "负对照失败：有佛历标记时没换算")

    # 两种标记同时出现 → 仍然不猜
    both = resolve_year("2024", "พ.ศ. และ ค.ศ.")
    check(both.era == "ambiguous", "同时出现两种标记时应判 ambiguous")


def test_raw_always_preserved() -> None:
    check(resolve_year("ปี 2567").raw == "ปี 2567",
          "原文串没被保留 —— 出事时无法复盘模型给的是什么")
    expect_raises(ValueError, lambda: resolve_year("没有数字"),
                  "不含数字的年份没被拒")


# ══════════════════════════════════════ 币种：不猜

def test_currency_never_guessed() -> None:
    check(parse_money("45,000 บาท") == {"amount": 45000.0, "currency": "THB"},
          "泰铢没被识别")
    check(parse_money("$1,200.50") == {"amount": 1200.5, "currency": "USD"},
          "美元没被识别")
    expect_raises(ExtractionRejected, lambda: parse_money("45,000"),
                  "无币种标记的金额没被拒 —— 泰铢当成美元差约 30 倍")


def test_number_parsing() -> None:
    check(parse_number("1,234.5") == 1234.5, "千分位数字解析错")
    check(parse_number("总计 -42 件") == -42.0, "负数解析错")
    expect_raises(ExtractionRejected, lambda: parse_number("没有数字"),
                  "不含数字的值没被拒")


# ══════════════════════════════════════ schema 强制

def test_extra_field_rejected() -> None:
    """多出的字段一律拒绝 —— 不是「忽略就好」。"""
    expect_raises(ExtractionRejected,
                  lambda: extract(ir(), SCHEMA,
                                  GOOD + [{"name": "hallucinated", "raw": "x", "block_id": "b1"}]),
                  "多出字段没被拒 —— 多字段是模型开始自由发挥的第一个信号")

    # 负对照:恰好符合 schema 的必须通过
    try:
        extract(ir(), SCHEMA, GOOD)
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：合法输出被拒（%s）" % e)


def test_missing_required_rejected() -> None:
    """必填缺失拒绝整份，不做部分交付。"""
    expect_raises(ExtractionRejected, lambda: extract(ir(), SCHEMA, GOOD[:2]),
                  "缺必填字段没被拒 —— 半个结果比没有结果更危险")

    # 负对照:非必填缺失应放行
    s = Schema([FieldSpec("quote_no", "string"),
                FieldSpec("memo", "string", required=False)])
    try:
        r = extract(ir(), s, [GOOD[0]])
        check(len(r.fields) == 1, "非必填缺失时字段数不对")
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：非必填缺失被拒（%s）" % e)


def test_duplicate_field_rejected() -> None:
    expect_raises(ExtractionRejected,
                  lambda: extract(ir(), SCHEMA, GOOD + [GOOD[0]]),
                  "同一字段被抽两次没被拒")


def test_schema_validation() -> None:
    expect_raises(SchemaError, lambda: Schema([]).validate(), "空 schema 没被拒")
    expect_raises(SchemaError,
                  lambda: Schema([FieldSpec("a", "weird")]).validate(),
                  "未知字段类型没被拒")
    expect_raises(SchemaError,
                  lambda: Schema([FieldSpec("a", "string"), FieldSpec("a", "number")]).validate(),
                  "重复字段名没被拒")
    expect_raises(SchemaError, lambda: Schema([FieldSpec("", "string")]).validate(),
                  "空字段名没被拒")


def test_model_output_shape_validated() -> None:
    for missing in ("name", "raw", "block_id"):
        bad = [dict(GOOD[0])]
        del bad[0][missing]
        expect_raises(ExtractionRejected,
                      lambda b=bad: extract(ir(), SCHEMA, b + GOOD[1:]),
                      "模型输出缺 %r 没被拒" % missing)


# ══════════════════════════════════════ citation 强制

def test_citation_required_and_valid() -> None:
    """引用的 block 必须真的在文档里 —— 否则客户点不回原文。"""
    bad = GOOD[:2] + [{"name": "total", "raw": "1 บาท", "block_id": "不存在"}]
    expect_raises(ExtractionRejected, lambda: extract(ir(), SCHEMA, bad),
                  "引用不存在的 block 没被拒")

    r = extract(ir(), SCHEMA, GOOD)
    for f in r.fields:
        check(isinstance(f.citation, Citation), "字段缺 citation")
        check(f.citation.doc_id == "sha256:q", "citation 的 doc_id 错")
        check(f.citation.locator.startswith("p"), "locator 格式错：%r" % f.citation.locator)
    by = {f.name: f for f in r.fields}
    check(by["total"].citation.page == 2,
          "citation 页码错：total 在第 2 页，得到 %r" % by["total"].citation.page)


# ══════════════════════════════════════ 不确定要被看见

def test_uncertain_surfaces_to_human() -> None:
    out = [GOOD[0], {"name": "issue_year", "raw": "2024", "block_id": "b1"}, GOOD[2]]
    r = extract(ir(), SCHEMA, out)
    check(r.needs_human, "有歧义字段时 needs_human 应为真")
    check("issue_year" in r.uncertain, "歧义字段没进 uncertain 列表")
    by = {f.name: f for f in r.fields}
    check(not by["issue_year"].certain, "歧义字段没标 certain=False")
    check(by["issue_year"].value is None, "歧义字段不该有值 —— 那是猜的")
    check("543" in by["issue_year"].note, "歧义字段的 note 没说明原因")

    # 负对照:全确定时不该要人看 —— 否则「永远要人看」也能让上面绿
    check(not extract(ir(), SCHEMA, GOOD).needs_human,
          "负对照失败：全部确定时仍标记 needs_human")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    for t in TESTS:
        t()
    if FAILS:
        print("✗ %d 个测试断言失败" % len(FAILS), file=sys.stderr)
        for f in FAILS:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ extract 测试全部通过（%d 个测试函数，含「不确定不猜」的负对照）"
          % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
