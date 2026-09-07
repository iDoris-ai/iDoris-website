#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iDoris Creative — copy 动作：泰英双语营销文案。

设计见 docs/business/starter-kit/creative.md。

## 为什么先做这一个

Creative 的其余三个动作都要经 ComfyUI，而 **[待核] 图像模型权重的商用许可
还没核清**（见 oss-due-diligence.md §3）。`copy` **不碰 ComfyUI**，
只走 Gateway 的文本模型：

  **零 GPL 风险 · 零权重许可风险 · 可以先交付**

而且泰英双语营销文案本身就是能卖的东西 —— 不是「等图像做好了才有价值」的半成品。

## 三条硬要求

1. **渠道字数上限是硬闸，不是建议。**
   LINE OA 的推送被截断、Instagram 的说明被折叠，客户看到的是残缺的文案。
   超限直接拒绝，让人改，而不是发出去再说。

2. **BrandKit 的 `forbidden` 是禁止项，逐条校验。**
   「不得出现竞品名」「不得承诺具体折扣」这类约束，客户提出来就是因为踩过坑。
   模型不会记得，我们必须查。

3. **泰文敬语与 Documents 同一套处理。**
   同一家客户的翻译和文案如果一个用 ครับ 一个用 ค่ะ，比两个都用错更糟 ——
   那看起来像两个人在冒充同一个品牌。

## 模型做什么、不做什么

**做**：写文案。
**不做**：判断有没有超字数、有没有踩禁止项、敬语一致不一致。

    python3 copywriting.py --self-test
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any

# ── 计数单位 ──────────────────────────────────────────────────────────
#
# **不能一律用 len()。** 各平台数的东西不一样，用错单位的闸门会两头出错：
#
#   1. LINE / Facebook / Instagram / 邮件客户端都是 JS 栈，数的是
#      **UTF-16 code unit**（JS 的 String.length）。一个 emoji 在 Python
#      len() 里是 1，在平台那里是 2。用 len() 数会**偏松** —— 放过去的文案
#      到了平台被截断，正是这个闸门要防的事。
#   2. 短信的 160 是 **GSM-7 septet** 上限，不是「字符」。泰文没有一个字
#      在 GSM-7 表里，整条强制转 UCS-2，单条上限掉到 **70**。一条 152 字的
#      泰文短信用 len() 数「没超 160」，实际要发 3 段、**三倍话费**，
#      而且没有任何东西报错。
#
# 所以每个渠道显式声明单位。宁可多写一行，不要让闸门看起来在把关、实际没有。

UNIT_UTF16 = "utf16"      # JS 平台的 String.length
UNIT_SMS = "sms"          # GSM-7 septet / UCS-2，见 sms_cost()

# GSM-7 基本表。不在表里的字符会让整条短信转 UCS-2。
_GSM7_BASIC = set(
    "@\u00a3$\u00a5\u00e8\u00e9\u00f9\u00ec\u00f2\u00c7\n\u00d8\u00f8\r"
    "\u00c5\u00e5\u0394_\u03a6\u0393\u039b\u03a9\u03a0\u03a8\u03a3\u0398\u039e"
    "\u00c6\u00e6\u00df\u00c9"
    " !\"#\u00a4%&'()*+,-./0123456789:;<=>?"
    "\u00a1ABCDEFGHIJKLMNOPQRSTUVWXYZ\u00c4\u00d6\u00d1\u00dc\u00a7"
    "\u00bfabcdefghijklmnopqrstuvwxyz\u00e4\u00f6\u00f1\u00fc\u00e0")
# 扩展表：每个占 2 个 septet。
_GSM7_EXT = set("^{}\\[~]|\u20ac")


def utf16_units(text: str) -> int:
    """平台（JS）看到的长度。emoji 等非 BMP 字符算 2。"""
    return len(text.encode("utf-16-le")) // 2


def gsm7_septets(text: str) -> int | None:
    """GSM-7 所需 septet 数；有任一字符不在表里则返回 None（=必须走 UCS-2）。"""
    n = 0
    for ch in text:
        if ch in _GSM7_BASIC:
            n += 1
        elif ch in _GSM7_EXT:
            n += 2
        else:
            return None
    return n


def sms_cost(text: str) -> tuple[str, int, int]:
    """返回 (编码, 计数值, 需要的短信段数)。

    单段上限：GSM-7 160 / UCS-2 70；拼接后每段留 6 字节 UDH，
    降到 153 / 67。泰文永远走 UCS-2。
    """
    sep = gsm7_septets(text)
    if sep is not None:
        enc, units, single, multi = "GSM-7", sep, 160, 153
    else:
        enc, units, single, multi = "UCS-2", utf16_units(text), 70, 67
    segments = 1 if units <= single else -(-units // multi)
    return enc, units, segments


# 渠道字数上限。**[待核] 各平台的实际限制会变，这里的值需定期核。**
# 核法：各平台官方开发者文档。谁核：Dev，季度复查。
# 取值刻意保守 —— 宁可让人删两个字，不要让客户看到被截断的文案。
# 第二个值是**计数单位**，见上面那段。
CHANNEL_LIMITS: dict[str, int] = {
    "line_oa": 500,          # [待核] LINE OA 推送
    "facebook_post": 2000,   # [待核]
    "instagram_post": 2200,  # [待核] 超过会被折叠
    "email_subject": 60,     # 通用经验值
    "sms": 160,              # GSM-7 septet；泰文走 UCS-2 时实际是 70，见 sms_cost()
}

CHANNEL_UNIT: dict[str, str] = {
    "line_oa": UNIT_UTF16,
    "facebook_post": UNIT_UTF16,
    "instagram_post": UNIT_UTF16,
    "email_subject": UNIT_UTF16,
    "sms": UNIT_SMS,
}

# 允许的最高短信段数。1 段 = 1 条的价钱；放宽到 2 就是话费翻倍，
# 那是客户该拍板的事，不是我们默认替他决定的。
MAX_SMS_SEGMENTS = 1


def count_for_channel(text: str, channel: str) -> int:
    """按渠道自己的单位数长度。"""
    if CHANNEL_UNIT[channel] == UNIT_SMS:
        return sms_cost(text)[1]
    return utf16_units(text)


def effective_limit(text: str, channel: str) -> int:
    """该渠道对**这段文本**的实际上限。

    短信是唯一会随内容变的：同一个渠道，英文 160、泰文 70。
    """
    if CHANNEL_UNIT[channel] != UNIT_SMS:
        return CHANNEL_LIMITS[channel]
    return 160 if gsm7_septets(text) is not None else 70

LANGS = ("th", "en", "zh")

# 与 Documents 的 translate 共用同一套敬语粒子判定 —— 同一家客户的
# 翻译和文案必须一致，否则看起来像两个人在冒充同一个品牌。
_PARTICLE_MALE = re.compile(r"ครับ|คับ")
_PARTICLE_FEMALE = re.compile(r"ค่ะ|คะ")


class CopyRejected(ValueError):
    """文案不合格。**拒绝，让人改，而不是发出去再说。**"""


@dataclass
class BrandKit:
    """品牌配置。**由客户确认，不由模型推断。**"""
    brand_id: str
    display_name: str
    tone_th: str = ""
    tone_en: str = ""
    forbidden: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.brand_id or not self.display_name:
            raise CopyRejected("BrandKit 缺 brand_id 或 display_name")
        for f in self.forbidden:
            if not f.strip():
                raise CopyRejected("forbidden 里有空条目")


@dataclass
class CopyRequest:
    brand: BrandKit
    subject: str                       # 要宣传什么
    channels: list[str]
    langs: list[str]
    variants: int = 3

    def validate(self) -> None:
        self.brand.validate()
        if not self.subject.strip():
            raise CopyRejected("subject 不能为空 —— 没有主题的文案是废话生成器")
        if not self.channels:
            raise CopyRejected("至少要指定一个渠道 —— 字数上限由渠道决定")
        unknown = [c for c in self.channels if c not in CHANNEL_LIMITS]
        if unknown:
            raise CopyRejected(
                "未知渠道：%s。**不猜字数上限** —— 猜错的后果是客户看到被截断的文案"
                % ", ".join(unknown))
        bad_langs = [l for l in self.langs if l not in LANGS]
        if bad_langs:
            raise CopyRejected("未支持的语言：%s" % ", ".join(bad_langs))
        if not 1 <= self.variants <= 5:
            raise CopyRejected("variants 应在 1..5，得到 %r" % self.variants)


@dataclass
class CopyVariant:
    channel: str
    lang: str
    text: str
    length: int = 0

    def __post_init__(self) -> None:
        # 按渠道自己的单位数 —— 交付物上写的字数得和平台数的一致,
        # 否则客户拿去核对会对不上。
        self.length = count_for_channel(self.text, self.channel)


@dataclass
class CopyResult:
    brand_id: str
    subject: str
    variants: list[CopyVariant] = field(default_factory=list)

    def for_channel(self, channel: str) -> list[CopyVariant]:
        return [v for v in self.variants if v.channel == channel]

    def as_dict(self) -> dict[str, Any]:
        return {"brand_id": self.brand_id, "subject": self.subject,
                "variants": [{"channel": v.channel, "lang": v.lang,
                              "text": v.text, "length": v.length}
                             for v in self.variants]}


def build_instruction(req: CopyRequest, channel: str, lang: str) -> str:
    """给模型的指示。**把字数、语气、禁止项写死。**"""
    limit = CHANNEL_LIMITS[channel]
    tone = req.brand.tone_th if lang == "th" else req.brand.tone_en
    lines = [
        "Write %d marketing copy variants in %s for: %s" % (req.variants, lang, req.subject),
        "Brand: %s" % req.brand.display_name,
    ]
    if CHANNEL_UNIT[channel] == UNIT_SMS:
        # 短信的上限随语言变。告诉模型 160 再让泰文文案被拒,是我们的错不是它的。
        sms_limit = 70 if lang == "th" else 160
        lines.append(
            "Hard limit: %d characters per variant (SMS in %s uses %s encoding). "
            "Going over is a rejection, not a warning."
            % (sms_limit, lang, "UCS-2" if lang == "th" else "GSM-7"))
    else:
        lines.append(
            "Hard limit: %d UTF-16 code units per variant (an emoji counts as 2). "
            "Going over is a rejection, not a warning." % limit)
    if tone:
        lines.append("Tone: %s" % tone)
    if req.brand.forbidden:
        lines.append("Never mention or imply any of the following:")
        lines.extend("  - %s" % f for f in req.brand.forbidden)
    if lang == "th":
        lines.append(
            "Use one politeness register consistently across all variants. "
            "Do not mix ครับ and ค่ะ.")
    return "\n".join(lines)


def check_forbidden(text: str, forbidden: list[str]) -> list[str]:
    """返回命中的禁止项。**大小写不敏感** —— 否则改个大小写就绕过去了。"""
    low = text.lower()
    return [f for f in forbidden if f.lower() in low]


def check_particles(texts: list[str]) -> str | None:
    """跨全部变体检查敬语一致 —— 单条看不出问题，一组放在一起才看得出。"""
    joined = "\n".join(texts)
    if _PARTICLE_MALE.search(joined) and _PARTICLE_FEMALE.search(joined):
        return ("同一组文案里同时出现 ครับ 与 ค่ะ —— "
                "对外看起来像两个人在冒充同一个品牌")
    return None


def assemble(req: CopyRequest,
             model_output: dict[tuple[str, str], list[str]]) -> CopyResult:
    """把模型的输出组装成结果，并逐条校验三条硬要求。

    `model_output`：{(channel, lang): [变体文案, ...]}
    """
    req.validate()
    result = CopyResult(req.brand.brand_id, req.subject)

    for ch in req.channels:
        limit = CHANNEL_LIMITS[ch]
        for lang in req.langs:
            key = (ch, lang)
            if key not in model_output:
                raise CopyRejected(
                    "缺 %s/%s 的文案 —— 拒绝整份。"
                    "少一个渠道而交付出去，客户会以为我们做了" % (ch, lang))
            texts = model_output[key]
            if len(texts) != req.variants:
                raise CopyRejected(
                    "%s/%s 要 %d 个变体，得到 %d 个"
                    % (ch, lang, req.variants, len(texts)))

            for i, t in enumerate(texts):
                if not t.strip():
                    raise CopyRejected("%s/%s 第 %d 个变体是空的" % (ch, lang, i + 1))
                # 硬要求 1：字数上限。**按渠道自己的单位数**，不是 len()。
                if CHANNEL_UNIT[ch] == UNIT_SMS:
                    enc, units, segments = sms_cost(t)
                    if segments > MAX_SMS_SEGMENTS:
                        raise CopyRejected(
                            "%s/%s 第 %d 个变体要发 %d 段短信（%s 编码，%d 单位，"
                            "单段上限 %d）—— 直接拒绝。多一段就是多一条的话费，"
                            "而且不会有任何东西提醒你。泰文没有一个字在 GSM-7 表里，"
                            "整条走 UCS-2，单段只有 70"
                            % (ch, lang, i + 1, segments, enc, units,
                               effective_limit(t, ch)))
                else:
                    n = count_for_channel(t, ch)
                    if n > limit:
                        raise CopyRejected(
                            "%s/%s 第 %d 个变体 %d 个 UTF-16 单位，超过 %s 的上限 %d —— "
                            "超限直接拒绝。发出去会被截断，客户看到的是残缺文案。"
                            "（平台按 JS 的 String.length 数，一个 emoji 算 2，"
                            "所以这个数可能比你肉眼数的多）"
                            % (ch, lang, i + 1, n, ch, limit))
                # 硬要求 2：禁止项
                hits = check_forbidden(t, req.brand.forbidden)
                if hits:
                    raise CopyRejected(
                        "%s/%s 第 %d 个变体踩了禁止项：%s —— "
                        "客户提出这些约束就是因为踩过坑"
                        % (ch, lang, i + 1, ", ".join(repr(h) for h in hits)))
                result.variants.append(CopyVariant(ch, lang, t))

    extra = set(model_output) - {(c, l) for c in req.channels for l in req.langs}
    if extra:
        raise CopyRejected("模型给了没要的组合：%s" % sorted(extra))

    # 硬要求 3：泰文敬语跨变体一致
    if "th" in req.langs:
        problem = check_particles([v.text for v in result.variants if v.lang == "th"])
        if problem:
            raise CopyRejected(problem)

    return result


# ---------------------------------------------------------------- 自检

_BK = BrandKit(brand_id="baan-rimping", display_name="Baan Rimping",
               tone_th="สุภาพ เป็นกันเอง", tone_en="warm, concise",
               forbidden=["最便宜", "保证", "competitor-hotel"])


def _req(**kw: Any) -> CopyRequest:
    base: dict[str, Any] = dict(brand=_BK, subject="เมนูอาหารเช้าใหม่",
                                channels=["line_oa"], langs=["th", "en"], variants=2)
    base.update(kw)
    return CopyRequest(**base)


_GOOD = {
    ("line_oa", "th"): ["เมนูเช้าใหม่มาแล้วครับ", "ลองเมนูใหม่ของเราครับ"],
    ("line_oa", "en"): ["Our new breakfast menu is here.", "Try our new breakfast."],
}


def self_test() -> int:
    fails: list[str] = []
    r = assemble(_req(), _GOOD)
    if len(r.variants) != 4:
        fails.append("变体数不对：%d" % len(r.variants))
    if len(r.for_channel("line_oa")) != 4:
        fails.append("按渠道取变体错")

    def _with(key, val):
        d = dict(_GOOD)      # 元组键不能走 dict(**{...})，那要求键是字符串
        d[key] = val
        return d

    over = _with(("line_oa", "en"), ["x" * 600, "ok"])
    try:
        assemble(_req(), over)
        fails.append("超字数没被拒")
    except CopyRejected:
        pass

    forb = _with(("line_oa", "en"), ["We are the 最便宜 hotel", "ok"])
    try:
        assemble(_req(), forb)
        fails.append("禁止项没被拒")
    except CopyRejected:
        pass

    mixed = _with(("line_oa", "th"), ["ยินดีครับ", "ขอบคุณค่ะ"])
    try:
        assemble(_req(), mixed)
        fails.append("敬语混用没被拒")
    except CopyRejected:
        pass

    try:
        assemble(_req(channels=["未知渠道"]), _GOOD)
        fails.append("未知渠道没被拒 —— 不该猜字数上限")
    except CopyRejected:
        pass

    instr = build_instruction(_req(), "line_oa", "th")
    if "500" not in instr or "最便宜" not in instr:
        fails.append("指示里没写清字数上限或禁止项")

    if fails:
        print("✗ copywriting 自检失败", file=sys.stderr)
        for f in fails:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ copywriting 自检通过（字数硬闸 · 禁止项 · 敬语一致 · 未知渠道不猜）")
    return 0


if __name__ == "__main__":
    sys.exit(self_test())
