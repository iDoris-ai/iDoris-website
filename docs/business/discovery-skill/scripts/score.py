#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris Discovery — 评分与排序。

两件事:
  1. AI Readiness 五维评分 → 总分 → 建议起步档次
  2. 候选用例的 Impact x Effort x Risk → 优先级排序

为什么排序公式里 Risk 的权重高于 Effort:
    优先级 = Impact x 2 - Effort - Risk x 1.5
做慢了只是慢,做错了会失去客户。一个高价值但会伤到客户的用例,
排在低价值安全用例后面是对的。

用法:
    score.py readiness data.json      五维评分
    score.py usecases data.json       用例排序
    score.py --self-test              自检(CI 用)

输入格式见 --self-test 里的样例,或 templates/ 下的模板。
"""

import json
import sys

# ---------------------------------------------------------------- Readiness

DIMENSIONS = [
    ("data", "数据可得性"),
    ("process", "流程标准化"),
    ("tooling", "工具基础"),
    ("willingness", "人员意愿"),
    ("governance", "治理准备"),
]


def readiness(scores):
    """五维各 1-5 分 → 总分与建议。"""
    missing = [k for k, _ in DIMENSIONS if k not in scores]
    if missing:
        raise ValueError("缺少维度: %s" % ", ".join(missing))
    for k, label in DIMENSIONS:
        v = scores[k]
        if not isinstance(v, int) or not 1 <= v <= 5:
            raise ValueError("%s(%s) 必须是 1-5 的整数,得到 %r" % (label, k, v))

    total = sum(scores[k] for k, _ in DIMENSIONS)

    # 分档判据见 discovery-sop.md §6.1。「建议别做」是合法结论。
    if total <= 10:
        tier = "不建议现在做 Implementation"
        advice = ("先做 Enablement,或直接建议客户暂缓。照实写进交付物 —— "
                  "这是可信度的来源,不是失败。")
    elif total <= 17:
        tier = "从 L1 Skill Pack 起步"
        advice = "先用可复用 Skill 见效,不要一上来做集成。"
    else:
        tier = "可以考虑 L2 Agent / L3 集成"
        advice = "基础具备,但仍建议第一个用例选一周内能见效的。"

    weakest = min(DIMENSIONS, key=lambda d: scores[d[0]])
    return {
        "total": total,
        "max": 25,
        "tier": tier,
        "advice": advice,
        "weakest": {"key": weakest[0], "label": weakest[1], "score": scores[weakest[0]]},
        "detail": [{"key": k, "label": lab, "score": scores[k]} for k, lab in DIMENSIONS],
    }


# ---------------------------------------------------------------- Use cases

def priority(impact, effort, risk):
    """优先级得分。Risk 权重 1.5 > Effort 权重 1 —— 做错比做慢贵。"""
    return impact * 2 - effort - risk * 1.5


def rank(cases):
    """候选用例排序。每个 case 需要 name / impact / effort / risk。"""
    if not cases:
        raise ValueError("用例列表为空")
    out = []
    for c in cases:
        for f in ("name", "impact", "effort", "risk"):
            if f not in c:
                raise ValueError("用例 %r 缺少字段 %s" % (c.get("name", "?"), f))
        for f in ("impact", "effort", "risk"):
            v = c[f]
            if not isinstance(v, int) or not 1 <= v <= 5:
                raise ValueError("%s 的 %s 必须是 1-5 的整数,得到 %r" % (c["name"], f, v))
        out.append(dict(c, score=round(priority(c["impact"], c["effort"], c["risk"]), 2)))

    out.sort(key=lambda c: c["score"], reverse=True)

    # Top 3 的挑法不是取分数最高的三个 —— 见 SKILL.md ④。
    # 脚本只给排序,挑选由人做,但把节奏提示打出来。
    quick = [c for c in out if c["effort"] <= 2]
    note = ("提示:第 1 个用例应挑「一周内能见效」的(Effort ≤ 2),用来建立信心,"
            "哪怕它不是分数最高的。当前 Effort ≤ 2 的候选:%s"
            % (", ".join(c["name"] for c in quick) if quick else "无 —— "
               "全部候选都要 1 周以上,建议重新拆出一个更小的切口"))
    return {"ranked": out, "pacing_note": note}


# ---------------------------------------------------------------- Self-test

_R_SAMPLE = {"data": 2, "process": 2, "tooling": 3, "willingness": 4, "governance": 1}
_U_SAMPLE = [
    {"name": "报价单起草", "impact": 4, "effort": 2, "risk": 2},
    {"name": "LINE 客户问答", "impact": 5, "effort": 4, "risk": 4},
    {"name": "会议纪要", "impact": 3, "effort": 1, "risk": 1},
]


def self_test():
    """断言判据真的会分辨 —— 一个永远给同样答案的评分器等于没有评分器。"""
    fails = []

    r = readiness(_R_SAMPLE)
    if r["total"] != 12:
        fails.append("readiness 总分算错:期望 12,得到 %s" % r["total"])
    if "L1" not in r["tier"]:
        fails.append("12 分应落在 L1 档,得到 %r" % r["tier"])
    if r["weakest"]["key"] != "governance":
        fails.append("最弱维度应为 governance,得到 %s" % r["weakest"]["key"])

    # 分档边界:10 与 11 必须给出不同结论,否则这条判据是死的
    lo = readiness({k: 2 for k, _ in DIMENSIONS})            # 10
    hi = readiness(dict({k: 2 for k, _ in DIMENSIONS}, data=3))  # 11
    if lo["tier"] == hi["tier"]:
        fails.append("10 分与 11 分给了同样的结论 —— 分档判据是死的")
    if "不建议" not in lo["tier"]:
        fails.append("10 分应给出「不建议现在做」,得到 %r" % lo["tier"])

    k = rank(_U_SAMPLE)
    order = [c["name"] for c in k["ranked"]]
    # 会议纪要 3*2-1-1.5=3.5 · 报价单 4*2-2-3=3 · LINE 5*2-4-6=0
    if order[0] != "会议纪要":
        fails.append("排序错:低风险低成本的会议纪要应排第一,得到 %s" % order[0])
    if order[-1] != "LINE 客户问答":
        fails.append("排序错:高风险的 LINE 应排最后,得到 %s" % order[-1])

    # Risk 权重必须真的高于 Effort,否则那句注释是谎话
    a = priority(3, 4, 1)   # 高 effort
    b = priority(3, 1, 4)   # 高 risk
    if not b < a:
        fails.append("Risk 权重没有高于 Effort —— 公式与文档不符")

    # 输入校验必须真的拦得住
    for bad, why in (
        ({"data": 2}, "缺维度"),
        (dict(_R_SAMPLE, data=6), "超出 1-5"),
        (dict(_R_SAMPLE, data="3"), "非整数"),
    ):
        try:
            readiness(bad)
            fails.append("输入校验没拦住:%s" % why)
        except ValueError:
            pass
    try:
        rank([])
        fails.append("输入校验没拦住:空用例列表")
    except ValueError:
        pass

    if fails:
        print("✗ 自检失败 —— 评分器坏了,它的输出不能信", file=sys.stderr)
        for f in fails:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ score.py 自检通过（分档边界、排序权重、输入校验都验证过会分辨）")
    return 0


# ---------------------------------------------------------------- CLI

def main(argv):
    if "--self-test" in argv:
        return self_test()
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2

    mode, path = argv[1], argv[2]
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    try:
        if mode == "readiness":
            result = readiness(data)
        elif mode == "usecases":
            result = rank(data)
        else:
            print("未知模式:%s（可用:readiness / usecases）" % mode, file=sys.stderr)
            return 2
    except ValueError as exc:
        print("✗ 输入有问题:%s" % exc, file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
