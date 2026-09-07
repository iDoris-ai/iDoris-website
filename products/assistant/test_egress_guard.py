#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""egress_guard 的测试。

每条都配负对照 —— 一个「永远放行」或「永远拒绝」的闸门都能让粗糙的测试全绿，
而这两种坏法的后果完全不同：永远拒绝会立刻被运维发现，
**永远放行不会有任何人发现**，直到客户的会议记录已经在别人的服务器上。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from egress_guard import (                                   # noqa: E402
    KNOWN_HARMLESS,
    EgressConfigError,
    assert_no_tracing_env,
    format_report,
    scan_env,
)

HERE = os.path.dirname(os.path.abspath(__file__))
FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


# ══════════════════════════════════════ 真实观测到的那个配置

def test_the_exact_config_that_was_observed_to_leak() -> None:
    """P0 #1 的探针实测:设 LANGSMITH_TRACING=true 时确实会连
    api.smith.langchain.com。这道闸门存在的全部理由就是拦住它。

    如果哪天这条测试变红,说明闸门对**已知会出网的配置**都不管用了。
    """
    hits = scan_env({"LANGSMITH_TRACING": "true"})
    check(len(hits) == 1, "实测会出网的那个配置没被拦住：%r" % hits)
    check(hits[0][0] == "LANGSMITH_TRACING", "拦住的不是那个变量：%r" % hits)


def test_refuses_to_start_not_just_warns() -> None:
    """必须**抛**,不能只返回个结果让调用方自己决定要不要管。

    打警告没人看 —— 一条 WARNING 出现在容器启动的前两秒、
    后面还有几百行输出,在真实运维里等于不存在。
    """
    raised = False
    try:
        assert_no_tracing_env({"LANGSMITH_TRACING": "1"})
    except EgressConfigError:
        raised = True
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("抛的不是 EgressConfigError 而是 %s" % type(e).__name__)
        raised = True
    check(raised, "环境不干净却没有拒绝启动 —— 这道闸门形同虚设")


# ══════════════════════════════════════ 失败关闭

def test_unknown_prefixed_var_is_rejected_not_ignored() -> None:
    """认不出来的带前缀变量必须拒绝。

    点名一串已知变量看起来更精确,实际是**失败开放**:
    langsmith 下个版本加个新变量名,我们的清单不会自己长出来,于是静默漏过。
    误拒的代价是运维多看一行报错;漏放的代价是客户的会议记录出境。不对称。
    """
    for name in ("LANGSMITH_SOMETHING_NEW_IN_2027",
                 "LANGCHAIN_FUTURE_TELEMETRY_SINK",
                 "LANGSMITH_OTEL_ENABLED"):
        hits = scan_env({name: "whatever"})
        check(len(hits) == 1, "认不出来的变量 %s 被放行了 —— 这是失败开放" % name)


def test_api_key_rejected_regardless_of_value() -> None:
    """密钥类变量只要非空就拒,不看真假值 —— "false" 也是个能用的 key 名。"""
    for name in ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY",
                 "LANGCHAIN_ENDPOINT", "LANGSMITH_ENDPOINT"):
        for value in ("ls__abc", "false", "0", "https://api.smith.langchain.com"):
            hits = scan_env({name: value})
            check(len(hits) == 1,
                  "%s=%r 被放行了 —— 这类变量非空就是风险，不是开关" % (name, value))


# ══════════════════════════════════════ 正对照:不能靠「一律拒绝」蒙混

def test_clean_env_passes() -> None:
    """干净环境必须放行。

    没有这条,一个 `return [("X","")]` 的假闸门也能让上面全绿 ——
    然后 Assistant 永远起不来,而我们会以为闸门在工作。
    """
    check(scan_env({"PATH": "/bin", "HOME": "/root", "TZ": "Asia/Bangkok"}) == [],
          "干净环境被误拒")
    try:
        assert_no_tracing_env({"PATH": "/bin"})
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("干净环境竟然拒绝启动（%s）" % e)


def test_disabled_toggle_passes() -> None:
    """关掉的开关是无害的,必须放行。

    否则运维为了把服务起起来,会去删配置管理里的整行 ——
    下次有人想开启追踪时,反而看不到「这里本来是显式关掉的」。
    """
    for v in ("false", "0", "no", "off", "FALSE", " false ", ""):
        check(scan_env({"LANGSMITH_TRACING": v}) == [],
              "LANGSMITH_TRACING=%r 被误拒 —— 关掉的开关无害" % v)


def test_enabled_toggle_rejected_case_insensitively() -> None:
    for v in ("true", "1", "TRUE", "True", "yes", "on", "t", "y", " on "):
        check(len(scan_env({"LANGCHAIN_TRACING_V2": v})) == 1,
              "LANGCHAIN_TRACING_V2=%r 没被拒" % v)


def test_unrelated_vars_untouched() -> None:
    """负对照:不带前缀的变量不能误伤。

    `LANG` 是每台机器都有的 —— 如果闸门用的是子串匹配而不是前缀匹配,
    它会让每一次启动都失败,而这个坏法会被立刻发现、然后被人整条注释掉。
    """
    check(scan_env({"LANG": "en_US.UTF-8", "LANGUAGE": "th",
                    "MYLANGCHAIN_X": "1", "OLD_LANGSMITH_KEY": "x"}) == [],
          "误伤了不带前缀的变量")


# ══════════════════════════════════════ 不泄露密钥

def test_report_never_prints_values() -> None:
    """报错信息会进日志、会被贴进工单。**变量值可能是 API key。**"""
    secret = "ls__THIS_IS_A_SECRET_VALUE"
    report = format_report(scan_env({"LANGSMITH_API_KEY": secret}))
    check(secret not in report, "报错信息里泄露了变量值 —— 那是 API key")
    check("LANGSMITH_API_KEY" in report, "报错信息里没说是哪个变量，没法处理")
    check("SECRET" not in report.upper().replace("KEY", ""),
          "报错信息里疑似残留了值的片段：%r" % report)


# ══════════════════════════════════════ 白名单不能悄悄变大

def test_allowlist_is_empty_by_default() -> None:
    """`KNOWN_HARMLESS` 默认为空。

    这条测试的作用不是「检查一个常量」,是**让往里加东西这件事必须过一次人眼**:
    加了就得改测试,改测试就会在 diff 里被看见。
    悄悄加一个名字进白名单,是这道闸门最可能的失效方式。
    """
    check(KNOWN_HARMLESS == frozenset(),
          "KNOWN_HARMLESS 不再为空：%r —— 每一项都要写清楚为什么无害" % set(KNOWN_HARMLESS))


# ══════════════════════════════════════ 闸门必须真的被调用

def test_guard_is_actually_wired_into_the_entry_point() -> None:
    """**一道没人调用的闸门等于不存在。**

    这是最容易白写的一类安全代码:模块写得很漂亮、测试全绿、
    然后没有任何一条启动路径调用它。
    所以这里直接检查入口文件里有那一句。
    """
    entry = os.path.join(os.path.dirname(HERE), "demo_meeting_to_tasks.py")
    if not os.path.exists(entry):
        FAILS.append("找不到入口文件 %s —— 这条测试的前提没了" % entry)
        return
    src = open(entry, encoding="utf-8").read()
    check(re.search(r"^\s*assert_no_tracing_env\(\)", src, re.M) is not None,
          "入口 %s 没有调用 assert_no_tracing_env() —— 闸门没被接上，等于不存在"
          % os.path.basename(entry))


def test_check_mode_exit_code() -> None:
    """`--check` 给部署脚本用,退出码就是结论 —— 部署脚本不会读人话。"""
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith(("LANGCHAIN_", "LANGSMITH_"))}
    r = subprocess.run([sys.executable, os.path.join(HERE, "egress_guard.py"), "--check"],
                       env=clean, capture_output=True)
    check(r.returncode == 0, "干净环境下 --check 退出码不是 0：%d" % r.returncode)

    dirty = dict(clean, LANGSMITH_TRACING="true")
    r2 = subprocess.run([sys.executable, os.path.join(HERE, "egress_guard.py"), "--check"],
                        env=dirty, capture_output=True)
    check(r2.returncode != 0, "脏环境下 --check 竟然返回 0 —— 部署脚本会直接放行")
    check(b"LANGSMITH_TRACING" in r2.stderr, "--check 没说是哪个变量")


# ══════════════════════════════════════ main

TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    for t in TESTS:
        t()
    if FAILS:
        print("✗ %d 个测试断言失败" % len(FAILS), file=sys.stderr)
        for f in FAILS:
            print("    " + f, file=sys.stderr)
        return 1
    print("✓ egress_guard 测试全部通过（%d 个测试函数，含失败关闭与正对照）"
          % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
