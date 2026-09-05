#!/usr/bin/env bash
# 变异测试:破坏三条硬要求,测试必须变红。
set -uo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
RED=$'\033[31m'; GRN=$'\033[32m'; OFF=$'\033[0m'
cp copywriting.py .copywriting.bak
trap 'mv -f .copywriting.bak copywriting.py' EXIT
fail=0
n_mut=0        # 自动计数 —— 写死数字会随着加变异而过期,
               # 而一句过期的「三条硬要求都被兜住」比不说更糟。
mutate() {
  n_mut=$((n_mut + 1))
  sed -i.tmp "$2" copywriting.py && rm -f copywriting.py.tmp
  # 变异必须真的改到文件。sed 匹配不上时会**静默无操作**,测试照常通过,
  # 于是一条过期变异会伪装成「硬要求没被兜住」,把人引去改根本没问题的测试。
  if cmp -s copywriting.py .copywriting.bak; then
    echo "  ${RED}✗${OFF} $1 —— 变异未生效(sed 没匹配上,多半是代码重构了),请更新这条变异"
    fail=1; return
  fi
  if $PY test_copywriting.py >/dev/null 2>&1; then
    echo "  ${RED}✗${OFF} $1 —— 破坏后测试仍然通过,这条属性没有被兜住"; fail=1
  else
    echo "  ${GRN}✓${OFF} $1 —— 测试正确报警"
  fi
  cp .copywriting.bak copywriting.py
}

echo "== 变异测试:破坏硬要求,测试必须变红 =="

mutate "破坏字数硬闸(超限也放行)" \
  's/                    if n > limit:/                    if False:/'

mutate "破坏短信段数闸(多段短信也放行,话费翻倍无人知)" \
  's/                    if segments > MAX_SMS_SEGMENTS:/                    if False:/'

mutate "破坏短信编码判定(泰文当成 GSM-7,单段按 160 算)" \
  's/^            return None/            continue/'

mutate "破坏 UTF-16 计数(改回 len,emoji 少算一半)" \
  's|^    return len(text.encode("utf-16-le")) // 2|    return len(text)|'

mutate "破坏字数上限的渠道区分(全用最大值)" \
  's/        limit = CHANNEL_LIMITS\[ch\]/        limit = max(CHANNEL_LIMITS.values())/'

mutate "破坏未知渠道拒绝(猜一个上限)" \
  's/        if unknown:/        if False:/'

mutate "破坏禁止项校验" \
  's/                if hits:/                if False:/'

mutate "破坏禁止项的大小写不敏感" \
  's/    low = text.lower()\n//; s/    return \[f for f in forbidden if f.lower() in low\]/    return [f for f in forbidden if f in text]/'

mutate "破坏敬语一致检查" \
  's/    if _PARTICLE_MALE.search(joined) and _PARTICLE_FEMALE.search(joined):/    if False:/'

mutate "破坏组合完整性(缺渠道也交付)" \
  's/            if key not in model_output:/            if False:/'

mutate "破坏变体数校验" \
  's/            if len(texts) != req.variants:/            if False:/'

mutate "破坏空变体拒绝" \
  's/                if not t.strip():/                if False:/'

mutate "破坏多余组合拒绝" \
  's/^    if extra:/    if False:/'

mutate "破坏指示生成(不再写字数上限)" \
  's|^            "Hard limit: %d UTF-16 code units per variant (an emoji counts as 2). "|            "Write something nice. "|'

mutate "破坏短信指示的语言区分(对泰文也说 160)" \
  's/        sms_limit = 70 if lang == "th" else 160/        sms_limit = 160/'

# 反向对照
sed -i.tmp 's/# 渠道字数上限/# 注释改动/' copywriting.py 2>/dev/null; rm -f copywriting.py.tmp
if $PY test_copywriting.py >/dev/null 2>&1; then
  echo "  ${GRN}✓${OFF} 反向对照:无害改动后测试仍通过(无假阳性)"
else
  echo "  ${RED}✗${OFF} 反向对照:无害改动竟然让测试变红 —— 测试太脆"; fail=1
fi
cp .copywriting.bak copywriting.py

echo
[ "$fail" -eq 0 ] && echo "${GRN}✓ 变异测试通过:${n_mut} 条属性都被测试真正兜住,且无假阳性${OFF}" \
                  || echo "${RED}✗ 变异测试失败${OFF}"
exit $fail
