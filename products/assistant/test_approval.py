#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""approval.py 的测试。

**每条安全属性都配负对照** —— 证明规矩真的在拦，而不是碰巧没触发。

跑法：python3 test_approval.py
"""

import os
import sys
import tempfile
import time

from approval import (
    APPROVED,
    AUTO_RELEASED,
    AutoReleasePolicy,
    AutoReleaseRule,
    ApprovalQueue,
    DEFAULT_ESCALATE_AFTER_S,
    Draft,
    NoSourcesError,
    PENDING,
    REJECTED,
    Source,
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
        FAILS.append("%s（抛的是 %s）" % (msg, type(e).__name__))
        return
    FAILS.append(msg)


def draft(**kw):
    base = dict(tenant="h", flow="meeting_minutes", assignee="u1",
                summary="3 条待办", body="草稿正文",
                sources=[Source("transcript", "rec-1", "00:12:30")])
    base.update(kw)
    return Draft(**base)


def fresh(policy=None, escalate_after_s=DEFAULT_ESCALATE_AFTER_S):
    return ApprovalQueue(os.path.join(tempfile.mkdtemp(), "a.db"),
                         policy=policy, escalate_after_s=escalate_after_s)


# ══════════════════════════════════════ 规矩 1：草稿可编辑后放行

def test_edit_then_approve() -> None:
    q = fresh()
    aid = q.submit(draft(body="原始草稿"))
    q.approve(aid, actor="u1", edited_body="人改过的内容")
    got = q.get(aid)
    check(got["status"] == APPROVED, "编辑后放行未生效")
    check(got["final_body"] == "人改过的内容",
          "规矩 1 破了：编辑内容没被保存，得到 %r" % got["final_body"])
    check(got["body"] == "原始草稿",
          "原始草稿被覆盖了 —— 出事时无法对比 AI 生成了什么、人改了什么")

    # 负对照:不传 edited_body 时必须原样放行 ——
    # 否则「永远用原文」也能让上面绿
    bid = q.submit(draft(body="另一份草稿"))
    q.approve(bid, actor="u1")
    check(q.get(bid)["final_body"] == "另一份草稿",
          "负对照失败：未编辑时 final_body 不等于原文")
    q.close()


def test_approve_requires_actor_and_content() -> None:
    q = fresh()
    aid = q.submit(draft())
    expect_raises(ValueError, lambda: q.approve(aid, actor=""),
                  "空 actor 没被拒 —— 审批必须留下是谁点的头")
    expect_raises(ValueError, lambda: q.approve(aid, actor="u1", edited_body="   "),
                  "放行空白内容没被拒")
    q.close()


def test_no_double_decision() -> None:
    q = fresh()
    aid = q.submit(draft())
    q.approve(aid, actor="u1")
    expect_raises(ValueError, lambda: q.approve(aid, actor="u2"),
                  "已放行的项能被重复放行")
    expect_raises(ValueError, lambda: q.reject(aid, actor="u2", reason="x"),
                  "已放行的项能被驳回")
    q.close()


def test_reject_requires_reason() -> None:
    q = fresh()
    aid = q.submit(draft())
    expect_raises(ValueError, lambda: q.reject(aid, actor="u1", reason="  "),
                  "驳回没写理由竟然通过 —— 草稿质量永远不会改进")
    q.reject(aid, actor="u1", reason="房价答错了")
    got = q.get(aid)
    check(got["status"] == REJECTED and got["reject_reason"] == "房价答错了",
          "驳回没记录理由")
    q.close()


# ══════════════════════════════════════ 规矩 2：必须显示来源

def test_sources_required() -> None:
    q = fresh()
    expect_raises(NoSourcesError, lambda: q.submit(draft(sources=[])),
                  "规矩 2 破了：没有出处的草稿进了队列")

    # 负对照:有出处的必须能进 —— 否则「什么都拒绝」也能让上面绿
    aid = q.submit(draft())
    got = q.get(aid)
    check(len(got["sources"]) == 1 and got["sources"][0]["locator"] == "00:12:30",
          "负对照失败：有出处的草稿没能正确保存 sources，得到 %r" % got["sources"])
    q.close()


# ══════════════════════════════════════ 规矩 3：超时不自动放行

def test_escalation_never_releases() -> None:
    """超时的后果是升级提醒，**绝不是默认发出去**。"""
    q = fresh(escalate_after_s=3600)
    old = time.time() - 7200
    aid = q.submit(draft(summary="很久没人管"), now=old)

    esc = q.escalations("h")
    check(any(e["id"] == aid for e in esc), "超时项没被找出来")

    # 关键断言:超时之后状态**仍然是 pending**
    check(q.get(aid)["status"] == PENDING,
          "规矩 3 破了：超时项状态变成了 %r —— 它被自动放行了"
          % q.get(aid)["status"])
    check(q.get(aid)["final_body"] is None,
          "规矩 3 破了：超时项有了 final_body —— 内容被发出去了")

    # 再查一次也不该有副作用
    q.escalations("h")
    check(q.get(aid)["status"] == PENDING,
          "escalations() 有副作用 —— 多查几次就把项目放行了")

    # 负对照:没超时的不该被列进升级 —— 否则「全都算超时」也能让上面绿
    new_id = q.submit(draft(summary="刚提交"))
    check(not any(e["id"] == new_id for e in q.escalations("h")),
          "负对照失败：刚提交的项也被算作超时")
    q.close()


# ══════════════════════════════════════ 自动放行白名单

def test_whitelist_empty_by_default() -> None:
    """默认全部人工审批。这不是配置疏忽，是设计。"""
    q = fresh()
    aid = q.submit(draft(intent="business_hours", confidence=1.0))
    check(q.get(aid)["status"] == PENDING,
          "白名单默认不为空 —— 高置信度的常见意图被自动放行了")
    check("白名单为空" in q.get(aid)["release_note"],
          "release_note 没说明为什么没自动放行")
    q.close()


def test_whitelist_all_conditions() -> None:
    """白名单命中要四个条件全满足；任一不满足都必须落回人工。"""
    rule = AutoReleaseRule(flow="line_reply", intents=("business_hours", "location"),
                           min_confidence=0.9, require_no_pii=True)
    q = fresh(policy=AutoReleasePolicy([rule]))

    ok_id = q.submit(draft(flow="line_reply", intent="business_hours", confidence=0.95))
    check(q.get(ok_id)["status"] == AUTO_RELEASED,
          "四条件全满足却没自动放行")

    cases = [
        ("意图不在白名单", dict(flow="line_reply", intent="price_list", confidence=0.99)),
        ("置信度不足",     dict(flow="line_reply", intent="business_hours", confidence=0.85)),
        ("含个人信息",     dict(flow="line_reply", intent="business_hours", confidence=0.99, contains_pii=True)),
        ("flow 不匹配",    dict(flow="meeting_minutes", intent="business_hours", confidence=0.99)),
    ]
    for label, kw in cases:
        i = q.submit(draft(**kw))
        check(q.get(i)["status"] == PENDING,
              "白名单破了：%s 的草稿被自动放行了" % label)

    # 开关必须真的能关掉
    rule.enabled = False
    off = q.submit(draft(flow="line_reply", intent="business_hours", confidence=0.99))
    check(q.get(off)["status"] == PENDING,
          "白名单的开关关不掉 —— 出事时无法紧急停止")
    q.close()


def test_price_intent_never_auto() -> None:
    """价目类意图明确不进白名单 —— 高频不等于低风险。

    这条是产品决策的测试化：房价答错直接损失订单，
    尽管它是最高频的问题之一。见 line-agent-design.md §4。
    """
    rule = AutoReleaseRule(flow="line_reply",
                           intents=("business_hours", "location"))   # 刻意不含 price_list
    q = fresh(policy=AutoReleasePolicy([rule]))
    i = q.submit(draft(flow="line_reply", intent="price_list", confidence=1.0))
    check(q.get(i)["status"] == PENDING,
          "价目类意图被自动放行了 —— 房价答错会直接损失订单")
    q.close()


# ══════════════════════════════════════ 队列查询与隔离

def test_pending_filtering_and_tenant_isolation() -> None:
    q = fresh()
    q.submit(draft(assignee="u1"))
    q.submit(draft(assignee="u2"))
    q.submit(draft(tenant="另一家", assignee="u1"))

    check(len(q.pending("h")) == 2, "按租户过滤错")
    check(len(q.pending("h", assignee="u1")) == 1, "按 assignee 过滤错")
    check(q.pending("另一家")[0]["assignee"] == "u1", "另一租户的数据取错")

    # 负对照:租户隔离必须真的隔离
    check(all(r["tenant"] == "h" for r in q.pending("h")),
          "租户隔离破了：查 h 返回了别的租户的项")
    q.close()


def test_input_validation() -> None:
    q = fresh()
    expect_raises(ValueError, lambda: q.submit(draft(tenant="")), "空 tenant 没被拒")
    expect_raises(ValueError, lambda: q.submit(draft(assignee="")), "空 assignee 没被拒")
    expect_raises(ValueError, lambda: q.submit(draft(body="   ")), "空正文没被拒")
    expect_raises(ValueError, lambda: q.submit(draft(confidence=1.5)), "越界 confidence 没被拒")
    expect_raises(KeyError, lambda: q.get(99999), "不存在的 id 没报 KeyError")

    # 负对照:合法草稿必须能进
    try:
        q.submit(draft())
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：合法草稿被拒（%s）" % e)
    q.close()


# ══════════════════════════════════════ main

TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    for t in TESTS:
        t()
    if FAILS:
        print("✗ %d 个测试断言失败" % len(FAILS), file=sys.stderr)
        for f in FAILS:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ approval 测试全部通过（%d 个测试函数，含三条规矩与白名单的负对照）"
          % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
