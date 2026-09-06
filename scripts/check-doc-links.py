#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docs/ 里的站内相对链接必须指向真实存在的文件。

## 为什么需要这个

这些文档的判定标准是「**一个明天入职的新员工，读完能不能直接上岗**」。
一条死链会让他当场卡住 —— 而**没有任何东西会自动发现它**：
Markdown 不校验链接，CI 不渲染文档，写的人自己不会去点。

改文件名、挪目录、删掉一份草稿，都会悄悄留下死链。

## 只查相对链接

外链（http/https）不查 —— 网络状态不该决定 CI 红绿，
而且一个会因为对方站点抽风而变红的检查，很快就会被人加 `|| true`。

    python3 scripts/check-doc-links.py
    python3 scripts/check-doc-links.py --self-test
"""

from __future__ import annotations

import os
import re
import sys

RED = "\033[31m"; GRN = "\033[32m"; OFF = "\033[0m"

# [文字](目标) —— 排除 http(s) 与纯锚点
_LINK = re.compile(r'\[[^\]]*\]\((?!https?://|#)([^)\s]+)\)')


def check_file(path: str) -> list[str]:
    """返回该文件里的死链说明。"""
    errors = []
    base = os.path.dirname(path)
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    for m in _LINK.finditer(source):
        target = m.group(1).split("#")[0]        # 砍掉锚点
        if not target:                           # 纯锚点,上面已排除,兜底
            continue
        resolved = os.path.normpath(os.path.join(base, target))
        if not os.path.exists(resolved):
            line = source.count("\n", 0, m.start()) + 1
            errors.append("第 %d 行:%s → 不存在" % (line, target))
    return errors


def walk(root: str = "docs") -> tuple[int, int, list[str]]:
    files = links = 0
    problems: list[str] = []
    for dirpath, _dirs, names in os.walk(root):
        for n in sorted(names):
            if not n.endswith(".md"):
                continue
            p = os.path.join(dirpath, n)
            files += 1
            with open(p, encoding="utf-8") as fh:
                links += len(_LINK.findall(fh.read()))
            for e in check_file(p):
                problems.append("%s %s" % (p, e))
    return files, links, problems


# ---------------------------------------------------------------- 自检

def self_test() -> int:
    """断言这条判据确实会红,而且不会误报。"""
    import tempfile

    failures = []
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "sub"), exist_ok=True)
        with open(os.path.join(d, "sub", "real.md"), "w", encoding="utf-8") as fh:
            fh.write("# 存在的文件\n")

        # 负对照:指向不存在的文件 → 必须红
        bad = os.path.join(d, "bad.md")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("见 [那份文档](sub/missing.md)\n")
        if not check_file(bad):
            failures.append("对「指向不存在的文件」没有反应 —— 这条判据是死的")

        # 正对照 1:指向真实文件 → 必须绿
        good = os.path.join(d, "good.md")
        with open(good, "w", encoding="utf-8") as fh:
            fh.write("见 [那份文档](sub/real.md)\n")
        if check_file(good):
            failures.append("对真实存在的相对链接误报了 —— 假阳性")

        # 正对照 2:带锚点的真实文件 → 必须绿(锚点要被砍掉)
        anchored = os.path.join(d, "anchored.md")
        with open(anchored, "w", encoding="utf-8") as fh:
            fh.write("见 [某一节](sub/real.md#some-section)\n")
        if check_file(anchored):
            failures.append("带 #锚点 的真实链接被误报 —— 锚点没有被砍掉")

        # 正对照 3:外链与纯锚点 → 不该被检查
        external = os.path.join(d, "ext.md")
        with open(external, "w", encoding="utf-8") as fh:
            fh.write("[站点](https://idoris.ai/nope) 与 [本页某节](#anchor)\n")
        if check_file(external):
            failures.append("外链或纯锚点被当成站内链接检查了 —— "
                            "会因为对方站点抽风而变红,然后被人加 || true")

    if failures:
        print("%s✗ 自检失败%s" % (RED, OFF), file=sys.stderr)
        for f in failures:
            print("    " + f, file=sys.stderr)
        return 1
    print("%s✓%s 文档链接检查的对照通过（会红、且不误报）" % (GRN, OFF))
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    if self_test():
        return 1
    files, links, problems = walk()
    if problems:
        print("%s✗ %d 条死链%s" % (RED, len(problems), OFF), file=sys.stderr)
        for p in problems:
            print("    " + p, file=sys.stderr)
        return 1
    print("%s✓%s 文档链接完好（%d 个 .md，%d 条站内链接）" % (GRN, OFF, files, links))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
