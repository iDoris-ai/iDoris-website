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

# 语言码点区段
_THAI = re.compile(r"[\u0e00-\u0e7f]")
_CJK = re.compile(r"[\u4e00-\u9fff]")
# HTML 注释。**必须先剥掉再数** —— 三封信的 srcdoc 里都嵌着中文源码注释,
# 英文信实测有 381 个 CJK 全部来自注释,不剥就会把"英文信含中文"当成正常。
_COMMENT = re.compile(r"<!--.*?-->", re.S)

# 正文语言下限。取得很松 —— 这一维要抓的是"整封换成了别的语言",
# 不是"翻译得够不够地道"。定得紧只会在正常改稿时误报,然后被人关掉。
MIN_CODEPOINTS = {"th": 300, "zh": 300}

# 正文语言**上限**:某封信里不该有别的语言。
#
# 这一条补的是两个洞,都是 PR-Daemon 实测出来的:
#
# 1. **「剥注释」那一步原本不承重。** 把 `_COMMENT.sub("", body)` 换成
#    `return body`,整套自检**仍然全绿** —— 因为三条下限都是「至少」,
#    而不剥注释只会让计数**变大**。一个「至少」型的判据,永远测不出
#    「你多算了」这类错误。**量纲不对,对照就是假的。**
#
# 2. 现在三条全是「至少有本语言」,**没有一条说「不该有别的语言」**。
#    「英文信里混进整段中文」是同一族的另一半,此前完全不设防。
#
# 取 50 很宽松:英文信剥注释后实测 **0** 个 CJK,不剥是 **381**。
MAX_FOREIGN = {"en": ("zh", 50)}


def strip_comments(body: str) -> str:
    return _COMMENT.sub("", body)


def count_lang(body: str, lang: str) -> int:
    pat = _THAI if lang == "th" else _CJK
    return len(pat.findall(strip_comments(body)))


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

    # 第五维:正文真的是那个语言。
    #
    # **前四维只比结构,语言不在其中。** 把英文信整段塞进泰文槽,
    # 四维完全一致 —— 实测两条检查都 exit 0,而泰文码点从 3447 掉到 0。
    # 「泰文版静默留在英文」正是这个仓库反复要抓的那件事,
    # 而信恰恰是两处文档叫新人拿去发给客户的成品。
    for lang, (foreign, ceiling) in MAX_FOREIGN.items():
        n = count_lang(bodies[lang], foreign)
        if n > ceiling:
            errors.append(
                "%s 那封信里有 %d 个%s码点(上限 %d)—— **混进了别的语言**。"
                "注意这个数是**剥掉 HTML 注释之后**的:srcdoc 里嵌着中文源码注释,"
                "不剥的话英文信本身就有 381 个 CJK"
                % (lang, n, "中文" if foreign == "zh" else "泰文", ceiling))

    for lang, floor in MIN_CODEPOINTS.items():
        n = count_lang(bodies[lang], lang)
        if n < floor:
            errors.append(
                "%s 那封信的正文只有 %d 个%s码点(下限 %d)—— "
                "**整封很可能被换成了别的语言**。"
                "注意:数的是剥掉 HTML 注释之后的正文,"
                "因为 srcdoc 里嵌着中文源码注释,不剥会把英文信也算成有中文"
                % (lang, n, "泰文" if lang == "th" else "中文", floor))
    return errors


# ---------------------------------------------------------------- 自检

def _page(en_p: int = 7, zh_p: int = 7, th_p: int = 7,
          th_text: str | None = None, zh_text: str | None = None,
          en_comment: str = "") -> str:
    """造一个三封信的页面样本。

    `th_text`/`zh_text` 覆盖正文语言;`en_comment` 往英文信里塞注释,
    用来验「剥注释」那一格。
    """
    THAI = "สวัสดีครับ " * 40      # ≈ 400 泰文码点,过下限
    CJK = "中文正文内容测试" * 40   # ≈ 320 CJK,过下限
    fill = {"en": "English body ", "zh": zh_text if zh_text is not None else CJK,
            "th": th_text if th_text is not None else THAI}

    def letter(lang, n):
        body = "".join("&lt;p&gt;%s&lt;/p&gt;" % fill[lang] for _ in range(n))
        if lang == "en" and en_comment:
            body = "&lt;!-- %s --&gt;" % en_comment + body
        return ('<div class="letter" data-mail="%s">\n'
                '  <iframe srcdoc="%s"></iframe>\n</div>\n' % (lang, body))
    return ("<section>\n" + letter("en", en_p) + letter("zh", zh_p)
            + letter("th", th_p) + "</section>\n")


def self_test() -> int:
    failures = []

    # 正对照:三封结构一致 → 必须绿
    if check(_page()):
        failures.append("对结构一致的三封信误报了 —— 假阳性")

    # 负对照:泰文少一段(最常见的失败:改了中英忘了泰)→ 必须红
    if not check(_page(7, 7, 6)):
        failures.append("对「泰文少一段」没有反应 —— 这条判据是死的，"
                        "而它守的正是「改一封忘另一封」")

    # 负对照:英文多一段
    if not check(_page(8, 7, 7)):
        failures.append("对「英文多一段」没有反应")

    # 负对照:整封信不见了
    missing = _page().replace('data-mail="th"', 'data-mail="xx"')
    if not check(missing):
        failures.append("对「少了一封信」没有反应")

    # ── 第五维(正文语言)的对照 ────────────────────────────────
    #
    # 这一维是 PR-Daemon 实测出来的缺口:把英文信整段塞进泰文槽,
    # 前四维完全一致、两条检查都 exit 0,而泰文码点从 3447 掉到 0。

    # 负对照:泰文槽里放英文 → 必须红(结构仍然平行,只有语言变了)
    if not check(_page(th_text="This is English, not Thai. ")):
        failures.append("[正文语言] 泰文信整段换成英文却没反应 —— "
                        "这正是「泰文版静默留在英文」,而信是要发给客户的成品")

    # 负对照:中文槽里放英文 → 必须红
    if not check(_page(zh_text="This is English, not Chinese. ")):
        failures.append("[正文语言] 中文信整段换成英文却没反应")

    # 正对照:英文信里嵌**中文源码注释** → 必须绿。
    #
    # ⚠️ **这一格单独存在时并不承重。** PR-Daemon 实测:把 `_COMMENT.sub` 换成
    # `return body`,整套自检仍然全绿 —— 因为当时三条判据全是「至少有 N 个」,
    # 而不剥注释只会让计数变大。**「至少」型的判据测不出「你多算了」。**
    # 真正让这一步承重的是下面那格**上限**对照,两格必须同时在。
    if check(_page(en_comment="这是中文源码注释，不该被当成正文语言" * 30)):
        failures.append("[正文语言] 英文信里的中文**注释**被当成了正文 —— "
                        "没有剥 <!-- --> 就数,真实页面会误判")

    # 负对照:英文信正文里混进整段中文 → 必须红。
    # **这一格才是让「剥注释」承重的那个** ——
    # 去掉剥注释,英文信的 381 个注释 CJK 会撞破上限,这格立刻变红。
    if not check(_page(en_p=7, zh_p=7, th_p=7).replace(
            "English body ", "整段中文混进了英文信里的正文" * 4)):
        failures.append("[正文语言] 英文信里混进整段中文却没反应 —— "
                        "三条下限都是「至少」,没有一条说「不该有别的语言」")

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
    # 维度名由 DIMS 自己列,再补上语言那一维 —— 加了第五维而这句还停在四维,
    # 就是一句过期的断言。
    print("%s✓%s 三封信平行（%s · 正文语言，逐维一致）"
          % (GRN, OFF, " · ".join(n for n, _ in DIMS)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
