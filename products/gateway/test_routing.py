#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""routing.py 的测试。

**每条「不可破规则」都配一个负对照** —— 证明规则真的在拦，
而不是碰巧测试用例都没触发它。

这条纪律来自本仓库 2026-09-05 的教训：所有检查全绿，但结论集体错了。
一个永远绿的测试，看起来和真测试一模一样。

跑法：python3 test_routing.py
"""

import sys

from routing import (
    Budget,
    BudgetExceeded,
    Policy,
    PolicyError,
    RoutingEngine,
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
        FAILS.append("%s（抛的是 %s 而不是 %s）" % (msg, type(e).__name__, exc.__name__))
        return
    FAILS.append(msg)


def base_policy(**kw) -> Policy:
    p = Policy(
        tenant="t",
        rules=[
            {"task": "translate", "tier": "cheap"},
            {"task": "summarize", "tier": "mid"},
            {"task": "compare", "tier": "premium"},
        ],
        tiers={
            "local": {"models": ["local-a"]},
            "cheap": {"models": ["cheap-a"]},
            "mid": {"models": ["mid-a"]},
            "premium": {"models": ["premium-a"]},
        },
    )
    for k, v in kw.items():
        setattr(p, k, v)
    return p


# ══════════════════════════════════════════════════════════ 规则 1:隐私

def test_sensitivity_override() -> None:
    """sensitivity=high 必须走 local，无论任务类型。"""
    eng = RoutingEngine(base_policy())

    # 正向:每一个已配置的任务，标 high 之后都必须落到 local
    for task in ("translate", "summarize", "compare", "从未见过的任务"):
        d = eng.route(task, sensitivity="high")
        check(d.tier == "local",
              "规则1 破了：task=%r sensitivity=high 走了 %s 而不是 local" % (task, d.tier))
        check(d.overridden, "规则1：task=%r 的决策没有标记 overridden" % task)

    # 负对照 A:同样的任务，normal 时**不该**走 local ——
    # 否则「都走 local」也能让上面全绿，这个测试就是瞎的
    d = eng.route("compare", sensitivity="normal")
    check(d.tier == "premium",
          "负对照失败：normal 的 compare 也走了 %s。"
          "如果什么都走 local，规则1 的测试就证明不了任何事" % d.tier)
    check(not d.overridden, "负对照失败：normal 请求不该标 overridden")

    # 负对照 B:即使路由表里显式给某任务配了 premium，high 也必须压过它
    p = base_policy(rules=[{"task": "secret", "tier": "premium"}])
    d = RoutingEngine(p).route("secret", sensitivity="high")
    check(d.tier == "local",
          "规则1 破了：显式配置的 premium 压过了 sensitivity=high —— "
          "敏感数据会被发到云端")


def test_sensitivity_input_validation() -> None:
    eng = RoutingEngine(base_policy())
    expect_raises(ValueError, lambda: eng.route("translate", sensitivity="HIGH"),
                  "大小写不同的 sensitivity 没被拒绝 —— 会静默当成 normal 放行")
    expect_raises(ValueError, lambda: eng.route("translate", sensitivity="secret"),
                  "未知 sensitivity 没被拒绝")
    expect_raises(ValueError, lambda: eng.route("translate", sensitivity=""),
                  "空 sensitivity 没被拒绝")


# ══════════════════════════════════════════════════════════ 规则 2:预算

def test_budget_hard_stop() -> None:
    """预算用尽必须拒绝，不是降级后继续跑。"""
    eng = RoutingEngine(base_policy(), Budget(limit_usd=100, spent_usd=100))
    expect_raises(BudgetExceeded, lambda: eng.route("translate"),
                  "规则2 破了：预算用尽仍然放行")

    # 超支更多也一样
    eng = RoutingEngine(base_policy(), Budget(limit_usd=100, spent_usd=250))
    expect_raises(BudgetExceeded, lambda: eng.route("translate"),
                  "规则2 破了：超支 2.5 倍仍然放行")

    # 硬停压过隐私 override —— 因为「跑」这个动作本身就要花钱
    eng = RoutingEngine(base_policy(), Budget(limit_usd=100, spent_usd=100))
    expect_raises(BudgetExceeded,
                  lambda: eng.route("translate", sensitivity="high"),
                  "预算用尽时 sensitivity=high 绕过了硬停")

    # 负对照:没超预算时**必须**放行 —— 否则「永远拒绝」也能让上面全绿
    eng = RoutingEngine(base_policy(), Budget(limit_usd=100, spent_usd=10))
    d = eng.route("translate")
    check(d.tier == "cheap",
          "负对照失败：预算充足(10%%)时竟然没正常路由，得到 %r" % d.tier)


def test_budget_degrade() -> None:
    """90% 时 premium 降级到 cheap，但其余档不动。"""
    eng = RoutingEngine(base_policy(), Budget(limit_usd=100, spent_usd=95))

    d = eng.route("compare")           # 本该 premium
    check(d.tier == "cheap" and d.degraded,
          "90%% 时 premium 未降级，得到 %r" % d.tier)

    # 负对照:同样在 90%，mid 不该被动 ——
    # 否则「全都降到 cheap」也能让上面绿
    d = eng.route("summarize")
    check(d.tier == "mid" and not d.degraded,
          "负对照失败：90%% 时 mid 也被降级了（得到 %r）。"
          "降级只该作用于 premium" % d.tier)


def test_budget_boundaries() -> None:
    """边界值必须给出不同结论，否则分档判据是死的。"""
    P = base_policy()
    states = {
        69.9: "ok", 70.0: "warning",
        89.9: "warning", 90.0: "degraded",
        99.9: "degraded", 100.0: "blocked",
    }
    for spent, want in states.items():
        got = Budget(limit_usd=100, spent_usd=spent).state()
        check(got == want,
              "预算状态边界错：spent=%.1f 期望 %s 得到 %s" % (spent, want, got))

    expect_raises(PolicyError, lambda: Budget(limit_usd=0, spent_usd=1).state(),
                  "limit_usd=0 没被拒绝（会除零）")


# ══════════════════════════════════════════════════════════ 规则 3:可解释

def test_every_decision_has_reason() -> None:
    eng = RoutingEngine(base_policy(), Budget(limit_usd=100, spent_usd=95))
    cases = [
        ("translate", "normal"),      # 命中规则
        ("未知任务", "normal"),        # 回落默认
        ("translate", "high"),        # 隐私 override
        ("compare", "normal"),        # 预算降级
    ]
    for task, sens in cases:
        d = eng.route(task, sensitivity=sens)
        check(bool(d.reason) and len(d.reason) > 5,
              "决策没有可读的 reason：task=%r sens=%r reason=%r" % (task, sens, d.reason))
        check("tier" in d.as_dict(), "as_dict 缺 tier —— 审计留痕会缺字段")


# ══════════════════════════════════════════════════════════ 配置校验

def test_policy_validation() -> None:
    """配置错了要在启动时炸，不要在第一个客户请求上炸。"""
    T = {"local": {"models": ["a"]}, "cheap": {"models": ["b"]}}

    expect_raises(PolicyError, lambda: RoutingEngine(Policy(tenant="", tiers=T)),
                  "空 tenant 没被拒绝")
    expect_raises(PolicyError, lambda: RoutingEngine(Policy(tenant="t", tiers={})),
                  "空 tiers 没被拒绝")
    expect_raises(PolicyError,
                  lambda: RoutingEngine(Policy(tenant="t", tiers={"cheap": {"models": ["b"]}})),
                  "缺 local 档没被拒绝 —— sensitivity=high 会无处可去")
    expect_raises(PolicyError,
                  lambda: RoutingEngine(Policy(tenant="t", tiers=dict(T, weird={"models": ["x"]}))),
                  "未知 tier 名没被拒绝")
    expect_raises(PolicyError,
                  lambda: RoutingEngine(Policy(tenant="t", tiers={"local": {"models": []}, "cheap": {"models": ["b"]}})),
                  "空 models 列表没被拒绝")
    expect_raises(PolicyError,
                  lambda: RoutingEngine(Policy(tenant="t", tiers=T, rules=[{"task": "x"}])),
                  "规则缺 tier 没被拒绝")
    expect_raises(PolicyError,
                  lambda: RoutingEngine(Policy(tenant="t", tiers=T, rules=[{"task": "x", "tier": "nope"}])),
                  "规则引用未配置的 tier 没被拒绝")
    expect_raises(PolicyError,
                  lambda: RoutingEngine(Policy(tenant="t", tiers=T, default_tier="nope")),
                  "default_tier 指向未配置的 tier 没被拒绝")

    # 负对照:合法配置**必须**通过 —— 否则「全部拒绝」也能让上面全绿
    try:
        RoutingEngine(Policy(tenant="t", tiers=T, rules=[{"task": "x", "tier": "cheap"}]))
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：合法配置被拒绝了（%s）。"
                     "如果什么都拒绝，上面的校验测试就证明不了任何事" % e)


# ══════════════════════════════════════════════════════════ 路由细节

def test_first_match_wins() -> None:
    """规则按顺序匹配，先命中的赢 —— 这个语义要测，否则改序会静默改行为。"""
    p = base_policy(rules=[
        {"task": "x", "tier": "cheap"},
        {"task": "x", "tier": "premium"},
    ])
    check(RoutingEngine(p).route("x").tier == "cheap",
          "规则匹配不是「先命中的赢」")


def test_wildcard_and_default() -> None:
    p = base_policy(rules=[{"task": "*", "tier": "mid"}])
    check(RoutingEngine(p).route("任意任务").tier == "mid", "通配规则没生效")

    p = base_policy(rules=[], default_tier="mid")
    check(RoutingEngine(p).route("任意任务").tier == "mid", "default_tier 没生效")


def test_models_for() -> None:
    eng = RoutingEngine(base_policy())
    check(eng.models_for("cheap") == ["cheap-a"], "models_for 返回错误")
    expect_raises(PolicyError, lambda: eng.models_for("nope"),
                  "models_for 对未知 tier 没报错")

    # 返回的是副本，外部改动不该污染 policy
    got = eng.models_for("cheap")
    got.append("注入的模型")
    check(eng.models_for("cheap") == ["cheap-a"],
          "models_for 返回了内部列表的引用 —— 调用方能改掉路由表")


# ══════════════════════════════════════════════════════════ main

TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    for t in TESTS:
        t()
    if FAILS:
        print("✗ %d 个测试断言失败" % len(FAILS), file=sys.stderr)
        for f in FAILS:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ routing 测试全部通过（%d 个测试函数，含每条不可破规则的负对照）"
          % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
