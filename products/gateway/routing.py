#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris AI Gateway — 路由策略引擎。

设计见 docs/business/gateway-design.md。这个模块只做一件事:
**给定一个请求，决定它该走哪一档模型** —— 并且能说清为什么。

为什么这一段值得自己写(而不是直接用 LiteLLM 的路由):
LiteLLM 解决的是「怎么调各家的 API」,那是我们不该自建的部分。
但「什么任务该走哪档、敏感数据必须留在本地、超预算怎么办」
是我们的业务规则,它必须是**可读、可测、可审计**的,不能埋在配置里。

三条不可破的规则,全部由测试兜住(见 test_routing.py):

  1. sensitivity=high 的请求**必须**走 local 档,无论任务类型是什么。
     这是隐私承诺的机械保障 —— 不能靠人记得在配置里写对。

  2. 预算用尽时**必须**拒绝,不是降级后继续跑。
     见过太多「预算告警」最后变成没人看的邮件。

  3. 每一次路由决策都**必须**能说出理由(reason 字段)。
     一个说不出理由的路由表,三个月后没人敢改。

用法:
    engine = RoutingEngine(load_policy("policy.example.json"))
    d = engine.route(task="translate", sensitivity="normal")
    d.tier      -> "cheap"
    d.reason    -> "task 'translate' 命中规则 #0"

    python3 routing.py --self-test
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from typing import Any


SENSITIVITY_LEVELS = ("normal", "high")
KNOWN_TIERS = ("local", "cheap", "mid", "premium")


class PolicyError(ValueError):
    """策略配置本身有问题 —— 启动时就该炸，不要等到线上第一个请求。"""


@dataclass(frozen=True)
class Decision:
    tier: str
    reason: str
    matched_rule: int | None = None
    overridden: bool = False
    degraded: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Budget:
    """月度预算闸。三层，从软到硬 —— 见 gateway-design.md §4。"""

    limit_usd: float
    spent_usd: float = 0.0

    @property
    def ratio(self) -> float:
        if self.limit_usd <= 0:
            raise PolicyError("预算上限必须 > 0，得到 %r" % self.limit_usd)
        return self.spent_usd / self.limit_usd

    def state(self) -> str:
        r = self.ratio
        if r >= 1.0:
            return "blocked"      # 硬停:拒绝新请求
        if r >= 0.9:
            return "degraded"     # 降级:非 premium 强制走 cheap
        if r >= 0.7:
            return "warning"      # 提醒
        return "ok"


@dataclass
class Policy:
    tenant: str
    rules: list[dict[str, Any]] = field(default_factory=list)
    tiers: dict[str, dict[str, Any]] = field(default_factory=dict)
    default_tier: str = "cheap"

    def validate(self) -> None:
        """启动时校验。配置错了要在这里炸，不要在第一个客户请求上炸。"""
        if not self.tenant:
            raise PolicyError("policy 缺少 tenant")
        if not self.tiers:
            raise PolicyError("policy 缺少 tiers")

        for name in self.tiers:
            if name not in KNOWN_TIERS:
                raise PolicyError(
                    "未知 tier %r（可用：%s）" % (name, ", ".join(KNOWN_TIERS)))
            models = self.tiers[name].get("models")
            if not models:
                raise PolicyError("tier %r 没有配置任何模型" % name)

        # local 档是隐私承诺的落点，缺了它 sensitivity=high 就无处可去
        if "local" not in self.tiers:
            raise PolicyError(
                "policy 必须配置 local 档 —— sensitivity=high 的请求要走它。"
                "没有 local 档就等于没有隐私保障")

        if self.default_tier not in self.tiers:
            raise PolicyError(
                "default_tier %r 不在已配置的 tiers 中" % self.default_tier)

        for i, r in enumerate(self.rules):
            if "tier" not in r:
                raise PolicyError("规则 #%d 缺少 tier" % i)
            if r["tier"] not in self.tiers:
                raise PolicyError(
                    "规则 #%d 的 tier %r 不在已配置的 tiers 中" % (i, r["tier"]))
            sens = r.get("sensitivity")
            if sens is not None and sens not in SENSITIVITY_LEVELS:
                raise PolicyError(
                    "规则 #%d 的 sensitivity %r 非法（可用：%s）"
                    % (i, sens, ", ".join(SENSITIVITY_LEVELS)))


class RoutingEngine:
    def __init__(self, policy: Policy, budget: Budget | None = None):
        policy.validate()
        self.policy = policy
        self.budget = budget

    # ---------------------------------------------------------------- route

    def route(self, task: str, sensitivity: str = "normal") -> Decision:
        if sensitivity not in SENSITIVITY_LEVELS:
            raise ValueError(
                "sensitivity 必须是 %s 之一，得到 %r"
                % (" / ".join(SENSITIVITY_LEVELS), sensitivity))

        # ── 规则 2:预算硬停优先于一切 ────────────────────────────────
        # 放在最前面是刻意的:超预算时连敏感任务也不该跑,
        # 因为「跑」这个动作本身就要花钱。
        if self.budget is not None and self.budget.state() == "blocked":
            raise BudgetExceeded(
                "本月预算已用尽（%.2f / %.2f USD）——拒绝新请求。"
                "这是硬停，不是降级。" % (self.budget.spent_usd, self.budget.limit_usd))

        # ── 规则 1:sensitivity=high 强制走 local，压过任务类型 ──────────
        # 这是隐私承诺的机械保障。放在任务匹配之前,
        # 所以无论路由表怎么写、写没写这个任务,敏感数据都不会出去。
        if sensitivity == "high":
            return Decision(
                tier="local",
                reason="sensitivity=high → 强制 local 档（压过任务类型规则）",
                overridden=True,
            )

        # ── 任务类型匹配 ──────────────────────────────────────────────
        matched: tuple[int, dict[str, Any]] | None = None
        for i, r in enumerate(self.policy.rules):
            if r.get("sensitivity") == "high":
                continue          # high 规则已由上面的 override 覆盖
            pattern = r.get("task", "*")
            if pattern == "*" or pattern == task:
                matched = (i, r)
                break

        if matched is None:
            tier, reason, idx = self.policy.default_tier, (
                "task %r 未命中任何规则 → 回落 default_tier" % task), None
        else:
            idx, rule = matched
            tier = rule["tier"]
            reason = "task %r 命中规则 #%d" % (task, idx)

        # ── 预算降级(软) ──────────────────────────────────────────────
        if self.budget is not None and self.budget.state() == "degraded":
            if tier == "premium":
                return Decision(
                    tier="cheap",
                    reason=reason + "；但预算已达 90% → 从 premium 降级到 cheap",
                    matched_rule=idx,
                    degraded=True,
                )

        return Decision(tier=tier, reason=reason, matched_rule=idx)

    def models_for(self, tier: str) -> list[str]:
        if tier not in self.policy.tiers:
            raise PolicyError("未配置的 tier: %r" % tier)
        return list(self.policy.tiers[tier]["models"])


class BudgetExceeded(RuntimeError):
    """预算硬停。**不要 catch 它然后继续跑** —— 那就等于没有闸。"""


# ---------------------------------------------------------------- 加载

def load_policy(path: str) -> Policy:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return Policy(
        tenant=raw.get("tenant", ""),
        rules=raw.get("rules", []),
        tiers=raw.get("tiers", {}),
        default_tier=raw.get("default_tier", "cheap"),
    )


# ---------------------------------------------------------------- 自检

_SAMPLE = Policy(
    tenant="sample",
    rules=[
        {"task": "translate", "tier": "cheap"},
        {"task": "extract", "tier": "cheap"},
        {"task": "summarize", "tier": "mid"},
        {"task": "compare", "tier": "premium"},
    ],
    tiers={
        "local": {"models": ["local-model"]},
        "cheap": {"models": ["cheap-a", "cheap-b"]},
        "mid": {"models": ["mid-a"]},
        "premium": {"models": ["premium-a"]},
    },
)


def self_test() -> int:
    """断言三条不可破规则真的成立。测试细节在 test_routing.py，这里是烟测。"""
    fails: list[str] = []
    eng = RoutingEngine(_SAMPLE)

    if eng.route("translate").tier != "cheap":
        fails.append("translate 应走 cheap")
    if eng.route("compare").tier != "premium":
        fails.append("compare 应走 premium")

    # 规则 1
    d = eng.route("translate", sensitivity="high")
    if d.tier != "local" or not d.overridden:
        fails.append("sensitivity=high 未强制走 local —— 隐私保障失效")

    # 规则 2
    over = RoutingEngine(_SAMPLE, Budget(limit_usd=100, spent_usd=100))
    try:
        over.route("translate")
        fails.append("预算用尽时没有拒绝 —— 硬停失效")
    except BudgetExceeded:
        pass

    # 规则 3
    if not eng.route("translate").reason:
        fails.append("决策没有 reason")

    # 配置校验:缺 local 档必须炸
    try:
        RoutingEngine(Policy(tenant="x", tiers={"cheap": {"models": ["m"]}}))
        fails.append("缺 local 档竟然通过了校验")
    except PolicyError:
        pass

    if fails:
        print("✗ routing 自检失败", file=sys.stderr)
        for f in fails:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ routing 自检通过（三条不可破规则 + 配置校验）")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else self_test())
