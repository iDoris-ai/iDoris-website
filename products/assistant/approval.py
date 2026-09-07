#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris Assistant — 审批队列。

设计见 docs/business/starter-kit/assistant.md §3.2 与 §3.3。

**这是客户每天真正要用的东西**，也是整个 Assistant 组件的安全支点。
LangGraph 负责在「等人点头」这里停住并持久化；这个模块负责**人点头的那一下**。

## 三条设计规矩（全部由测试兜住）

1. **草稿可编辑后放行。** 人改一半再发是最常见的路径。
   强制「要么全接受要么全驳回」会让人干脆不用这个系统 ——
   然后回到手工，而我们省的那点时间就没了。

2. **必须显示来源。** 纪要里每条任务能点回转写稿的哪一段；
   回复草稿能看到检索到了哪条业务信息。**没有出处的草稿没人敢发。**

3. **超时不自动放行。** 超过阈值未处理就升级提醒，**绝不默认发出去**。
   这条与「默认全审」是同一个原则的两面。

## 自动放行是白名单，不是开关

`AutoReleasePolicy` 默认**为空**。每加一条意图都必须同时满足三个条件：
客户书面确认 · 该意图已积累 ≥50 条人工审批历史且准确率 ≥95% · 有随时可关的开关。

理由（assistant.md 边界五）：
**一条错误的自动回复对本地小生意的伤害，远大于省下的那点人工。**

一家清迈酒店的 LINE 是他们的门面。回错一次房价、答错一次是否有空房，
损失的是真实订单和口碑。

用法：
    q = ApprovalQueue("approvals.db")
    aid = q.submit(Draft(tenant="h", flow="meeting_minutes", assignee="u1",
                         summary="3 条待办", body="...", sources=[...]))
    q.approve(aid, actor="u1", edited_body="改过的内容")

    python3 approval.py --self-test
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any


# 状态机。刻意不做「已发送」之外的终态细分 —— 越简单越不会有人绕过。
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
AUTO_RELEASED = "auto_released"
STATUSES = (PENDING, APPROVED, REJECTED, AUTO_RELEASED)

# 超时后升级提醒的默认阈值。**注意它不会导致自动放行** —— 见 escalations()。
DEFAULT_ESCALATE_AFTER_S = 4 * 3600


class NoSourcesError(ValueError):
    """草稿没有出处。**规矩 2 被破坏，不是参数写错。**"""


class AutoReleaseDenied(RuntimeError):
    """自动放行被拒。默认路径就是这条 —— 白名单默认为空。"""


@dataclass(frozen=True)
class Source:
    """一条出处。指回原始材料的哪一段。"""
    kind: str      # transcript / document / knowledge
    ref: str       # 文件或转写稿标识
    locator: str   # 段落号 / 页码+bbox / 时间码

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "ref": self.ref, "locator": self.locator}


@dataclass
class Draft:
    tenant: str
    flow: str          # meeting_minutes / reply_draft / doc_actions / research / line_reply
    assignee: str
    summary: str
    body: str
    sources: list[Source] = field(default_factory=list)
    intent: str = ""        # 供白名单匹配用，如 business_hours
    confidence: float = 0.0
    contains_pii: bool = False

    def validate(self) -> None:
        if not self.tenant or not self.assignee:
            raise ValueError("tenant 与 assignee 必填 —— 没有它们这条草稿没人认领")
        if not self.body.strip():
            raise ValueError("草稿正文不能为空")
        # 规矩 2:没有出处的草稿不许进队列
        if not self.sources:
            raise NoSourcesError(
                "草稿没有 sources —— 没有出处的草稿没人敢发。"
                "见 assistant.md §3.2 规矩 2")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence 必须在 0..1，得到 %r" % self.confidence)


@dataclass
class AutoReleaseRule:
    """白名单的一条。三个条件全满足才放行。"""
    flow: str
    intents: tuple[str, ...]
    min_confidence: float = 0.9
    require_no_pii: bool = True
    enabled: bool = True          # 随时可关的开关

    def allows(self, d: Draft) -> tuple[bool, str]:
        if not self.enabled:
            return False, "该规则已被关闭"
        if d.flow != self.flow:
            return False, "flow 不匹配（规则针对 %s）" % self.flow
        if d.intent not in self.intents:
            return False, "意图 %r 不在白名单 %s 内" % (d.intent, list(self.intents))
        if d.confidence < self.min_confidence:
            return False, ("置信度 %.2f 低于阈值 %.2f"
                           % (d.confidence, self.min_confidence))
        if self.require_no_pii and d.contains_pii:
            return False, "草稿含个人信息，禁止自动放行"
        return True, "命中白名单规则（flow=%s intent=%s）" % (self.flow, d.intent)


class AutoReleasePolicy:
    """**默认为空。** 这不是配置疏忽，是设计。"""

    def __init__(self, rules: list[AutoReleaseRule] | None = None):
        self.rules = list(rules or [])

    def decide(self, d: Draft) -> tuple[bool, str]:
        if not self.rules:
            return False, "白名单为空（默认）→ 全部人工审批"
        reasons = []
        for r in self.rules:
            ok, why = r.allows(d)
            if ok:
                return True, why
            reasons.append(why)
        return False, "未命中任何白名单规则：" + "；".join(reasons)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant       TEXT NOT NULL,
    flow         TEXT NOT NULL,
    assignee     TEXT NOT NULL,
    summary      TEXT NOT NULL,
    body         TEXT NOT NULL,
    final_body   TEXT,
    sources_json TEXT NOT NULL,
    intent       TEXT NOT NULL DEFAULT '',
    confidence   REAL NOT NULL DEFAULT 0,
    contains_pii INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL,
    release_note TEXT NOT NULL DEFAULT '',
    actor        TEXT,
    reject_reason TEXT,
    created_at   REAL NOT NULL,
    decided_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_ap_pending ON approvals(tenant, status, created_at);
"""


class ApprovalQueue:
    def __init__(self, path: str, policy: AutoReleasePolicy | None = None,
                 escalate_after_s: int = DEFAULT_ESCALATE_AFTER_S):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self.policy = policy or AutoReleasePolicy()   # 默认空白名单
        self.escalate_after_s = escalate_after_s

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ApprovalQueue":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------- 提交

    def submit(self, d: Draft, now: float | None = None) -> int:
        d.validate()
        now = time.time() if now is None else now

        auto, why = self.policy.decide(d)
        status = AUTO_RELEASED if auto else PENDING

        cur = self._conn.execute(
            "INSERT INTO approvals (tenant, flow, assignee, summary, body,"
            " final_body, sources_json, intent, confidence, contains_pii,"
            " status, release_note, actor, created_at, decided_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d.tenant, d.flow, d.assignee, d.summary, d.body,
             d.body if auto else None,
             json.dumps([s.as_dict() for s in d.sources], ensure_ascii=False),
             d.intent, d.confidence, int(d.contains_pii),
             status, why, None, now, now if auto else None))
        self._conn.commit()
        return int(cur.lastrowid)

    # ------------------------------------------------------------- 决策

    def approve(self, approval_id: int, actor: str,
                edited_body: str | None = None, now: float | None = None) -> None:
        """规矩 1：草稿可编辑后放行。`edited_body` 为 None 表示原样放行。"""
        row = self._require_pending(approval_id)
        if not actor:
            raise ValueError("actor 必填 —— 审批必须留下是谁点的头")
        final = row["body"] if edited_body is None else edited_body
        if not final.strip():
            raise ValueError("放行的内容不能为空")
        self._conn.execute(
            "UPDATE approvals SET status=?, final_body=?, actor=?, decided_at=?"
            " WHERE id=?",
            (APPROVED, final, actor, time.time() if now is None else now, approval_id))
        self._conn.commit()

    def reject(self, approval_id: int, actor: str, reason: str,
               now: float | None = None) -> None:
        self._require_pending(approval_id)
        if not actor:
            raise ValueError("actor 必填")
        if not reason.strip():
            raise ValueError("驳回必须写理由 —— 否则草稿质量永远不会改进")
        self._conn.execute(
            "UPDATE approvals SET status=?, actor=?, reject_reason=?, decided_at=?"
            " WHERE id=?",
            (REJECTED, actor, reason, time.time() if now is None else now, approval_id))
        self._conn.commit()

    def _require_pending(self, approval_id: int) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if row is None:
            raise KeyError("审批项不存在：%r" % approval_id)
        if row["status"] != PENDING:
            raise ValueError(
                "审批项 %d 已是 %s 状态，不能重复决策" % (approval_id, row["status"]))
        return row

    # ------------------------------------------------------------- 查询

    def pending(self, tenant: str, assignee: str | None = None) -> list[dict[str, Any]]:
        sql = ("SELECT * FROM approvals WHERE tenant=? AND status=?")
        args: tuple[Any, ...] = (tenant, PENDING)
        if assignee is not None:
            sql += " AND assignee=?"
            args += (assignee,)
        sql += " ORDER BY created_at"
        return [self._row(r) for r in self._conn.execute(sql, args)]

    def escalations(self, tenant: str, now: float | None = None) -> list[dict[str, Any]]:
        """超时未处理的项。

        **规矩 3：这个方法只负责「找出来提醒」，绝不放行。**
        超时的后果是升级提醒，不是默认发出去 —— 这与「默认全审」是同一个原则的两面。
        """
        now = time.time() if now is None else now
        cutoff = now - self.escalate_after_s
        return [self._row(r) for r in self._conn.execute(
            "SELECT * FROM approvals WHERE tenant=? AND status=? AND created_at<?"
            " ORDER BY created_at", (tenant, PENDING, cutoff))]

    def get(self, approval_id: int) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if row is None:
            raise KeyError("审批项不存在：%r" % approval_id)
        return self._row(row)

    @staticmethod
    def _row(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["sources"] = json.loads(d.pop("sources_json"))
        d["contains_pii"] = bool(d["contains_pii"])
        return d


# ---------------------------------------------------------------- 自检

def _draft(**kw: Any) -> Draft:
    base: dict[str, Any] = dict(
        tenant="h", flow="meeting_minutes", assignee="u1",
        summary="3 条待办", body="草稿正文",
        sources=[Source("transcript", "rec-1", "00:12:30")])
    base.update(kw)
    return Draft(**base)


def self_test() -> int:
    fails: list[str] = []
    q = ApprovalQueue(os.path.join(tempfile.mkdtemp(), "a.db"))

    aid = q.submit(_draft())
    if q.get(aid)["status"] != PENDING:
        fails.append("默认应进 pending（白名单为空）")

    q.approve(aid, actor="u1", edited_body="人改过的内容")
    got = q.get(aid)
    if got["status"] != APPROVED or got["final_body"] != "人改过的内容":
        fails.append("规矩 1 失效：编辑后放行没生效")

    # 规矩 2
    try:
        q.submit(_draft(sources=[]))
        fails.append("规矩 2 失效：没有出处的草稿进了队列")
    except NoSourcesError:
        pass

    # 规矩 3:超时只提醒不放行
    old = time.time() - DEFAULT_ESCALATE_AFTER_S - 60
    bid = q.submit(_draft(summary="很久没人管"), now=old)
    esc = q.escalations("h")
    if not any(e["id"] == bid for e in esc):
        fails.append("规矩 3 失效：超时项没被找出来")
    if q.get(bid)["status"] != PENDING:
        fails.append("规矩 3 破了：超时项竟然不再是 pending —— 可能被自动放行了")

    # 白名单默认为空
    ok, why = AutoReleasePolicy().decide(_draft(intent="business_hours", confidence=1.0))
    if ok:
        fails.append("白名单默认不为空 —— 默认就该全部人工审批")

    q.close()
    if fails:
        print("✗ approval 自检失败", file=sys.stderr)
        for f in fails:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ approval 自检通过（三条规矩 + 白名单默认为空）")
    return 0


if __name__ == "__main__":
    sys.exit(self_test())
