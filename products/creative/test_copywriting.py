#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""copywriting.py 的测试。

三条硬要求各配负对照：**字数上限**、**禁止项**、**敬语一致**。

跑法：python3 test_copywriting.py
"""

import sys

from copywriting import (
    CHANNEL_LIMITS,
    MAX_SMS_SEGMENTS,
    gsm7_septets,
    sms_cost,
    utf16_units,
    BrandKit,
    CopyRejected,
    CopyRequest,
    assemble,
    build_instruction,
    check_forbidden,
    check_particles,
)

FAILS: list[str] = []

BK = BrandKit(brand_id="baan-rimping", display_name="Baan Rimping",
              tone_th="สุภาพ เป็นกันเอง", tone_en="warm, concise",
              forbidden=["最便宜", "保证", "Competitor-Hotel"])


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def expect_raises(exc, fn, msg: str) -> None:
    try:
        fn()
    except exc:
        return
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("%s（抛的是 %s: %s）" % (msg, type(e).__name__, e))
        return
    FAILS.append(msg)


def req(**kw):
    base = dict(brand=BK, subject="เมนูอาหารเช้าใหม่",
                channels=["line_oa"], langs=["th", "en"], variants=2)
    base.update(kw)
    return CopyRequest(**base)


GOOD = {
    ("line_oa", "th"): ["เมนูเช้าใหม่มาแล้วครับ", "ลองเมนูใหม่ของเราครับ"],
    ("line_oa", "en"): ["Our new breakfast menu is here.", "Try our new breakfast."],
}


def with_(key, val):
    d = dict(GOOD)
    d[key] = val
    return d


# ══════════════════════════════════════ 硬要求 1：字数上限

def test_length_limit_is_a_gate() -> None:
    """超限直接拒绝，让人改 —— 而不是发出去让客户看到被截断的文案。"""
    over = with_(("line_oa", "en"), ["x" * (CHANNEL_LIMITS["line_oa"] + 1), "ok"])
    expect_raises(CopyRejected, lambda: assemble(req(), over), "超字数没被拒")

    # 边界:恰好等于上限必须放行 —— 否则「宁可全拒」也能让上面绿
    exact = with_(("line_oa", "en"), ["x" * CHANNEL_LIMITS["line_oa"], "ok"])
    try:
        assemble(req(), exact)
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("边界错：恰好等于上限被拒（%s）" % e)

    # 负对照:不同渠道用各自的上限，不是一刀切
    short = req(channels=["email_subject"])
    long_for_email = {("email_subject", "th"): ["ก" * 61, "ok"],
                      ("email_subject", "en"): ["a", "b"]}
    expect_raises(CopyRejected, lambda: assemble(short, long_for_email),
                  "email_subject 用了别的渠道的上限 —— 61 字应超过 60")


def test_sms_thai_counts_as_ucs2_not_characters() -> None:
    """短信的 160 是 GSM-7 septet，不是「字符」。泰文强制 UCS-2，单段只有 70。

    这是真实 bug 的回归测试：闸门原先用 len(t) > 160 判断，于是一条
    152 字的泰文短信「没超 160」直接放行，实际发出去是 3 段、三倍话费，
    而且没有任何东西报错。钱的事，不能靠人眼看。
    """
    thai = "สวัสดีค่ะ ยินดีต้อนรับสู่โรงแรมของเรา " * 4
    thai = thai[:152]
    enc, units, segs = sms_cost(thai)
    check(enc == "UCS-2", "泰文短信编码判错：%s（泰文没有一个字在 GSM-7 表里）" % enc)
    check(segs == 3, "泰文 152 字应是 3 段，得到 %d" % segs)
    check(units <= CHANNEL_LIMITS["sms"],
          "前提失效：这个样例得是「len() 看着没超 160」才有意义（units=%d）" % units)

    r = req(channels=["sms"], langs=["th"], variants=1)
    expect_raises(CopyRejected, lambda: assemble(r, {("sms", "th"): [thai]}),
                  "超段泰文短信没被拒 —— len() 数出来「没超 160」正是 bug 本身")

    # 正对照：70 以内的泰文必须放行，否则「一律拒绝」也能让上面绿
    ok_thai = "สวัสดีค่ะ ยินดีต้อนรับ"
    check(sms_cost(ok_thai)[2] == 1, "前提失效：短泰文应当只要 1 段")
    try:
        assemble(r, {("sms", "th"): [ok_thai]})
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("正对照失败：70 以内的泰文短信被拒了（%s）" % e)

    # 正对照：英文 160 走 GSM-7，仍应放行 —— 不能因为修泰文而误伤英文
    en = "Welcome to our hotel! " * 7
    en = en[:160]
    check(gsm7_septets(en) is not None, "前提失效：这段英文应当全在 GSM-7 表里")
    check(sms_cost(en)[2] == MAX_SMS_SEGMENTS, "英文 160 应当只要 1 段")
    try:
        assemble(req(channels=["sms"], langs=["en"], variants=1),
                 {("sms", "en"): [en]})
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("正对照失败：英文 160 字短信被拒了（%s）" % e)


def test_emoji_counted_as_platform_counts_them() -> None:
    """LINE/FB/IG 是 JS 栈，数的是 UTF-16 code unit —— 一个 emoji 算 2。

    用 len() 数会**偏松**：我们放行的文案到了平台被截断，
    而这个闸门存在的全部意义就是防这件事。
    """
    limit = CHANNEL_LIMITS["line_oa"]
    # 造一段 python len() 不超限、但 UTF-16 超限的文案
    n_emoji = 60
    text = "🎉" * n_emoji + "x" * (limit - n_emoji - 1)
    check(len(text) <= limit,
          "前提失效：这个样例得是「len() 看着没超」才有意义（len=%d）" % len(text))
    check(utf16_units(text) > limit,
          "前提失效：UTF-16 单位数应当超限（得到 %d）" % utf16_units(text))

    expect_raises(CopyRejected,
                  lambda: assemble(req(langs=["en"], variants=1),
                                   {("line_oa", "en"): [text]}),
                  "emoji 文案按 len() 数放行了 —— 平台按 UTF-16 数会截断")

    # 正对照：纯 BMP 文本恰好等于上限仍放行，UTF-16 计数没把普通文案误伤
    plain = "x" * limit
    check(utf16_units(plain) == limit, "纯 ASCII 的 UTF-16 单位数应当等于字符数")
    try:
        assemble(req(langs=["en"], variants=1), {("line_oa", "en"): [plain]})
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("正对照失败：恰好等于上限的普通文案被拒（%s）" % e)


def test_unknown_channel_not_guessed() -> None:
    """不猜字数上限 —— 猜错的后果是客户看到被截断的文案。"""
    expect_raises(CopyRejected, lambda: assemble(req(channels=["tiktok"]), GOOD),
                  "未知渠道没被拒")
    # 负对照:已知渠道必须放行
    for ch in CHANNEL_LIMITS:
        try:
            req(channels=[ch]).validate()
        except Exception as e:                               # noqa: BLE001
            FAILS.append("负对照失败：已知渠道 %r 被拒（%s）" % (ch, e))


# ══════════════════════════════════════ 硬要求 2：禁止项

def test_forbidden_terms_blocked() -> None:
    """客户提出这些约束就是因为踩过坑。模型不会记得，我们必须查。"""
    for bad in ("最便宜", "保证退款", "Competitor-Hotel"):
        expect_raises(CopyRejected,
                      lambda b=bad: assemble(req(), with_(("line_oa", "en"), [b, "ok"])),
                      "禁止项 %r 没被拦" % bad)

    # 大小写不敏感 —— 否则改个大小写就绕过去了
    expect_raises(CopyRejected,
                  lambda: assemble(req(), with_(("line_oa", "en"), ["competitor-hotel", "ok"])),
                  "小写形式的禁止项绕过了检查")

    # 负对照:不含禁止项的必须通过
    try:
        assemble(req(), GOOD)
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：干净文案被拒（%s）" % e)

    # 负对照:空禁止项列表时不该因此拒绝
    clean = BrandKit(brand_id="b", display_name="B")
    try:
        assemble(req(brand=clean), with_(("line_oa", "en"), ["最便宜 anything", "ok"]))
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：没有禁止项时仍被拒（%s）" % e)


def test_check_forbidden_unit() -> None:
    check(check_forbidden("we are 最便宜", ["最便宜"]) == ["最便宜"], "没命中")
    check(check_forbidden("ALL GOOD", ["最便宜"]) == [], "负对照失败：误报")
    check(check_forbidden("Competitor-HOTEL here", ["competitor-hotel"]) ==
          ["competitor-hotel"], "大小写不敏感失效")


# ══════════════════════════════════════ 硬要求 3：敬语一致

def test_particles_consistent_across_variants() -> None:
    """单条看不出问题，一组放在一起才看得出。"""
    expect_raises(CopyRejected,
                  lambda: assemble(req(), with_(("line_oa", "th"), ["ยินดีครับ", "ขอบคุณค่ะ"])),
                  "跨变体的敬语混用没被拒")

    # 负对照:统一用一种必须通过
    try:
        assemble(req(), with_(("line_oa", "th"), ["ยินดีครับ", "ขอบคุณครับ"]))
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：统一用 ครับ 被拒（%s）" % e)

    # 负对照:不要泰文时不该跑这条检查
    try:
        assemble(req(langs=["en"]),
                 {("line_oa", "en"): ["Yes ครับ", "Thanks ค่ะ"]})
    except Exception as e:                                   # noqa: BLE001
        FAILS.append("负对照失败：只要英文时也套用了泰文敬语检查（%s）" % e)


def test_check_particles_unit() -> None:
    check(check_particles(["ครับ", "ค่ะ"]) is not None, "混用没被检出")
    check(check_particles(["ครับ", "ครับ"]) is None, "负对照失败：统一用被误报")
    check(check_particles(["Hello", "World"]) is None, "负对照失败：无泰文被误报")


# ══════════════════════════════════════ 完整性

def test_missing_combination_rejected() -> None:
    """少一个渠道而交付出去，客户会以为我们做了。"""
    partial = {("line_oa", "th"): GOOD[("line_oa", "th")]}
    expect_raises(CopyRejected, lambda: assemble(req(), partial),
                  "缺一个语言组合没被拒")
    expect_raises(CopyRejected,
                  lambda: assemble(req(), with_(("facebook_post", "en"), ["x", "y"])),
                  "多出没要的组合没被拒")
    expect_raises(CopyRejected,
                  lambda: assemble(req(), with_(("line_oa", "en"), ["only-one"])),
                  "变体数不足没被拒")
    expect_raises(CopyRejected,
                  lambda: assemble(req(), with_(("line_oa", "en"), ["  ", "ok"])),
                  "空变体没被拒")


def test_request_validation() -> None:
    expect_raises(CopyRejected, lambda: req(subject="  ").validate(),
                  "空 subject 没被拒 —— 那是废话生成器")
    expect_raises(CopyRejected, lambda: req(channels=[]).validate(), "空渠道没被拒")
    expect_raises(CopyRejected, lambda: req(langs=["fr"]).validate(), "未支持语言没被拒")
    expect_raises(CopyRejected, lambda: req(variants=0).validate(), "variants=0 没被拒")
    expect_raises(CopyRejected, lambda: req(variants=9).validate(), "variants 过多没被拒")
    expect_raises(CopyRejected,
                  lambda: req(brand=BrandKit("", "x")).validate(), "空 brand_id 没被拒")
    expect_raises(CopyRejected,
                  lambda: req(brand=BrandKit("b", "B", forbidden=["  "])).validate(),
                  "空禁止项没被拒")


def test_instruction_states_the_hard_limits() -> None:
    instr = build_instruction(req(), "line_oa", "th")
    check(str(CHANNEL_LIMITS["line_oa"]) in instr, "指示里没写字数上限")
    check("最便宜" in instr, "指示里没列出禁止项")
    check("ครับ" in instr, "译成泰文时的指示没提敬语一致")

    en = build_instruction(req(), "line_oa", "en")
    check("ครับ" not in en, "负对照失败：英文指示里混进了泰文敬语规则")
    check("warm, concise" in en, "英文指示里没用英文 tone")


def test_sms_instruction_states_the_language_specific_limit() -> None:
    """给泰文短信的指示必须写 70，不是 160。

    短信上限随语言变（泰文走 UCS-2）。告诉模型 160、再用 70 拒它，
    是我们的错不是模型的 —— 白跑一轮，而且失败原因看起来毫无道理。
    """
    th = build_instruction(req(channels=["sms"]), "sms", "th")
    check("70" in th, "泰文短信的指示没写 70：%r" % th)
    check("160" not in th, "泰文短信的指示里出现了 160 —— 模型会照 160 写，然后被我们拒")
    check("UCS-2" in th, "泰文短信的指示没说明编码")

    en = build_instruction(req(channels=["sms"]), "sms", "en")
    check("160" in en, "英文短信的指示没写 160：%r" % en)
    check("70" not in en, "负对照失败：英文短信被按泰文的 70 限制了")


def test_result_shape() -> None:
    r = assemble(req(), GOOD)
    check(len(r.variants) == 4, "变体总数错：%d" % len(r.variants))
    check(len(r.for_channel("line_oa")) == 4, "按渠道取变体错")
    check(all(v.length == len(v.text) for v in r.variants), "length 字段没算对")
    d = r.as_dict()
    check(d["brand_id"] == "baan-rimping" and len(d["variants"]) == 4,
          "as_dict 结构错")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    for t in TESTS:
        t()
    if FAILS:
        print("✗ %d 个测试断言失败" % len(FAILS), file=sys.stderr)
        for f in FAILS:
            print("    %s" % f, file=sys.stderr)
        return 1
    print("✓ copywriting 测试全部通过（%d 个测试函数，含三条硬要求的负对照）"
          % len(TESTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
