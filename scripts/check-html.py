#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML 结构自检 —— 拦「浏览器不会喊、deploy.sh 也看不见」的那类坏。

为什么需要它:deploy.sh 原有的检查全是文本级的(grep 断链、grep i18n 脚本、比文件大小),
一行 HTML 都不解析。2026-09-05 我们真栽了一次:/pricing 的横幅里写成

    data-zh="仅供参考<span class="sub">副行</span>"

属性本身是双引号定界的,裸引号在 class= 后面就把属性截断了,页面结构从那一行起整个塌掉
(<p> 被 </span> 关掉,连锁到 <div>/<section>/<main>/<body>)。而 `deploy.sh --check`
**全绿** —— 它不解析 HTML,拦不住。浏览器也不喊:HTML 是容错的,它照样渲染一个错的树。

这就是这个脚本存在的理由:只查两件文本级检查永远看不见、而出错时不会有人告诉你的事。

两条判据,都是承重的:

  1. 整篇标签平衡。开合不匹配、有开无合、有合无开都算。
  2. data-zh / data-th 属性值内的尖括号配对。这两个属性的值是 i18n-v2.js 要塞进
     innerHTML 的 HTML 片段,里面合法地带 <b> <span> 之类;但值本身被双引号包着,
     所以值里一旦出现裸 " 就会截断属性,而截断的残骸(如 `<span class=`)会留下一个
     没有闭合的 <。

**故意不做第三条**:「把属性值当独立片段重新解析、看标签是否平衡」。评审在真实 bug 上
验过——它对这个 bug 是瞎的:截断后残留的 `<span class=` 根本不成其为一个 start tag,
解析器直接报 0 个失衡。写三条会让人以为有三重保险,实际只有两重。宁可少一条,也不要
一条永远绿的护栏。

--self-test 是正对照:把两种已知的坏形状喂进来,断言每条判据**确实会变红**。
一条不会变红的检查等于没有检查,而它看起来和真检查一模一样 —— CI 里每次都跑这个对照,
就是防止哪天有人重构完它悄悄变成死代码。

用法:
    scripts/check-html.py [目录]      默认 site/
    scripts/check-html.py --self-test  只跑正对照,不看真文件
"""

import html.parser
import os
import re
import sys

# 这些标签没有闭合标签,不进平衡栈
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

RED = "\033[31m"
GRN = "\033[32m"
OFF = "\033[0m"


class _Balance(html.parser.HTMLParser):
    """判据 1:整篇标签平衡。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append("第 %d 行:多出一个 </%s>,没有对应的开标签"
                               % (self.getpos()[0], tag))
            return
        open_tag, open_line = self.stack.pop()
        if open_tag != tag:
            self.errors.append(
                "第 %d 行:</%s> 关掉的是第 %d 行的 <%s> —— 开合不匹配"
                % (self.getpos()[0], tag, open_line, open_tag))

    def finish(self):
        for tag, line in self.stack:
            self.errors.append("第 %d 行:<%s> 一直没有闭合" % (line, tag))
        return self.errors


def check_tag_balance(source):
    p = _Balance()
    try:
        p.feed(source)
    except Exception as exc:                      # 解析器自己炸了也是一种失衡
        return ["解析中止:%s" % exc]
    return p.finish()


# 双引号与单引号两种定界都要抓。反向引用 \2 保证首尾同种引号。
# 值里不可能再合法出现同种引号,所以 [^"']* 就是「到下一个同种引号为止」——
# 截断发生时,捕获到的正是那截残骸,这正是我们要看的东西。
#
# 单引号这一格是补上的盲区:本仓库目前全用双引号,但只扫双引号意味着哪天
# 有人写了 data-zh='...' ,这条判据对它永远是绿的 —— 而它看起来和真检查一模一样。
_I18N_ATTR = re.compile(r'''data-(zh|th)=("|')([^"']*)\2''')

_TAG_IN_VALUE = re.compile(r'</?([a-zA-Z][a-zA-Z0-9]*)[^>]*>')


def check_i18n_attrs(source):
    """判据 2:data-zh / data-th 属性值内的尖括号必须配对。"""
    errors = []
    for m in _I18N_ATTR.finditer(source):
        which, value = m.group(1), m.group(3)
        line = source.count("\n", 0, m.start()) + 1

        lt, gt = value.count("<"), value.count(">")
        if lt != gt:
            errors.append(
                "第 %d 行 data-%s:尖括号不配对(%d 个 < / %d 个 >)"
                " —— 属性值里很可能有个裸双引号把属性截断了" % (line, which, lt, gt))
            continue

        # 数量对上了,再看嵌套是否成立
        stack = []
        for t in _TAG_IN_VALUE.finditer(value):
            name = t.group(1).lower()
            if name in VOID:
                continue
            if t.group(0).startswith("</"):
                if not stack:
                    errors.append("第 %d 行 data-%s:多出一个 </%s>" % (line, which, name))
                elif stack[-1] != name:
                    errors.append("第 %d 行 data-%s:</%s> 关掉的是 <%s>"
                                  % (line, which, name, stack[-1]))
                    stack.pop()
                else:
                    stack.pop()
            else:
                stack.append(name)
        for name in stack:
            errors.append("第 %d 行 data-%s:<%s> 没有闭合" % (line, which, name))
    return errors


CHECKS = (
    ("整篇标签平衡", check_tag_balance),
    ("data-zh/data-th 属性值尖括号配对", check_i18n_attrs),
)


# ---------------------------------------------------------------- 正对照

_CLEAN = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<p data-zh="中文<b>重点</b>" data-th="ไทย">ok</p>\n'
    # 正确形状:属性值里用 &quot; 转义嵌套引号 —— 这正是 2026-09-05 那个 bug 的修法。
    # 少了这一格,正对照只证明「坏的会红」,不证明「修对了的会绿」。
    '<p data-zh="仅供参考<span class=&quot;sub&quot;>副行</span>" data-th="ไทย">ref</p>\n'
    # 单引号定界的正确形状,守住上面那个补掉的盲区
    "<p data-zh='中文<b>重点</b>' data-th='ไทย'>ok</p>\n"
    '</body>\n</html>\n'
)

# 单引号定界 + 值内标签没闭合。补盲区前这个样本是全绿的。
_SINGLE_QUOTE_UNBALANCED = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    "<p data-zh='中文<b>重点没闭合' data-th='ไทย'>ok</p>\n"
    '</body>\n</html>\n'
)

# 真实翻过的车:属性值里用了裸双引号,属性被截断
_BARE_QUOTE = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<p data-zh="仅供参考<span class="sub">副行</span>">ref only</p>\n'
    '</body>\n</html>\n'
)

# 普通的开合不匹配
_UNBALANCED = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<div><p>丢了一个闭合</div>\n'
    '</body>\n</html>\n'
)


def self_test():
    """断言每条判据确实会变红。一条不会变红的检查等于没有检查。"""
    failures = []

    for name, fn in CHECKS:
        if fn(_CLEAN):
            failures.append("[%s] 在干净样本上误报了 —— 假阳性" % name)

    # 裸引号那一车:两条判据都应该红。这正是 2026-09-05 的真实形状。
    for name, fn in CHECKS:
        if not fn(_BARE_QUOTE):
            failures.append("[%s] 对「属性值裸双引号」没有反应 —— 这条判据是死的" % name)

    # 普通失衡:判据 1 应该红
    if not check_tag_balance(_UNBALANCED):
        failures.append("[整篇标签平衡] 对普通开合不匹配没有反应 —— 这条判据是死的")

    # 单引号定界的失衡:判据 2 应该红(这一格曾经是盲区)
    if not check_i18n_attrs(_SINGLE_QUOTE_UNBALANCED):
        failures.append("[data-zh/data-th 属性值尖括号配对] 对单引号定界的属性没有反应 —— 盲区回来了")

    if failures:
        print("%s✗ 正对照失败 —— 检查本身坏了,它的「绿」不能信%s" % (RED, OFF), file=sys.stderr)
        for f in failures:
            print("    %s" % f, file=sys.stderr)
        return 1

    print("%s✓%s HTML 检查的正对照通过（每条判据都验证过会变红）" % (GRN, OFF))
    return 0


# ---------------------------------------------------------------- 主流程

def main(argv):
    if "--self-test" in argv:
        return self_test()

    root = argv[1] if len(argv) > 1 else "site"
    if not os.path.isdir(root):
        print("%s✗ 目录不存在:%s%s" % (RED, root, OFF), file=sys.stderr)
        return 1

    # 先跑正对照。判据本身坏了的话,后面所有「绿」都不作数 —— 与其给出
    # 一个不能信的绿,不如在这里就红。
    if self_test() != 0:
        return 1

    files, bad = 0, 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in sorted(filenames):
            if not fn.endswith(".html"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            files += 1
            problems = []
            for _name, check in CHECKS:
                problems.extend(check(source))
            if problems:
                bad += 1
                print("  %s%s%s" % (RED, path, OFF), file=sys.stderr)
                for p in problems:
                    print("      %s" % p, file=sys.stderr)

    if bad:
        print("%s✗ %d 个页面结构有问题%s" % (RED, bad, OFF), file=sys.stderr)
        return 1

    print("%s✓%s HTML 结构完好（%d 个页面：标签平衡 + i18n 属性未被截断）"
          % (GRN, OFF, files))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
