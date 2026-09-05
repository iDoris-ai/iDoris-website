#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端演示：会议录音 → 纪要 → 任务 → 人工审批 → 放行。

这是 dev-plan.md 阶段 B3 的那条线，也是 thailand-channels.md 说的
「拜访 depa 只缺的那个能演示的东西」。

## 它演示的不是「AI 很聪明」，是「AI 很守规矩」

企业主怕的不是 AI 不够聪明，是 **AI 替他做了他不知道的决定**。
所以这个演示的主线是**安全属性**，不是生成质量：

  1. 路由决策可解释 —— 每次调用说得出为什么走这一档
  2. 敏感任务强制本地 —— 压过任务类型，不靠人记得
  3. 审计只存元数据 —— 客户内容不进我们的库
  4. 草稿默认要人审 —— 且能改一半再放行
  5. 出处可回溯 —— 每条任务点得回转写稿的哪一段

## 为什么用桩模型

**演示的是流程与规矩，不是模型能力。** 用桩模型有三个好处：
可离线跑、可重复（同样输入同样输出）、不花钱。

真实模型调用是 dev-plan 阶段 A2 的第三块（接 LiteLLM），尚未做。
**这一点在演示时要对客户直说** —— 见 discovery-sop.md §3 交付会第五步：
主动讲局限，比多演示两个功能有用得多。

跑法：
    python3 demo_meeting_to_tasks.py            # 走一遍，打印每步
    python3 demo_meeting_to_tasks.py --self-test  # 断言五条安全属性成立
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gateway"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "assistant"))

from approval import (          # noqa: E402
    APPROVED, PENDING, ApprovalQueue, AutoReleasePolicy, Draft, Source,
)
from audit import AuditLog, AuditRecord   # noqa: E402
from routing import Budget, Policy, RoutingEngine   # noqa: E402


# ── 桩:一段虚构的泰英混杂会议转写 ────────────────────────────────────
# 虚构内容，不含任何真实客户信息。
TRANSCRIPT = [
    ("00:00:12", "th", "สวัสดีครับ วันนี้เราคุยเรื่องเมนูใหม่สำหรับเดือนหน้า"),
    ("00:01:40", "en", "Nid, can you finish the English menu translation by Friday?"),
    ("00:02:05", "th", "ได้ค่ะ แต่ต้องรอเชฟยืนยันชื่อเมนูก่อน"),
    ("00:03:22", "en", "Boon will confirm the dish names by Wednesday then."),
    ("00:05:10", "th", "อีกเรื่อง ราคาห้องช่วงไฮซีซั่นต้องอัปเดตในระบบด้วย"),
]


def stub_extract_tasks(transcript: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    """桩:从转写里抽任务。真实实现走 Documents 的 extract 动作。

    **每条任务都带 locator** —— 指回转写稿的时间码。
    没有出处的草稿进不了审批队列（approval.py 规矩 2）。
    """
    return [
        {"task": "完成英文菜单翻译", "owner": "Nid", "due": "周五", "locator": "00:01:40"},
        {"task": "确认菜名", "owner": "Boon", "due": "周三", "locator": "00:03:22"},
        {"task": "更新旺季房价", "owner": "待定", "due": "未定", "locator": "00:05:10"},
    ]


def build_policy() -> Policy:
    return Policy(
        tenant="baan-rimping",
        rules=[
            {"task": "transcribe", "tier": "local"},
            {"task": "summarize", "tier": "mid"},
            {"task": "extract", "tier": "cheap"},
        ],
        tiers={
            "local":   {"models": ["<本地 whisper>"]},
            "cheap":   {"models": ["<低价档>"]},
            "mid":     {"models": ["<中档>"]},
            "premium": {"models": ["<高档>"]},
        },
    )


def run(verbose: bool = True) -> dict[str, object]:
    tmp = tempfile.mkdtemp()
    engine = RoutingEngine(build_policy(), Budget(limit_usd=50.0, spent_usd=1.2))
    audit = AuditLog(os.path.join(tmp, "audit.db"))
    queue = ApprovalQueue(os.path.join(tmp, "approvals.db"),
                          policy=AutoReleasePolicy())   # 默认空白名单

    def say(*a: object) -> None:
        if verbose:
            print(*a)

    say("\n══ 1. 转写（含客人可辨识信息 → 敏感）══")
    d = engine.route("transcribe", sensitivity="high")
    say("   路由：%s" % d.tier)
    say("   理由：%s" % d.reason)
    say("   → 敏感任务强制走本地，压过任务类型规则" if d.overridden else "")
    audit.record(AuditRecord(
        tenant="baan-rimping", user="pm-01", component="voice", task="transcribe",
        sensitivity="high", tier=d.tier, model=engine.models_for(d.tier)[0],
        tokens_in=0, tokens_out=1200, cost_usd=0.0, latency_ms=8400,
        status="ok", routing_reason=d.reason))

    say("\n══ 2. 抽取任务 ══")
    d2 = engine.route("extract", sensitivity="normal")
    say("   路由：%s ｜ %s" % (d2.tier, d2.reason))
    tasks = stub_extract_tasks(TRANSCRIPT)
    audit.record(AuditRecord(
        tenant="baan-rimping", user="pm-01", component="assistant", task="extract",
        sensitivity="normal", tier=d2.tier, model=engine.models_for(d2.tier)[0],
        tokens_in=1200, tokens_out=180, cost_usd=0.0009, latency_ms=1600,
        status="ok", routing_reason=d2.reason))
    for t in tasks:
        say("   · %s（%s，%s）← 转写 %s" % (t["task"], t["owner"], t["due"], t["locator"]))

    say("\n══ 3. 进审批队列（默认全审）══")
    body = "\n".join("- %s ｜ 负责人：%s ｜ 截止：%s" % (t["task"], t["owner"], t["due"])
                     for t in tasks)
    aid = queue.submit(Draft(
        tenant="baan-rimping", flow="meeting_minutes", assignee="pm-01",
        summary="抽出 3 条待办", body=body,
        sources=[Source("transcript", "rec-2026-09-06", t["locator"]) for t in tasks]))
    item = queue.get(aid)
    say("   状态：%s" % item["status"])
    say("   为什么不自动放行：%s" % item["release_note"])

    say("\n══ 4. 人工修改后放行 ══")
    edited = body.replace("负责人：待定", "负责人：Ploy")
    queue.approve(aid, actor="pm-01", edited_body=edited)
    final = queue.get(aid)
    say("   放行人：%s" % final["actor"])
    say("   AI 原稿与人改后的内容分开存，出事能对比：")
    say("     原稿第 3 条 → %s" % body.splitlines()[2])
    say("     放行第 3 条 → %s" % final["final_body"].splitlines()[2])

    say("\n══ 5. 成本与合规回执 ══")
    usage = audit.monthly_usage("baan-rimping", "%d-%02d" % _now_ym())
    say("   本月调用 %d 次，花费 $%.4f" % (usage["calls"], usage["cost_usd"]))
    say("   按档分布：%s" % {k: v["calls"] for k, v in usage["by_tier"].items()})
    off = audit.sensitive_calls_off_local("baan-rimping")
    say("   敏感任务离开本地的次数：%d %s" % (len(off), "✓" if not off else "← 异常！"))

    result = {"approval": final, "usage": usage, "off_local": off,
              "route_transcribe": d, "route_extract": d2}
    audit.close()
    queue.close()
    return result


def _now_ym() -> tuple[int, int]:
    import time
    t = time.localtime()
    return t.tm_year, t.tm_mon


# ---------------------------------------------------------------- 自检

def self_test() -> int:
    """断言五条安全属性在这条真实路径上成立。

    **不是断言演示能跑通，是断言规矩没被绕过。**
    """
    fails: list[str] = []
    r = run(verbose=False)

    # 1 路由可解释
    for k in ("route_transcribe", "route_extract"):
        if not getattr(r[k], "reason", ""):
            fails.append("%s 没有可读的路由理由" % k)

    # 2 敏感任务强制本地
    rt = r["route_transcribe"]
    if rt.tier != "local" or not rt.overridden:
        fails.append("敏感任务没走本地：tier=%s overridden=%s" % (rt.tier, rt.overridden))

    # 3 审计只存元数据 —— 转写原文绝不能出现在审计库里
    blob = repr(r["usage"])
    for _, _, text in TRANSCRIPT:
        if text[:12] in blob:
            fails.append("审计数据里出现了会议内容片段 —— 内容边界被破坏")
            break

    # 4 草稿默认要人审，且编辑生效
    ap = r["approval"]
    if ap["status"] != APPROVED:
        fails.append("演示末态应为 approved，得到 %r" % ap["status"])
    if ap["body"] == ap["final_body"]:
        fails.append("编辑没有生效 —— 原稿与放行内容相同")
    if "待定" in ap["final_body"]:
        fails.append("人工修改没落到 final_body")
    if "待定" not in ap["body"]:
        fails.append("原稿被覆盖了 —— 出事时无法对比 AI 生成了什么")

    # 5 出处可回溯
    if len(ap["sources"]) != 3:
        fails.append("出处数量不对：%r" % ap["sources"])
    if not all(s.get("locator") for s in ap["sources"]):
        fails.append("有出处缺 locator —— 点不回转写稿")

    # 6 事后核查:敏感任务离开本地的次数必须为 0
    if r["off_local"]:
        fails.append("事后核查发现敏感任务离开了本地：%r" % r["off_local"])

    if fails:
        print("✗ 端到端演示的安全属性断言失败", file=sys.stderr)
        for f in fails:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ 端到端演示通过（路由可解释 · 敏感强制本地 · 审计不存内容 · "
          "默认人审且可编辑 · 出处可回溯 · 事后核查为零）")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    run()
    print("\n（演示用桩模型，不做真实模型调用。真实调用是 dev-plan 阶段 A2 的第三块，"
          "尚未接入 —— 演示时要对客户直说。）")
