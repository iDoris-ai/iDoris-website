#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit.py 的测试。

重点是**那条不可破的边界**：Gateway 绝不存内容，只存元数据。
每条断言都配负对照 —— 证明闸门在拦，而不是碰巧没触发。

跑法：python3 test_audit.py
"""

import os
import sys
import tempfile
import time
from datetime import datetime

from audit import (
    AuditLog,
    AuditRecord,
    ContentLeakError,
    assert_no_content,
    BILLING_TZ,
)

FAILS: list[str] = []


def bkk(*args: int) -> float:
    """按**账单时区**构造时间戳。

    早先这里用的是 time.mktime()（服务器本地时区）。当时 monthly_usage 的
    月份边界也用 mktime —— 两边一起随 TZ 漂移,于是测试在任何时区都自洽、
    永远是绿的,而账单其实会因为部署机器换地方就算错月份。
    一致性证明不了正确性:两边都得钉死在账单时区上才有意义。
    """
    return datetime(*args, tzinfo=BILLING_TZ).timestamp()          # type: ignore[arg-type]


T0 = bkk(2026, 9, 5, 10, 0)


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


def rec(**kw) -> AuditRecord:
    base = dict(tenant="h", user="u1", component="documents", task="extract",
                sensitivity="normal", tier="cheap", model="m",
                tokens_in=100, tokens_out=20, cost_usd=0.001,
                latency_ms=900, status="ok", ts=T0)
    base.update(kw)
    return AuditRecord(**base)


def fresh() -> AuditLog:
    return AuditLog(os.path.join(tempfile.mkdtemp(), "t.db"))


# ═══════════════════════════════════════════════ 不可破边界：只存元数据

def test_content_fields_rejected() -> None:
    """任何疑似内容的字段名都必须被拒绝。"""
    for f in ("prompt", "input", "content", "output", "completion",
              "messages", "document", "response", "text", "payload", "raw"):
        expect_raises(ContentLeakError,
                      lambda f=f: assert_no_content({"tenant": "h", f: "客户的合同全文"}),
                      "内容边界破了：字段 %r 没被拒绝 —— 客户内容会进审计表" % f)

    # 大小写不敏感 —— 否则 Prompt / PROMPT 就能绕过去
    for f in ("Prompt", "PROMPT", "Input", "CoNtEnT"):
        expect_raises(ContentLeakError,
                      lambda f=f: assert_no_content({f: "x"}),
                      "内容边界破了：%r 大小写变体绕过了闸门" % f)


def test_long_text_rejected() -> None:
    """自由文本字段里塞长内容也要拦 —— 字段名合法不代表内容合法。"""
    expect_raises(ContentLeakError,
                  lambda: assert_no_content({"routing_reason": "x" * 501}),
                  "501 字符的自由文本没被拒绝")
    # 边界:恰好 500 应放行
    try:
        assert_no_content({"routing_reason": "x" * 500})
    except ContentLeakError:
        FAILS.append("边界错：恰好 500 字符被拒了")


def test_legitimate_metadata_passes() -> None:
    """负对照：合法元数据必须放行。

    没有这条，「什么都拒绝」也能让上面所有测试全绿 —— 那个闸门就是废的。
    """
    try:
        assert_no_content({
            "tenant": "hotel-x", "user": "staff-07", "component": "documents",
            "task": "extract", "sensitivity": "normal", "tier": "cheap",
            "model": "some-model", "tokens_in": 3200, "tokens_out": 450,
            "cost_usd": 0.0021, "latency_ms": 1840, "status": "ok",
            "routing_reason": "task 'extract' 命中规则 #1", "ts": T0,
        })
    except ContentLeakError as e:
        FAILS.append("负对照失败：完整的合法元数据被误拒（%s）。"
                     "如果什么都拒绝，上面的边界测试就证明不了任何事" % e)


def test_record_enforces_boundary_end_to_end() -> None:
    """闸门必须在 record() 这条真实路径上生效，不只是在独立函数里。"""
    log = fresh()
    log.record(rec())        # 正常写入应成功

    # AuditRecord 是 frozen dataclass，字段固定 —— 这本身就是第一道防线。
    # 验证它确实不接受内容字段。
    expect_raises(TypeError, lambda: AuditRecord(  # type: ignore[call-arg]
        tenant="h", user="u", component="c", task="t", sensitivity="normal",
        tier="cheap", model="m", tokens_in=1, tokens_out=1, cost_usd=0.0,
        latency_ms=1, status="ok", prompt="客户合同"),
        "AuditRecord 竟然接受了 prompt 字段 —— 数据结构层面的防线破了")
    log.close()


# ═══════════════════════════════════════════════ 输入校验

def test_record_validation() -> None:
    log = fresh()
    expect_raises(ValueError, lambda: log.record(rec(tenant="")), "空 tenant 没被拒")
    expect_raises(ValueError, lambda: log.record(rec(user="")), "空 user 没被拒")
    expect_raises(ValueError, lambda: log.record(rec(status="weird")), "非法 status 没被拒")
    expect_raises(ValueError, lambda: log.record(rec(tokens_in=-1)), "负 token 数没被拒")
    expect_raises(ValueError, lambda: log.record(rec(cost_usd=-0.1)), "负成本没被拒")
    expect_raises(ValueError, lambda: log.record(rec(latency_ms=-5)), "负延迟没被拒")

    # 负对照:合法记录必须能写进去
    try:
        log.record(rec())
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：合法记录写不进去（%s）" % e)
    log.close()


# ═══════════════════════════════════════════════ 月度统计

def test_monthly_usage() -> None:
    log = fresh()
    for i in range(3):
        log.record(rec(cost_usd=0.01, tier="cheap", component="documents"))
    log.record(rec(cost_usd=0.50, tier="premium", component="assistant"))
    # 落在下个月的一条,不该被算进来
    log.record(rec(cost_usd=99.0, ts=bkk(2026, 10, 1, 0, 0)))

    u = log.monthly_usage("h", "2026-09")
    check(u["calls"] == 4, "月度调用数错：期望 4 得到 %r" % u["calls"])
    check(abs(u["cost_usd"] - 0.53) < 1e-9, "月度成本错：期望 0.53 得到 %r" % u["cost_usd"])
    check(u["by_tier"]["cheap"]["calls"] == 3, "按 tier 分组错：%r" % u["by_tier"])
    check(u["by_tier"]["premium"]["calls"] == 1, "按 tier 分组错：%r" % u["by_tier"])
    check(set(u["by_component"]) == {"documents", "assistant"},
          "按组件分组错：%r" % u["by_component"])

    # 负对照:换一个月份必须得到不同结果 —— 否则时间过滤是死的
    u10 = log.monthly_usage("h", "2026-10")
    check(u10["calls"] == 1 and abs(u10["cost_usd"] - 99.0) < 1e-9,
          "负对照失败：10 月的统计不该等于 9 月的（得到 %r）" % u10)

    # 负对照:换一个租户必须得到空 —— 否则租户隔离是死的
    other = log.monthly_usage("另一家", "2026-09")
    check(other["calls"] == 0,
          "租户隔离破了：查别的租户竟然返回了 %d 条" % other["calls"])

    expect_raises(ValueError, lambda: log.monthly_usage("h", "2026/09"), "非法月份格式没被拒")
    expect_raises(ValueError, lambda: log.monthly_usage("h", "2026-13"), "13 月没被拒")
    log.close()


def test_monthly_usage_independent_of_server_tz() -> None:
    """账单月份不能随服务器时区漂。

    这是真实 bug 的回归测试:月份边界原先用 time.mktime()(本地时区)算,
    而 ts 存的是 UTC epoch。实测同一笔「曼谷时间 2026-10-01 06:00」的调用,
    服务器 TZ=UTC 时被算进 9 月账单,TZ=Asia/Bangkok 时算进 10 月 ——
    换个部署机器,客户账单就变,且没有任何东西报错。

    做法是**真的切换进程时区**再跑同一套断言。只在测试内部构造时间戳、
    不动 TZ 的写法抓不到这个 bug —— 原测试正是那样,所以它一直是绿的。
    """
    if not hasattr(time, "tzset"):                    # Windows 没有,跳过
        return
    # 曼谷时间 10-01 06:00 —— 在 UTC 下是 09-30 23:00,正好跨月,最能暴露问题
    ts = bkk(2026, 10, 1, 6, 0)
    old_tz = os.environ.get("TZ")
    results = {}
    try:
        for tz in ("UTC", "Asia/Bangkok", "Pacific/Midway", "Pacific/Kiritimati"):
            os.environ["TZ"] = tz
            time.tzset()
            log = fresh()
            log.record(rec(cost_usd=1.0, ts=ts))
            results[tz] = (log.monthly_usage("h", "2026-09")["calls"],
                           log.monthly_usage("h", "2026-10")["calls"])
            log.close()
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()

    for tz, got in results.items():
        check(got == (0, 1),
              "服务器 TZ=%s 时账单月份算错：期望 9月0笔/10月1笔，得到 %r —— "
              "账单不该随部署机器的时区变" % (tz, got))
    check(len(set(results.values())) == 1,
          "不同服务器时区给出了不同的账单：%r" % results)


# ═══════════════════════════════════════════════ 隐私事后核查

def test_sensitive_off_local_detection() -> None:
    """sensitivity=high 却没走 local 的调用必须被查出来。

    这是隐私承诺的**事后核查**，与路由引擎的事前拦截互为双保险。
    """
    log = fresh()
    log.record(rec(sensitivity="high", tier="local"))     # 正常
    log.record(rec(sensitivity="normal", tier="cheap"))   # 正常
    check(log.sensitive_calls_off_local("h") == [],
          "正常数据下不该报警")

    # 制造一条违规:high 却走了 cheap
    log.record(rec(sensitivity="high", tier="cheap", user="u-bad"))
    hits = log.sensitive_calls_off_local("h")
    check(len(hits) == 1 and hits[0]["user"] == "u-bad",
          "隐私事后核查失效：high 走 cheap 没被查出来（得到 %r）" % hits)

    # 负对照:别的租户的违规不该串进来
    check(log.sensitive_calls_off_local("另一家") == [],
          "租户隔离破了：查别的租户返回了本租户的违规记录")
    log.close()


# ═══════════════════════════════════════════════ main

TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    for t in TESTS:
        t()
    if FAILS:
        print("✗ %d 个测试断言失败" % len(FAILS), file=sys.stderr)
        for f in FAILS:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ audit 测试全部通过（%d 个测试函数，含内容边界与租户隔离的负对照）"
          % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
