#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""/hello 的三封信必须结构平行。

## 为什么单独写这一条

`onboarding-day1.md` 和 `playbook-customer-journey.md` 都向新人担保:
**「三语版本内容一致，发哪一版看对方习惯」**。

但那三封信是三个独立的 `<iframe srcdoc>` 文档,**完全不用 `data-zh`/`data-th`** ——
`check-html.py` 的三语判据**够不着它们**。也就是说,那句担保此前
**没有任何东西在它变假时报警**。

这正是本仓库反复警惕的形状:一个看起来被守住、实际没有的承诺。
(PR-Daemon 在 #58 的 review 里指出了这一点。)

## 它查什么、不查什么

**查**:三封信的段落数、折叠块数、图片数、链接数**必须一致**。
改了英文忘了改泰文,这一条立刻红 —— 而这正是今天差点发生两次的事。

**不查**:翻译质量、语义是否真的对应。那需要人。
**这条判据担保的是「没有漏改一封」,不是「翻译是对的」** —— 别把它当成后者。

    python3 scripts/check-letters.py
    python3 scripts/check-letters.py --self-test
"""

from __future__ import annotations

import html
import re
import sys

RED = "\033[31m"; GRN = "\033[32m"; OFF = "\033[0m"

PAGE = "site/hello/index.html"
LANGS = ("en", "zh", "th")

# 结构维度。**每一维都是「改一封忘另一封」会立刻错开的东西。**
DIMS = (
    ("段落 <p>", r"<p[\s>]"),
    ("折叠块 <details>", r"<details[\s>]"),
    ("图片 <img>", r"<img[\s>]"),
    ("链接 <a>", r"<a[\s>]"),
)


def extract(source: str, lang: str) -> str | None:
    """取出某一语种那封信的 srcdoc 正文(已反转义)。"""
    m = re.search(r'data-mail="%s"(.*?)(?=<div class="letter"|</section)' % lang,
                  source, re.S)
    if not m:
        return None
    sd = re.search(r'srcdoc="(.*?)"\s*>', m.group(1), re.S)
    return html.unescape(sd.group(1)) if sd else None


def check(source: str) -> list[str]:
    errors: list[str] = []
    bodies = {}
    for lang in LANGS:
        body = extract(source, lang)
        if body is None:
            errors.append("找不到 %s 那封信 —— 三语少了一封" % lang)
            continue
        bodies[lang] = body
    if len(bodies) != len(LANGS):
        return errors

    for name, pat in DIMS:
        counts = {l: len(re.findall(pat, b)) for l, b in bodies.items()}
        if len(set(counts.values())) > 1:
            errors.append(
                "%s 数量不一致:%s —— **改了一封忘了另一封**。"
                "两处文档都向新人担保「三语版本内容一致」"
                % (name, "、".join("%s=%d" % (l, counts[l]) for l in LANGS)))
    return errors


# ---------------------------------------------------------------- 自检

def _page(en_p: int, zh_p: int, th_p: int) -> str:
    def letter(lang, n):
        body = "".join("&lt;p&gt;x&lt;/p&gt;" for _ in range(n))
        return ('<div class="letter" data-mail="%s">\n'
                '  <iframe srcdoc="%s"></iframe>\n</div>\n' % (lang, body))
    return ("<section>\n" + letter("en", en_p) + letter("zh", zh_p)
            + letter("th", th_p) + "</section>\n")


def self_test() -> int:
    failures = []

    # 正对照:三封结构一致 → 必须绿
    if check(_page(7, 7, 7)):
        failures.append("对结构一致的三封信误报了 —— 假阳性")

    # 负对照:泰文少一段(最常见的失败:改了中英忘了泰)→ 必须红
    if not check(_page(7, 7, 6)):
        failures.append("对「泰文少一段」没有反应 —— 这条判据是死的，"
                        "而它守的正是「改一封忘另一封」")

    # 负对照:英文多一段
    if not check(_page(8, 7, 7)):
        failures.append("对「英文多一段」没有反应")

    # 负对照:整封信不见了
    missing = _page(7, 7, 7).replace('data-mail="th"', 'data-mail="xx"')
    if not check(missing):
        failures.append("对「少了一封信」没有反应")

    if failures:
        print("%s✗ 自检失败%s" % (RED, OFF), file=sys.stderr)
        for f in failures:
            print("    " + f, file=sys.stderr)
        return 1
    print("%s✓%s 三封信判据的对照通过（会红、且不误报）" % (GRN, OFF))
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    if self_test():
        return 1
    with open(PAGE, encoding="utf-8") as fh:
        problems = check(fh.read())
    if problems:
        print("%s✗ 三封信结构不平行%s" % (RED, OFF), file=sys.stderr)
        for p in problems:
            print("    " + p, file=sys.stderr)
        return 1
    print("%s✓%s 三封信结构平行（%s，逐维一致）"
          % (GRN, OFF, " · ".join(n for n, _ in DIMS)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
