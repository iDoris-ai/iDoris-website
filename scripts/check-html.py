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


def _iter_tags(source):
    """扫标签,**属性值里的 > 不算标签结束**。

    这一条是这个函数存在的全部理由。用 `<[^>]*>` 去扫,会在属性值里第一个
    `<b>`、`<br>`、`<span>` 处被截断 —— 于是「这个标签有没有 data-th」永远
    看不到后半截,判据变成**几乎每一行都报错**。
    写这条判据时第一版就是那样,74 条全是误报。
    """
    i, n = 0, len(source)
    while i < n:
        if source[i] != "<":
            i += 1
            continue
        if i + 1 < n and not (source[i + 1].isalpha() or source[i + 1] == "/"):
            i += 1
            continue
        j, quote = i + 1, None
        while j < n:
            c = source[j]
            if quote:
                if c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == ">":
                break
            j += 1
        yield i, source[i:j + 1]
        i = j + 1


# 泰文 Unicode 区段 U+0E00–U+0E7F。
_THAI_CP = re.compile(r"[\u0e00-\u0e7f]")

# 允许**不含泰文**的 data-th 值:专名、品牌、域名、纯符号。
# 判定用「归一化后完全相等」,不是子串 —— 子串会把
# "Doris 是我们的吉祥物" 这种真漏译也放过去。
# 结构是 {值: 为什么豁免},**理由必填**,由自检断言非空。
#
# 白名单是这条判据唯一的逃生舱:往里加一句真漏译,检查就会转绿,而且没有声音。
# 堵法不是「钉住条目数」—— 那等于新增一个会随修改而过期的断言,
# 和本仓库把写死的「63 份文档」「九条规则」改成自动计数的方向正好相反。
#
# 堵法是**让加一条豁免必须写下为什么**:理由写不出来的多半不该豁免,
# 而写下的理由会出现在 diff 里,让下一个 reviewer 看得见。
_TH_ALLOW_EXACT = {
    "Doris": "角色名,三语一致",
    "Cherry": "角色名,三语一致",
    "Doris &amp; Cherry": "两个角色名,三语一致",
    "iDoris": "公司名",
    "— iDoris": "公司名带破折号前缀",
    "Issues": "GitHub 界面术语,泰国开发者也用英文原词",
    "GitHub": "产品名",
    "Blog": "导航词,三语站点均保留英文",
    "Meetup": "产品名",
    "✍️ Blog / WeChat": "两个产品名 + emoji,无可译成分",
    "Hyphae · Memory · Context · Skill": "产品名 + 四个技术术语,泰文技术文档同样用英文原词",
    '<a href=&quot;https://blog.mushroom.cv&quot;>blog.mushroom.cv ↗</a>':
        "纯外链,域名不译",
}
# 曾经这里还有一个 `_TH_ALLOW_CONTAINS` 子串白名单(域名那几条)。**已删。**
#
# 理由:它用 `any(k in value)`,于是 `data-th="idoris.ai is completely untranslated"`
# 直接放行 —— 一个子串白名单就是一个逃生舱。而实测它几乎什么都没豁免:
# 24 页全部 data-th 值里,`blog.mushroom.cv` 命中 1、`github.com` 0、`idoris.ai` 0。
# **风险最大的两条承载为零。** 那一条真命中的已并入下面的完全相等白名单。
#
# **一个白名单,一种语义。** 两套判定规则并存,人只会记住松的那套。


def check_thai_actually_thai(source):
    """判据 4:data-th 的值必须真的含泰文,除非在白名单里。

    **判据 3 只保证属性在,不保证里面是泰文。**
    把英文原样抄进 data-th,页面在泰文下看起来"有翻译"、检查也是绿的 ——
    但泰国读者看到的还是英文。这是 PR-Daemon 在 review 里指出的:
    `site/services/index.html` 有一格 `data-th="Discover — AI Discovery Sprint"`,
    一个泰文字符都没有,而当时全绿。

    白名单收的是**专名与品牌**(Doris / Cherry / iDoris / 域名),
    它们在三种语言里本来就该长一样。用「完全相等」判定而不是子串,
    否则 "Doris 是我们的吉祥物" 这种真漏译会被放过去。
    """
    errors = []
    for m in _I18N_ATTR.finditer(source):
        if m.group(1) != "th":
            continue
        value = m.group(3).strip()
        if not value or _THAI_CP.search(value):
            continue
        # 纯符号/纯数字的值不算漏译 —— "2026"、"→"、"01 / Products" 这类
        # 本来就没有可译的东西。**必须放在白名单判断之前** ——
        # 否则第一个写数字或箭头的人会被直接推向白名单,
        # 而白名单是个无声的逃生舱:往里加一条真漏译,检查会转绿。
        if not re.search(r"[A-Za-z]", value):
            continue
        if value in _TH_ALLOW_EXACT:
            continue
        line = source.count("\n", 0, m.start()) + 1
        errors.append(
            "第 %d 行 data-th 里没有一个泰文字符:%r —— "
            "泰国读者看到的还是英文。真是专名就加进 _TH_ALLOW_EXACT"
            % (line, value[:60]))
    return errors


def check_trilingual(source):
    """判据 3:带 data-zh 的元素必须同时带 data-th，反之亦然。

    **站点是中英泰三语,英文是 inline 默认,中泰靠这两个属性换。**
    只写一个的元素,在缺的那个语种下会**静默保持英文** ——
    页面不会报错、不会塌,看起来一切正常,只是那一句没被翻译。
    这类漏译靠肉眼在三个语种间来回切是抓不完的。
    """
    errors = []
    for pos, tag in _iter_tags(source):
        has_zh, has_th = "data-zh=" in tag, "data-th=" in tag
        if has_zh == has_th:
            continue
        line = source.count("\n", 0, pos) + 1
        missing = "data-th" if has_zh else "data-zh"
        errors.append(
            "第 %d 行:有 %s 却没有 %s —— 该语种下这一句会静默留在英文"
            % (line, "data-zh" if has_zh else "data-th", missing))
    return errors


CHECKS = (
    ("整篇标签平衡", check_tag_balance),
    ("data-zh/data-th 属性值尖括号配对", check_i18n_attrs),
    ("三语齐全(有 zh 必有 th)", check_trilingual),
    ("data-th 不是未翻译的英文", check_thai_actually_thai),
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

# 判据 3 的负对照:只写了 data-zh,泰文那一版会静默留在英文
_MISSING_TH = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<p data-zh="只有中文">English</p>\n'
    '</body>\n</html>\n'
)

# 判据 3 的**另一个方向**:只写了 data-th
_MISSING_ZH = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<p data-th="ไทยอย่างเดียว">English</p>\n'
    '</body>\n</html>\n'
)

# 判据 3 最容易写错的地方:属性值里有 <b>/<br>,扫描不能被它截断。
# 这个样本**三语齐全,必须绿**。第一版用 `<[^>]*>` 扫,它是红的 —— 74 条误报。
_TAGS_INSIDE_VALUE = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<p data-zh="中文<b>重点</b>与<br>换行" data-th="ไทย<b>เน้น</b>และ<br>ขึ้นบรรทัด">en<b>x</b></p>\n'
    '</body>\n</html>\n'
)

# 判据 4 的样本
_TH_IS_ENGLISH = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<p data-zh="发现冲刺" data-th="Discovery Sprint">Discovery Sprint</p>\n'
    '</body>\n</html>\n'
)
_TH_REAL = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<p data-zh="发现冲刺" data-th="สปรินต์ค้นพบ">Discovery Sprint</p>\n'
    '</body>\n</html>\n'
)
_TH_PROPER_NOUN = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<p data-zh="Doris" data-th="Doris">Doris</p>\n'
    '</body>\n</html>\n'
)
# 专名混在句子里 —— 必须仍然红
_TH_PROPER_NOUN_IN_SENTENCE = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<p data-zh="Doris 是我们的吉祥物" data-th="Doris is our mascot">Doris is our mascot</p>\n'
    '</body>\n</html>\n'
)

_TH_SYMBOLS_ONLY = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<p data-zh="→" data-th="→">→</p>\n'
    '</body>\n</html>\n'
)
_TH_DIGITS_ONLY = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<p data-zh="2026" data-th="2026">2026</p>\n'
    '</body>\n</html>\n'
)
# 含域名的整句英文 —— 曾经被子串白名单放行,现在必须红
_TH_DOMAIN_IN_SENTENCE = (
    '<!DOCTYPE html>\n<html lang="en" data-lang="en">\n<body>\n'
    '<p data-zh="完全没翻译" data-th="idoris.ai is completely untranslated">x</p>\n'
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

    # 裸引号那一车:**结构类**判据都应该红。这正是 2026-09-05 的真实形状。
    #
    # 判据 4(data-th 里真的有泰文)不在此列 —— 它管的是**内容**不是结构,
    # 对裸引号没有反应是正确的。把它硬塞进这个循环,只会逼人写一条
    # 「为了让自检过」的假逻辑。**每条判据配自己的对照,不套别人的。**
    _STRUCTURAL = ("整篇标签平衡", "data-zh/data-th 属性值尖括号配对", "三语齐全(有 zh 必有 th)")
    for name, fn in CHECKS:
        if name not in _STRUCTURAL:
            continue
        if not fn(_BARE_QUOTE):
            failures.append("[%s] 对「属性值裸双引号」没有反应 —— 这条判据是死的" % name)

    # 判据 4 的负对照:英文原样抄进 data-th → 必须红
    if not check_thai_actually_thai(_TH_IS_ENGLISH):
        failures.append("[data-th 不是未翻译的英文] 对「英文抄进 data-th」没有反应 —— "
                        "泰国读者看到的还是英文,而检查是绿的")

    # 判据 4 的正对照 1:真泰文 → 必须绿
    if check_thai_actually_thai(_TH_REAL):
        failures.append("[data-th 不是未翻译的英文] 对真正的泰文误报了 —— 假阳性")

    # 判据 4 的正对照 2:白名单里的专名 → 必须绿。
    # 少了这一格,Doris/Cherry 这类三语本来就一样的专名会天天报错,
    # 然后这条判据会被人整条注释掉。
    if check_thai_actually_thai(_TH_PROPER_NOUN):
        failures.append("[data-th 不是未翻译的英文] 把白名单里的专名报错了 —— "
                        "天天误报的判据会被人整条注释掉")

    # 白名单每一条都必须写下**为什么** —— 这是它唯一的约束。
    # 不钉条目数(那是会过期的断言),而是让加一条必须写理由,
    # 理由写不出来的多半不该豁免,写下的理由会出现在 diff 里。
    for value, why in _TH_ALLOW_EXACT.items():
        if not why or not why.strip():
            failures.append(
                "[data-th 不是未翻译的英文] 白名单条目 %r 没写豁免理由 —— "
                "白名单是这条判据唯一的逃生舱,进来的每一条都要说清为什么" % value[:40])

    # 判据 4 的正对照 3:纯符号/纯数字 → 必须绿。
    # 少了这一格,第一个写 "2026" 或 "→" 的人会被推向白名单 ——
    # 而白名单是逃生舱,越多人被推进去,这条判据越没用。
    for sample in (_TH_SYMBOLS_ONLY, _TH_DIGITS_ONLY):
        if check_thai_actually_thai(sample):
            failures.append("[data-th 不是未翻译的英文] 把纯符号/纯数字报成漏译了 —— "
                            "会把人推向白名单逃生舱")

    # 判据 4 的负对照 3:**曾经的子串白名单**已删,这一格钉住它别回来。
    if not check_thai_actually_thai(_TH_DOMAIN_IN_SENTENCE):
        failures.append("[data-th 不是未翻译的英文] 含域名的整句英文被放行了 —— "
                        "子串白名单又回来了")

    # 判据 4 的负对照 2:专名**混在句子里**必须仍然红 ——
    # 白名单用「完全相等」而不是子串,就是为了守住这一格。
    if not check_thai_actually_thai(_TH_PROPER_NOUN_IN_SENTENCE):
        failures.append("[data-th 不是未翻译的英文] 白名单退化成了子串匹配 —— "
                        "「Doris is our mascot」这种真漏译会被放过去")

    # 普通失衡:判据 1 应该红
    if not check_tag_balance(_UNBALANCED):
        failures.append("[整篇标签平衡] 对普通开合不匹配没有反应 —— 这条判据是死的")

    # 判据 3:两个方向都要红
    if not check_trilingual(_MISSING_TH):
        failures.append("[三语齐全] 对「只有 data-zh」没有反应 —— 泰文会静默留在英文")
    if not check_trilingual(_MISSING_ZH):
        failures.append("[三语齐全] 对「只有 data-th」没有反应 —— 中文会静默留在英文")

    # 判据 3 的正对照:属性值里带 <b>/<br> 的三语元素**必须绿**。
    # 少了这一格,一个把每行都报错的判据也是「能变红」的 —— 而它毫无用处。
    if check_trilingual(_TAGS_INSIDE_VALUE):
        failures.append(
            "[三语齐全] 对属性值里带 <b>/<br> 的正常三语元素误报了 —— "
            "扫描被属性值里的尖括号截断了(第一版就是这么错的,74 条全假)")

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

    # 默认扫 site **与 subsites**。
    # 只扫 site 的话,子站(agent./model.)不在判据里 —— 而它们同样是"网站"的一部分,
    # 同样用 data-zh/data-th。PR-Daemon 在 review 里指出子站漏了一条活的外链,
    # 而我当时报的是「零残留」—— 因为我只扫了 site/。**范围没覆盖到的地方,绿灯不代表干净。**
    roots = [argv[1]] if len(argv) > 1 and not argv[1].startswith("-") else \
            [d for d in ("site", "subsites") if os.path.isdir(d)]
    root = roots[0]
    if not roots:
        print("%s✗ 没有可扫的目录%s" % (RED, OFF), file=sys.stderr)
        return 1

    # 先跑正对照。判据本身坏了的话,后面所有「绿」都不作数 —— 与其给出
    # 一个不能信的绿,不如在这里就红。
    if self_test() != 0:
        return 1

    files, bad = 0, 0
    for r in roots:
      for dirpath, _dirnames, filenames in os.walk(r):
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

    # 判据名由 CHECKS 自己列出,不写死 —— 加了第三条判据而这句还停在两条,
    # 那就是一句过期的断言,比不说更糟。
    print("%s✓%s HTML 结构完好（%d 个页面：%s）"
          % (GRN, OFF, files, " · ".join(name for name, _ in CHECKS)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
