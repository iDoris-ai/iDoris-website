#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris Assistant — 启动断言：环境里有出网追踪配置就**拒绝启动**。

## 为什么需要这个模块

P0 阻塞项 #1 的核查结论（见 `docs/agent/progress.md`）：

> LangGraph 经 `langchain-core` 传递依赖 `langsmith`，包一定会被装上。
> socket 层实测：**不设任何环境变量时 0 次外部连接**；
> 但设 `LANGSMITH_TRACING=true` 时**确实会连** `api.smith.langchain.com`。

也就是说 —— **风险不在库，在部署配置。**

客户的会议内容是我们碰得到的最敏感的数据。一台机器上多一个环境变量，
转写稿就开始往外发，而且**不会有任何东西提醒你**：日志照常、功能照常、
测试照常绿。这正是本轮反复栽的那个形状。

## 为什么是「拒绝启动」而不是「打警告」

**打警告没人看。** 一条启动日志里的 WARNING，在真实运维里等于不存在 ——
尤其是它出现在容器启动的前两秒、后面还有几百行输出的时候。

而这件事的失败模式是**静默的数据外流**：出事时没人知道，
等发现的时候数据已经在别人的服务器上了，撤不回来。

所以这里的选择是**炸**。启动不了，人一定会看；数据流出去了，人不一定会知道。

## 为什么是前缀扫描而不是白名单点名

点名一串已知变量（`LANGCHAIN_TRACING_V2`、`LANGSMITH_API_KEY`……）
看起来更精确，实际上是**失败开放**：langsmith 下个版本加一个新变量名，
我们的清单不会自己长出来，于是静默漏过。

这里反过来 —— 扫 `LANGCHAIN_` / `LANGSMITH_` 前缀，
**认不出来的一律拒绝**，要放行必须显式写进 `KNOWN_HARMLESS`。
误拒的代价是运维多看一行报错；漏放的代价是客户的会议记录出境。不对称。

## 用法

    from egress_guard import assert_no_tracing_env
    assert_no_tracing_env()        # 放在 Assistant 进程的最开头

    python3 egress_guard.py --self-test
    python3 egress_guard.py --check      # 给部署脚本用，退出码即结论

## 这个模块**不**保证什么

它只管环境变量。它**挡不住**：

- 代码里直接传 `callbacks=[LangChainTracer()]` —— 那是代码审查的事
- 别的库自己的遥测（各自另有开关）
- 环境干净但网络出口没关 —— 出网控制是部署层的事，见 `tools/verify/`

**这是一道闸门，不是全部防线。** 写清楚它管到哪为止，
比让人以为「有这个就安全了」要紧。
"""

from __future__ import annotations

import os
import sys

# 扫描的前缀。langsmith / langchain 的遥测配置全部落在这两个下面。
WATCHED_PREFIXES = ("LANGCHAIN_", "LANGSMITH_")

# 已知无害、可以放行的变量。**加进来之前想清楚它会不会导致出网。**
#
# 刻意留空并显式写出来 —— 一个空集合加一句「为什么是空的」，
# 比没有这个常量更能挡住下一个人随手往里加东西。
KNOWN_HARMLESS: frozenset[str] = frozenset()

# 这些是明确的开关：值为假就无害。其余带前缀的变量只要非空就拒绝。
_TOGGLES = frozenset({
    "LANGCHAIN_TRACING",
    "LANGCHAIN_TRACING_V2",
    "LANGSMITH_TRACING",
    "LANGSMITH_TRACING_V2",
})

# 严格的「真」值。刻意不用 bool(str) —— 那样 "false" 是真的。
_TRUTHY = frozenset({"1", "true", "yes", "on", "t", "y"})


class EgressConfigError(RuntimeError):
    """环境里有会导致出网的追踪配置。**拒绝启动。**"""


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in _TRUTHY


def scan_env(env: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """返回 [(变量名, 拒绝理由)]。空列表 = 环境干净。

    可以传 env 进来，方便测试和给部署脚本预检别的机器的环境。
    """
    src = os.environ if env is None else env
    hits: list[tuple[str, str]] = []

    for name in sorted(src):
        if not name.startswith(WATCHED_PREFIXES):
            continue
        if name in KNOWN_HARMLESS:
            continue
        value = src[name]
        if not value.strip():
            continue                     # 空值等于没设
        if name in _TOGGLES:
            if _is_truthy(value):
                hits.append((name, "追踪开关被打开（值 %r）" % value))
            continue
        hits.append((name, "带追踪前缀且非空（值长度 %d）" % len(value)))

    return hits


def format_report(hits: list[tuple[str, str]]) -> str:
    lines = [
        "拒绝启动：环境里有会把客户数据发到外部的追踪配置。",
        "",
    ]
    for name, why in hits:
        lines.append("  - %s：%s" % (name, why))
    lines += [
        "",
        "为什么这会炸而不是打个警告：",
        "  客户的会议内容是我们碰得到的最敏感的数据。这些变量一旦生效，",
        "  转写稿会被发到 api.smith.langchain.com，而且不会有任何东西提醒你 ——",
        "  日志照常、功能照常、测试照常绿。等发现时数据已经在别人的服务器上，撤不回来。",
        "",
        "怎么处理：",
        "  1. 确认这台机器上确实不需要它们：unset 掉，或从 compose/k8s 的 env 里删掉",
        "  2. 如果你确信某个变量无害，把它加进 egress_guard.KNOWN_HARMLESS，",
        "     并在那里写清楚为什么 —— 让下一个人能看懂，而不是只看到一个名字",
        "",
        "注意变量值本身没有打印出来（可能含 API key）。",
    ]
    return "\n".join(lines)


def assert_no_tracing_env(env: dict[str, str] | None = None) -> None:
    """环境不干净就抛 EgressConfigError。**放在进程最开头。**"""
    hits = scan_env(env)
    if hits:
        raise EgressConfigError(format_report(hits))


# ---------------------------------------------------------------- 自检

def _selftest() -> int:
    fails: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            fails.append(msg)

    # 干净环境放行
    check(scan_env({"PATH": "/bin", "HOME": "/root"}) == [], "干净环境被误拒")

    # 开关打开 → 拒绝
    for v in ("true", "1", "TRUE", "yes", "on"):
        check(len(scan_env({"LANGSMITH_TRACING": v})) == 1,
              "LANGSMITH_TRACING=%r 没被拒" % v)

    # 开关关闭 → 放行（否则运维为了启动会去删配置管理里的行，反而更糟）
    for v in ("false", "0", "no", "off", ""):
        check(scan_env({"LANGSMITH_TRACING": v}) == [],
              "LANGSMITH_TRACING=%r 被误拒 —— 关掉的开关是无害的" % v)

    # API key / endpoint 只要非空就拒绝，不看真假值
    check(len(scan_env({"LANGSMITH_API_KEY": "ls__abc"})) == 1, "API key 没被拒")
    check(len(scan_env({"LANGCHAIN_ENDPOINT": "https://x"})) == 1, "endpoint 没被拒")

    # 失败关闭:没见过的带前缀变量也要拒
    check(len(scan_env({"LANGSMITH_SOMETHING_NEW_IN_2027": "x"})) == 1,
          "认不出来的带前缀变量被放行了 —— 这是失败开放")

    # 不相干的变量不碰
    check(scan_env({"MYLANGCHAIN_X": "1", "LANG": "en_US.UTF-8"}) == [],
          "误伤了不带前缀的变量")

    # 报错信息里不能出现密钥值
    try:
        assert_no_tracing_env({"LANGSMITH_API_KEY": "ls__SECRET_VALUE"})
        fails.append("assert_no_tracing_env 没抛")
    except EgressConfigError as e:
        check("SECRET_VALUE" not in str(e),
              "报错信息里泄露了变量值 —— 那是 API key")
        check("LANGSMITH_API_KEY" in str(e), "报错信息里没说是哪个变量")

    if fails:
        print("✗ %d 项失败" % len(fails), file=sys.stderr)
        for f in fails:
            print("    " + f, file=sys.stderr)
        return 1
    print("✓ egress_guard 自检通过")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return _selftest()
    if "--check" in argv:
        hits = scan_env()
        if hits:
            print(format_report(hits), file=sys.stderr)
            return 1
        print("✓ 环境干净：没有 LANGCHAIN_/LANGSMITH_ 追踪配置")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
