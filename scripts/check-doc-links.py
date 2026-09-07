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


def check_file(path: str, root: str = ".") -> list[str]:
    """返回该文件里的死链说明。

    **跑出仓库的相对链接一律算错,哪怕它在本机能打开。**

    这一条是被 CI 教会的:`docs/ROADMAP.md` 里有一条 `../../ai-atlas/BACKLOG.md`,
    在我本机是绿的 —— 因为旁边正好 checkout 了那个兄弟仓库。
    CI 上、以及任何一个读者那里,它都是死链。
    **一个结果取决于「你旁边还放了什么」的检查,是不可信的。**
    """
    errors = []
    base = os.path.dirname(path)
    root_abs = os.path.abspath(root)
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    for m in _LINK.finditer(source):
        target = m.group(1).split("#")[0]        # 砍掉锚点
        if not target:                           # 纯锚点,上面已排除,兜底
            continue
        line = source.count("\n", 0, m.start()) + 1
        resolved = os.path.normpath(os.path.join(base, target))
        abs_resolved = os.path.abspath(resolved)
        if os.path.commonpath([abs_resolved, root_abs]) != root_abs:
            errors.append(
                "第 %d 行:%s → **跑出仓库了**。别人 clone 下来打不开 —— "
                "跨仓库要用完整 URL,不是相对路径" % (line, target))
            continue
        if not os.path.exists(resolved):
            errors.append("第 %d 行:%s → 不存在" % (line, target))
    return errors


def walk(scan_dir: str = "docs", repo_root: str = ".") -> tuple[int, int, list[str]]:
    """扫 `scan_dir` 下的 .md,链接的合法范围是 `repo_root`。

    **这两个不是一回事。** 第一版把它们当成了同一个参数,于是
    `docs/business/../../tools/verify/`(指向仓库内的 tools/)被判成「跑出仓库」——
    而它完全合法。这个 bug 是跑变异测试时才现形的:
    我改回一条真死链去验判据会不会红,结果多报了两条无辜的。
    """
    files = links = 0
    problems: list[str] = []
    for dirpath, _dirs, names in os.walk(scan_dir):
        for n in sorted(names):
            if not n.endswith(".md"):
                continue
            p = os.path.join(dirpath, n)
            files += 1
            with open(p, encoding="utf-8") as fh:
                links += len(_LINK.findall(fh.read()))
            for e in check_file(p, repo_root):
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
        if not check_file(bad, root=d):
            failures.append("对「指向不存在的文件」没有反应 —— 这条判据是死的")

        # 正对照 1:指向真实文件 → 必须绿
        good = os.path.join(d, "good.md")
        with open(good, "w", encoding="utf-8") as fh:
            fh.write("见 [那份文档](sub/real.md)\n")
        if check_file(good, root=d):
            failures.append("对真实存在的相对链接误报了 —— 假阳性")

        # 正对照 2:带锚点的真实文件 → 必须绿(锚点要被砍掉)
        anchored = os.path.join(d, "anchored.md")
        with open(anchored, "w", encoding="utf-8") as fh:
            fh.write("见 [某一节](sub/real.md#some-section)\n")
        if check_file(anchored, root=d):
            failures.append("带 #锚点 的真实链接被误报 —— 锚点没有被砍掉")

        # 负对照 2:跑出仓库根的相对链接 → 必须红,**哪怕那个文件真的存在**。
        # 这一格是 CI 教的:本机旁边 checkout 了兄弟仓库时,它是绿的。
        outside = os.path.join(d, "escape.md")
        os.makedirs(os.path.join(d, "repo"), exist_ok=True)
        with open(os.path.join(d, "sibling.md"), "w", encoding="utf-8") as fh:
            fh.write("# 仓库外真实存在的文件\n")
        inside = os.path.join(d, "repo", "doc.md")
        with open(inside, "w", encoding="utf-8") as fh:
            fh.write("见 [兄弟仓库](../sibling.md)\n")
        if not check_file(inside, root=os.path.join(d, "repo")):
            failures.append("对「跑出仓库根」没有反应 —— "
                            "本机旁边有 checkout 时会假绿,CI 上才发现")
        del outside

        # 正对照 3:外链与纯锚点 → 不该被检查
        external = os.path.join(d, "ext.md")
        with open(external, "w", encoding="utf-8") as fh:
            fh.write("[站点](https://idoris.ai/nope) 与 [本页某节](#anchor)\n")
        if check_file(external, root=d):
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
