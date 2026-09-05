#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""泰历（佛历）与公历的判定与换算。

设计见 docs/business/starter-kit/documents.md §4 的 `extract` 一节：

> **坑**：数字与日期最容易错 —— 泰历（佛历）年份比公历多 543 年，
> 客户文档里两种都有。**对策**：日期字段强制要求模型同时输出原文串与解析值，
> 由我们的代码判断历法并转换，**不让模型自己算**。

## 为什么不让模型算

模型算术不可靠，而且**错了不会报错** —— 它会自信地给出 2024 而不是 2567。
一份报价单上的日期错 543 年，客户第一眼就会发现，然后不再相信这份文档里的
任何一个数字。

这个模块把「判定历法」变成**确定性规则 + 明确的不确定标记**：
能确定就换算，不能确定就**如实说不确定**，而不是猜一个。

## 判定规则（按优先级）

1. 年份 ≥ 2400 → 一定是佛历（公历 2400 年还没到）
2. 年份 ≤ 1500 → 一定是公历（佛历 1500 年 = 公历 957，文档里不会出现）
3. 1500 < 年份 < 2400 → **有歧义**，需要旁证：
   a. 文档里有明确的泰历标记（พ.ศ. / พศ / B.E.）→ 佛历
   b. 有明确的公历标记（ค.ศ. / คศ / A.D. / C.E.）→ 公历
   c. 都没有 → **标为 ambiguous，不猜**

    python3 thai_dates.py --self-test
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

BE_OFFSET = 543          # 佛历 - 公历

# 佛历标记。พ.ศ. 是最常见的写法，也有省略点号的。
_BE_MARK = re.compile(r"พ\.?\s?ศ\.?|B\.?\s?E\.?", re.IGNORECASE)
# 公历标记
_CE_MARK = re.compile(r"ค\.?\s?ศ\.?|A\.?\s?D\.?|C\.?\s?E\.?", re.IGNORECASE)

# 上下界。低于此一定是公历，高于此一定是佛历。
_CERTAIN_BE_FROM = 2400   # 公历 2400 年还没到
_CERTAIN_CE_TO = 1500     # 佛历 1500 = 公历 957，文档里不会出现


class DateAmbiguous(ValueError):
    """无法确定历法。**这是一个合法结论，不是失败。**

    调用方必须显式处理：要么带着 ambiguous 标记交给人确认，
    要么拒绝这个字段。**绝不许默默猜一个。**
    """


@dataclass(frozen=True)
class YearResolution:
    raw: str                 # 原文串，永远保留
    year_ce: int | None      # 换算后的公历年；ambiguous 时为 None
    era: str                 # "BE" / "CE" / "ambiguous"
    evidence: str            # 为什么这么判 —— 出事时要能复盘

    @property
    def is_certain(self) -> bool:
        return self.era in ("BE", "CE")


def resolve_year(raw_year: str, context: str = "") -> YearResolution:
    """判定一个年份是佛历还是公历，并换算成公历。

    `raw_year`：模型抽出来的原文串（如 "2567"）
    `context`：该字段周边的原文，用来找 พ.ศ. / ค.ศ. 标记

    **不确定就返回 era="ambiguous"，绝不猜。**
    """
    m = re.search(r"\d{3,4}", raw_year)
    if not m:
        raise ValueError("年份里找不到数字：%r" % raw_year)
    y = int(m.group())

    if y >= _CERTAIN_BE_FROM:
        return YearResolution(raw_year, y - BE_OFFSET, "BE",
                              "年份 %d ≥ %d，公历还没到这一年，必为佛历"
                              % (y, _CERTAIN_BE_FROM))
    if y <= _CERTAIN_CE_TO:
        return YearResolution(raw_year, y, "CE",
                              "年份 %d ≤ %d，佛历不会这么小，必为公历"
                              % (y, _CERTAIN_CE_TO))

    # 歧义区间：找旁证
    probe = "%s %s" % (context, raw_year)
    has_be, has_ce = bool(_BE_MARK.search(probe)), bool(_CE_MARK.search(probe))
    if has_be and not has_ce:
        return YearResolution(raw_year, y - BE_OFFSET, "BE", "上下文出现佛历标记（พ.ศ./B.E.）")
    if has_ce and not has_be:
        return YearResolution(raw_year, y, "CE", "上下文出现公历标记（ค.ศ./A.D.）")
    if has_be and has_ce:
        return YearResolution(raw_year, None, "ambiguous",
                              "上下文同时出现佛历与公历标记，无法判定")
    return YearResolution(
        raw_year, None, "ambiguous",
        "年份 %d 落在 %d..%d 的歧义区间，且上下文无历法标记 —— "
        "佛历读作 %d，公历读作 %d，相差 %d 年"
        % (y, _CERTAIN_CE_TO + 1, _CERTAIN_BE_FROM - 1, y - BE_OFFSET, y, BE_OFFSET))


def resolve_or_raise(raw_year: str, context: str = "") -> int:
    """要么给出确定的公历年，要么抛错。给「不接受不确定」的调用方用。"""
    r = resolve_year(raw_year, context)
    if r.year_ce is None:
        raise DateAmbiguous(r.evidence)
    return r.year_ce


# ---------------------------------------------------------------- 自检

def self_test() -> int:
    fails: list[str] = []

    def eq(got: YearResolution, era: str, ce: int | None, label: str) -> None:
        if got.era != era or got.year_ce != ce:
            fails.append("%s：期望 era=%s year_ce=%s，得到 era=%s year_ce=%s（%s）"
                         % (label, era, ce, got.era, got.year_ce, got.evidence))

    eq(resolve_year("2567"), "BE", 2024, "佛历 2567")
    eq(resolve_year("2568"), "BE", 2025, "佛历 2568")
    eq(resolve_year("1450"), "CE", 1450, "公历 1450")
    eq(resolve_year("2024", "วันที่ 5 ค.ศ. 2024"), "CE", 2024, "带公历标记")
    eq(resolve_year("2024", "พ.ศ. 2024"), "BE", 1481, "带佛历标记")

    amb = resolve_year("2024")
    if amb.era != "ambiguous" or amb.year_ce is not None:
        fails.append("2024 无上下文时应判为 ambiguous，得到 %r" % (amb,))
    if "543" not in amb.evidence:
        fails.append("ambiguous 的说明里应写明相差 543 年")

    try:
        resolve_or_raise("2024")
        fails.append("resolve_or_raise 对 ambiguous 没有抛错")
    except DateAmbiguous:
        pass

    if resolve_or_raise("2567") != 2024:
        fails.append("resolve_or_raise 对确定值算错")

    # 原文串必须永远保留
    if resolve_year("ปี 2567").raw != "ปี 2567":
        fails.append("原文串没被保留 —— 出事时无法复盘")

    if fails:
        print("✗ thai_dates 自检失败", file=sys.stderr)
        for f in fails:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ thai_dates 自检通过（佛历/公历判定 · 歧义不猜 · 原文保留）")
    return 0


if __name__ == "__main__":
    sys.exit(self_test())
