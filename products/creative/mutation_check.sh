#!/usr/bin/env bash
# 变异测试:破坏三条硬要求,测试必须变红。
set -uo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
RED=$'\033[31m'; GRN=$'\033[32m'; OFF=$'\033[0m'
cp copywriting.py .copywriting.bak
trap 'mv -f .copywriting.bak copywriting.py' EXIT
fail=0
mutate() {
  sed -i.tmp "$2" copywriting.py && rm -f copywriting.py.tmp
  if $PY test_copywriting.py >/dev/null 2>&1; then
    echo "  ${RED}✗${OFF} $1 —— 破坏后测试仍然通过,这条属性没有被兜住"; fail=1
  else
    echo "  ${GRN}✓${OFF} $1 —— 测试正确报警"
  fi
  cp .copywriting.bak copywriting.py
}

echo "== 变异测试:破坏硬要求,测试必须变红 =="

mutate "破坏字数硬闸(超限也放行)" \
  's/                if len(t) > limit:/                if False:/'

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
  's/        "Hard limit: %d characters per variant. Going over is a rejection, not a warning."/        "Write something nice."  # /'

# 反向对照
sed -i.tmp 's/# 渠道字数上限/# 注释改动/' copywriting.py 2>/dev/null; rm -f copywriting.py.tmp
if $PY test_copywriting.py >/dev/null 2>&1; then
  echo "  ${GRN}✓${OFF} 反向对照:无害改动后测试仍通过(无假阳性)"
else
  echo "  ${RED}✗${OFF} 反向对照:无害改动竟然让测试变红 —— 测试太脆"; fail=1
fi
cp .copywriting.bak copywriting.py

echo
[ "$fail" -eq 0 ] && echo "${GRN}✓ 变异测试通过:三条硬要求都被测试真正兜住,且无假阳性${OFF}" \
                  || echo "${RED}✗ 变异测试失败${OFF}"
exit $fail
