#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris Documents — extract 动作：结构化抽取。

设计见 docs/business/starter-kit/documents.md §4 的 extract 一节。
它是六个动作里**先做的两个之一**（另一个是 translate）——
演示效果最直接、技术风险最低。

## 三条硬要求

1. **strict schema。** 模型只填字段，不自由发挥。字段缺失、多出、类型不对
   一律拒绝 —— 而不是「尽量解析」。半个结果比没有结果更危险，
   因为客户会拿它去做事。

2. **每个字段必须带 citation。** `doc_id` + `page` + `bbox`，
   让客户能点回原文核对。**没有出处的抽取结果没人敢用。**

3. **日期与数字不让模型算。** 模型输出原文串，由**我们的代码**判定历法、
   解析数值。见 thai_dates.py：泰历比公历多 543 年，模型算错了不会报错，
   它会自信地给出错的那个。

## 模型在这里做什么、不做什么

**做**：从文档里找出字段对应的原文片段，并指出它在哪个 block。
**不做**：格式化、单位换算、历法换算、算术。

这条分工不是洁癖 —— 它把「不可靠但擅长找」和「可靠但不会找」各自放在
对的位置上。

    python3 extract.py --self-test
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from docir import DocIR, Block
from thai_dates import YearResolution, resolve_year

FIELD_TYPES = ("string", "number", "date", "money")


class SchemaError(ValueError):
    """schema 本身有问题 —— 启动时炸，不要等到第一份客户文档。"""


class ExtractionRejected(ValueError):
    """模型的输出不符合 schema。**拒绝，不要「尽量解析」。**"""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    required: bool = True
    description: str = ""

    def validate(self) -> None:
        if not self.name:
            raise SchemaError("字段缺 name")
        if self.type not in FIELD_TYPES:
            raise SchemaError("字段 %r 的 type %r 非法（可用：%s）"
                              % (self.name, self.type, ", ".join(FIELD_TYPES)))


@dataclass
class Schema:
    fields: list[FieldSpec]

    def validate(self) -> None:
        if not self.fields:
            raise SchemaError("schema 不能为空")
        seen: set[str] = set()
        for f in self.fields:
            f.validate()
            if f.name in seen:
                raise SchemaError("字段名重复：%r" % f.name)
            seen.add(f.name)

    def by_name(self, name: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.name == name), None)


@dataclass(frozen=True)
class Citation:
    doc_id: str
    block_id: str
    page: int
    locator: str

    def as_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "block_id": self.block_id,
                "page": self.page, "locator": self.locator}


@dataclass
class ExtractedField:
    name: str
    raw: str                       # 模型给的原文串 —— 永远保留
    value: Any                     # 我们解析出来的值
    citation: Citation
    note: str = ""                 # 不确定时的说明（如历法歧义）
    certain: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "raw": self.raw, "value": self.value,
                "citation": self.citation.as_dict(),
                "certain": self.certain, "note": self.note}


# ── 值解析：全部由我们的代码做，不让模型算 ──────────────────────────

_NUM_RE = re.compile(r"-?[\d,]+(?:\.\d+)?")
_CURRENCY = {"THB": ("บาท", "฿", "thb", "baht"), "USD": ("$", "usd", "dollar")}


def parse_number(raw: str) -> float:
    m = _NUM_RE.search(raw)
    if not m:
        raise ExtractionRejected("字段值里找不到数字：%r" % raw)
    return float(m.group().replace(",", ""))


def parse_money(raw: str) -> dict[str, Any]:
    amount = parse_number(raw)
    low = raw.lower()
    currency = next((c for c, marks in _CURRENCY.items()
                     if any(mk in low for mk in marks)), None)
    if currency is None:
        # 不猜币种。一份泰铢报价被当成美元，差 30 倍。
        raise ExtractionRejected(
            "金额 %r 没有可识别的币种标记 —— 不猜。"
            "泰铢当成美元差约 30 倍，这种错客户一眼看得出" % raw)
    return {"amount": amount, "currency": currency}


def parse_date_year(raw: str, context: str) -> YearResolution:
    return resolve_year(raw, context)


PARSERS: dict[str, Callable[..., Any]] = {
    "string": lambda raw, ctx: raw.strip(),
    "number": lambda raw, ctx: parse_number(raw),
    "money": lambda raw, ctx: parse_money(raw),
    "date": lambda raw, ctx: parse_date_year(raw, ctx),
}


@dataclass
class ExtractResult:
    doc_id: str
    fields: list[ExtractedField] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)

    @property
    def needs_human(self) -> bool:
        """有任何不确定的字段就要人看。**不确定不是失败，是必须被看见。**"""
        return bool(self.uncertain)

    def as_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id,
                "fields": [f.as_dict() for f in self.fields],
                "uncertain": list(self.uncertain),
                "needs_human": self.needs_human}


def extract(ir: DocIR, schema: Schema,
            model_output: list[dict[str, str]]) -> ExtractResult:
    """把模型的输出变成经过校验的结构化结果。

    `model_output` 是模型给的原始条目，每条形如：
        {"name": "total", "raw": "45,000 บาท", "block_id": "b3"}

    **模型只给 name / raw / block_id 三样。** 值的解析、历法判定、
    币种识别全部在这里做 —— 见模块 docstring 的分工说明。
    """
    schema.validate()
    ir.validate()
    blocks: dict[str, Block] = {b.id: b for b in ir.blocks}

    seen: set[str] = set()
    result = ExtractResult(doc_id=ir.doc_id)

    for item in model_output:
        for k in ("name", "raw", "block_id"):
            if k not in item:
                raise ExtractionRejected("模型输出缺 %r：%r" % (k, item))
        name, raw, bid = item["name"], item["raw"], item["block_id"]

        spec = schema.by_name(name)
        if spec is None:
            # 多出的字段一律拒绝 —— 不是「忽略就好」。
            # 模型开始自由发挥时，第一个信号就是多字段。
            raise ExtractionRejected(
                "模型输出了 schema 里没有的字段 %r —— 拒绝整份结果。"
                "多字段是模型开始自由发挥的第一个信号" % name)
        if name in seen:
            raise ExtractionRejected("字段 %r 被抽了两次" % name)
        seen.add(name)

        # citation 是硬要求
        blk = blocks.get(bid)
        if blk is None:
            raise ExtractionRejected(
                "字段 %r 引用的 block %r 不在文档里 —— 出处对不上，"
                "客户点不回原文" % (name, bid))
        cite = Citation(ir.doc_id, blk.id, blk.page, blk.locator())

        parsed = PARSERS[spec.type](raw, blk.text)
        note, certain = "", True
        if spec.type == "date":
            assert isinstance(parsed, YearResolution)
            note, certain = parsed.evidence, parsed.is_certain
            if not certain:
                result.uncertain.append(name)
            parsed = parsed.year_ce

        result.fields.append(ExtractedField(
            name=name, raw=raw, value=parsed, citation=cite,
            note=note, certain=certain))

    missing = [f.name for f in schema.fields
               if f.required and f.name not in seen]
    if missing:
        raise ExtractionRejected(
            "必填字段缺失：%s —— 拒绝整份结果，不做部分交付。"
            "半个结果比没有结果更危险，客户会拿它去做事" % ", ".join(missing))

    return result


# ---------------------------------------------------------------- 自检

def _ir() -> DocIR:
    from docir import SourceInfo
    return DocIR.from_blocks(
        "sha256:q", SourceInfo("quote.pdf", "application/pdf", 2),
        [Block("b1", "paragraph", 1, (10, 10, 400, 40),
               "ใบเสนอราคา เลขที่ Q-2026-014", ["th"]),
         Block("b2", "paragraph", 1, (10, 50, 400, 90),
               "วันที่ 12 มีนาคม พ.ศ. 2567", ["th"]),
         Block("b3", "paragraph", 2, (10, 10, 400, 50),
               "ยอดรวมทั้งสิ้น 45,000 บาท", ["th"])])


_SCHEMA = Schema([
    FieldSpec("quote_no", "string"),
    FieldSpec("issue_year", "date"),
    FieldSpec("total", "money"),
])

_GOOD = [
    {"name": "quote_no", "raw": "Q-2026-014", "block_id": "b1"},
    {"name": "issue_year", "raw": "2567", "block_id": "b2"},
    {"name": "total", "raw": "45,000 บาท", "block_id": "b3"},
]


def self_test() -> int:
    fails: list[str] = []
    r = extract(_ir(), _SCHEMA, _GOOD)

    by = {f.name: f for f in r.fields}
    if by["issue_year"].value != 2024:
        fails.append("佛历 2567 应换算成公历 2024，得到 %r" % by["issue_year"].value)
    if by["total"].value != {"amount": 45000.0, "currency": "THB"}:
        fails.append("金额解析错：%r" % by["total"].value)
    if by["quote_no"].citation.page != 1:
        fails.append("citation 页码错")
    if r.needs_human:
        fails.append("全部确定时不该要人看")
    if any(not f.raw for f in r.fields):
        fails.append("有字段丢了原文串")

    for label, out in (
        ("多出字段", _GOOD + [{"name": "extra", "raw": "x", "block_id": "b1"}]),
        ("缺必填", _GOOD[:2]),
        ("block 不存在", _GOOD[:2] + [{"name": "total", "raw": "1 บาท", "block_id": "zz"}]),
        ("金额无币种", _GOOD[:2] + [{"name": "total", "raw": "45,000", "block_id": "b3"}]),
    ):
        try:
            extract(_ir(), _SCHEMA, out)
            fails.append("应拒绝但通过了：%s" % label)
        except ExtractionRejected:
            pass

    # 歧义年份要被标出来，而不是猜
    amb = extract(_ir(), _SCHEMA,
                  [_GOOD[0], {"name": "issue_year", "raw": "2024", "block_id": "b1"}, _GOOD[2]])
    if not amb.needs_human or "issue_year" not in amb.uncertain:
        fails.append("歧义年份没被标成需要人看")

    if fails:
        print("✗ extract 自检失败", file=sys.stderr)
        for f in fails:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ extract 自检通过（schema 强制 · citation 强制 · 历法与币种由代码解析）")
    return 0


if __name__ == "__main__":
    sys.exit(self_test())
