#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris AI Gateway — 审计留痕。

设计见 docs/business/gateway-design.md §2 与 §5。

**一条不可破的边界，写在最前面：**

    Gateway 绝不存储客户业务数据的内容，只存元数据。

存：时间、租户、用户、组件、任务、敏感度、tier、模型、token 数、成本、延迟、成败。
不存：提示词内容、模型输出内容、上传的文档、任何客户业务数据。

理由：Gateway 是我们托管的、**跨客户**的组件。一旦它存内容，
它就成了一个集中的客户数据库 —— 那是我们最不想承担的责任。
内容留在客户侧或客户指定的存储。

这条边界由 `_FORBIDDEN_FIELDS` 机械保证：出现任何疑似内容字段直接拒绝写入，
而不是「记得别传」。见 test_audit.py 的负对照。

一条记录同时服务三个目的：
  客户看成本 · 我们做优化 · 出事能追溯

存储用 SQLite。第一批客户的调用量在每天几百到几千条，SQLite 完全够用，
**少一个要运维的东西**比多一点写入性能重要得多。撑不住再换 —— 换的成本
远低于现在多养一个 Postgres。

用法：
    log = AuditLog("audit.db")
    log.record(AuditRecord(tenant="hotel", user="staff-07", component="documents",
                           task="extract", sensitivity="normal", tier="cheap",
                           model="m", tokens_in=3200, tokens_out=450,
                           cost_usd=0.0021, latency_ms=1840, status="ok"))
    log.monthly_usage("hotel", "2026-09")

    python3 audit.py --self-test
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass, asdict
from typing import Any


class ContentLeakError(ValueError):
    """有人试图把业务内容写进审计表。**这是设计边界被破坏，不是参数写错。**"""


# 出现这些字段名就是在试图存内容。宁可误伤，也不能让内容进来 ——
# 一个「大概不会存内容」的审计表，和一个客户数据库没有区别。
_FORBIDDEN_FIELDS = frozenset({
    "prompt", "prompts", "input", "input_text", "content", "text", "body",
    "output", "output_text", "completion", "response", "result",
    "messages", "document", "documents", "file", "files", "payload",
    "raw", "data",
})

_STATUSES = ("ok", "error", "blocked", "degraded")


@dataclass(frozen=True)
class AuditRecord:
    tenant: str
    user: str
    component: str          # documents / assistant / creative / voice
    task: str               # translate / extract / line.reply ...
    sensitivity: str        # normal / high
    tier: str               # local / cheap / mid / premium
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    status: str             # ok / error / blocked / degraded
    routing_reason: str = ""   # 路由决策的理由，来自 RoutingEngine.Decision
    ts: float | None = None    # None 表示用当前时间

    def validate(self) -> None:
        if not self.tenant or not self.user:
            raise ValueError("tenant 与 user 必填 —— 没有它们就无法追溯")
        if self.status not in _STATUSES:
            raise ValueError("status 必须是 %s 之一，得到 %r"
                             % ("/".join(_STATUSES), self.status))
        for f in ("tokens_in", "tokens_out", "latency_ms"):
            v = getattr(self, f)
            if not isinstance(v, int) or v < 0:
                raise ValueError("%s 必须是非负整数，得到 %r" % (f, v))
        if not isinstance(self.cost_usd, (int, float)) or self.cost_usd < 0:
            raise ValueError("cost_usd 必须是非负数，得到 %r" % self.cost_usd)


def assert_no_content(payload: dict[str, Any]) -> None:
    """机械保证内容边界。**这不是建议，是闸门。**"""
    hits = sorted(k for k in payload if k.lower() in _FORBIDDEN_FIELDS)
    if hits:
        raise ContentLeakError(
            "审计记录里出现疑似业务内容字段 %s —— Gateway 只存元数据。"
            "内容留在客户侧或客户指定的存储，见 gateway-design.md §2。"
            % ", ".join(repr(h) for h in hits))

    # 值也要看:有人可能把一整段提示词塞进 routing_reason 之类的自由文本字段
    for k, v in payload.items():
        if isinstance(v, str) and len(v) > 500:
            raise ContentLeakError(
                "字段 %r 长度 %d 超过 500 字符 —— 审计表不该出现长文本，"
                "这通常意味着有人把内容塞进了元数据字段" % (k, len(v)))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             REAL    NOT NULL,
    tenant         TEXT    NOT NULL,
    user           TEXT    NOT NULL,
    component      TEXT    NOT NULL,
    task           TEXT    NOT NULL,
    sensitivity    TEXT    NOT NULL,
    tier           TEXT    NOT NULL,
    model          TEXT    NOT NULL,
    tokens_in      INTEGER NOT NULL,
    tokens_out     INTEGER NOT NULL,
    cost_usd       REAL    NOT NULL,
    latency_ms     INTEGER NOT NULL,
    status         TEXT    NOT NULL,
    routing_reason TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_calls_tenant_ts ON calls(tenant, ts);
"""


class AuditLog:
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "AuditLog":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------- 写

    def record(self, rec: AuditRecord) -> int:
        rec.validate()
        payload = asdict(rec)
        assert_no_content(payload)          # ← 内容边界的闸门
        payload["ts"] = rec.ts if rec.ts is not None else time.time()

        cols = ", ".join(payload)
        marks = ", ".join("?" for _ in payload)
        cur = self._conn.execute(
            "INSERT INTO calls (%s) VALUES (%s)" % (cols, marks),
            tuple(payload.values()))
        self._conn.commit()
        return int(cur.lastrowid)

    # ------------------------------------------------------------- 读

    def monthly_usage(self, tenant: str, month: str) -> dict[str, Any]:
        """month 形如 '2026-09'。给客户看的月报就是这个。"""
        try:
            y, m = (int(x) for x in month.split("-"))
        except Exception:                                    # noqa: BLE001
            raise ValueError("month 需形如 '2026-09'，得到 %r" % month) from None
        if not 1 <= m <= 12:
            raise ValueError("月份非法：%r" % month)

        start = time.mktime((y, m, 1, 0, 0, 0, 0, 0, -1))
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        end = time.mktime((ny, nm, 1, 0, 0, 0, 0, 0, -1))

        row = self._conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(cost_usd),0) cost,"
            " COALESCE(SUM(tokens_in),0) tin, COALESCE(SUM(tokens_out),0) tout"
            " FROM calls WHERE tenant=? AND ts>=? AND ts<?",
            (tenant, start, end)).fetchone()

        by_tier = {
            r["tier"]: {"calls": r["n"], "cost_usd": round(r["cost"], 6)}
            for r in self._conn.execute(
                "SELECT tier, COUNT(*) n, SUM(cost_usd) cost FROM calls"
                " WHERE tenant=? AND ts>=? AND ts<? GROUP BY tier",
                (tenant, start, end))
        }
        by_component = {
            r["component"]: {"calls": r["n"], "cost_usd": round(r["cost"], 6)}
            for r in self._conn.execute(
                "SELECT component, COUNT(*) n, SUM(cost_usd) cost FROM calls"
                " WHERE tenant=? AND ts>=? AND ts<? GROUP BY component",
                (tenant, start, end))
        }
        return {
            "tenant": tenant, "month": month,
            "calls": row["n"],
            "cost_usd": round(row["cost"], 6),
            "tokens_in": row["tin"], "tokens_out": row["tout"],
            "by_tier": by_tier, "by_component": by_component,
        }

    def sensitive_calls_off_local(self, tenant: str) -> list[dict[str, Any]]:
        """审计用:找出所有 sensitivity=high 却没走 local 的调用。

        **正常情况下这个查询必须永远返回空** —— 路由引擎的规则 1 保证了这一点。
        它非空就说明有人绕过了 Gateway 直连模型，或者规则 1 被改坏了。
        这是隐私承诺的**事后核查**手段，与路由引擎的事前拦截互为双保险。
        """
        return [dict(r) for r in self._conn.execute(
            "SELECT id, ts, user, component, task, tier, model FROM calls"
            " WHERE tenant=? AND sensitivity='high' AND tier!='local'"
            " ORDER BY ts DESC", (tenant,))]


# ---------------------------------------------------------------- 自检

def self_test() -> int:
    fails: list[str] = []
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "t.db")

    with AuditLog(db) as log:
        rid = log.record(AuditRecord(
            tenant="h", user="u1", component="documents", task="extract",
            sensitivity="normal", tier="cheap", model="m",
            tokens_in=100, tokens_out=20, cost_usd=0.001,
            latency_ms=900, status="ok", ts=time.mktime((2026, 9, 5, 10, 0, 0, 0, 0, -1))))
        if rid <= 0:
            fails.append("record 没有返回 id")

        u = log.monthly_usage("h", "2026-09")
        if u["calls"] != 1 or abs(u["cost_usd"] - 0.001) > 1e-9:
            fails.append("月度统计错：%r" % u)

        # 内容边界:必须拒绝
        try:
            log._conn  # noqa: B018
            assert_no_content({"tenant": "h", "prompt": "客户的合同全文"})
            fails.append("内容边界失效：prompt 字段没被拒绝")
        except ContentLeakError:
            pass
        try:
            assert_no_content({"routing_reason": "x" * 600})
            fails.append("内容边界失效：600 字符的长文本没被拒绝")
        except ContentLeakError:
            pass
        # 负对照:合法元数据必须放行
        try:
            assert_no_content({"tenant": "h", "model": "m", "cost_usd": 0.1})
        except ContentLeakError:
            fails.append("负对照失败：合法元数据被误拒 —— 闸门有假阳性")

        if log.sensitive_calls_off_local("h"):
            fails.append("sensitive_calls_off_local 对正常数据返回了非空")

    if fails:
        print("✗ audit 自检失败", file=sys.stderr)
        for f in fails:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ audit 自检通过（写入 · 月度统计 · 内容边界 + 负对照）")
    return 0


if __name__ == "__main__":
    sys.exit(self_test())
