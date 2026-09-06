#!/usr/bin/env bash
# 变异测试:逐条破坏「不可破规则」,测试套件**必须**变红。
#
# 为什么需要这个:一个永远绿的测试套件,看起来和真测试一模一样。
# 2026-09-05 我们在 /pricing 上栽过 —— 所有检查全绿,但结论集体错了。
# 这个脚本回答的是「如果规则真被破坏了,测试会不会喊」。
set -uo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
RED=$'\033[31m'; GRN=$'\033[32m'; OFF=$'\033[0m'

cp routing.py .routing.bak
cp audit.py   .audit.bak
restore() { mv -f .routing.bak routing.py; mv -f .audit.bak audit.py; }
trap restore EXIT

fail=0
n_mut=0        # 变异条数自动计数 —— 写死数字会随着加变异而过期,
               # 而一句过期的「九条规则都被兜住」比不说更糟。
mutate() {   # $1=描述  $2=sed 表达式  [$3=目标文件,默认 routing.py] [$4=测试,默认 test_routing.py]
  local f="${3:-routing.py}" t="${4:-test_routing.py}" b
  b=".${f%.py}.bak"
  n_mut=$((n_mut + 1))
  sed -i.tmp "$2" "$f" && rm -f "$f.tmp"
  # 变异必须真的改到文件。sed 匹配不上时会**静默无操作**,测试照常通过,
  # 于是一条过期变异会伪装成「规则没被兜住」,把人引去改根本没问题的测试。
  # 重构挪走了被匹配的代码就会这样 —— 必须和真漏洞区分开。
  if cmp -s "$f" "$b"; then
    echo "  ${RED}✗${OFF} $1 —— 变异未生效(sed 没匹配上,多半是代码重构了),请更新这条变异"
    fail=1; return
  fi
  if $PY "$t" >/dev/null 2>&1; then
    echo "  ${RED}✗${OFF} $1 —— 破坏后测试仍然通过,这条规则没有被测试兜住"
    fail=1
  else
    echo "  ${GRN}✓${OFF} $1 —— 测试正确报警"
  fi
  cp ".${f%.py}.bak" "$f"
}

echo "== 变异测试:破坏规则,测试必须变红 =="

# 规则 1:去掉 sensitivity=high 的强制 local
mutate "破坏隐私 override(high 不再强制 local)" \
  's/if sensitivity == "high":/if False:/'

# 规则 2:把硬停改成不拦
mutate "破坏预算硬停(超预算不再拒绝)" \
  's/if self.budget is not None and self.budget.state() == "blocked":/if False:/'

# 规则 2b:降级门槛改成对所有档生效
mutate "破坏降级范围(把 mid 也降级)" \
  's/if tier == "premium":/if tier in ("premium", "mid"):/'

# 配置校验:去掉 local 档必需
mutate "破坏配置校验(不再要求 local 档)" \
  's/if "local" not in self.tiers:/if False:/'

# 规则 3:清空 reason
mutate "破坏可解释性(reason 置空)" \
  's/reason = "task %r 命中规则 #%d" % (task, idx)/reason = ""/'

# ── audit.py:那条不可破的边界 ──────────────────────────────
# 「Gateway 只存元数据」如果没有被测试兜住,它就只是一句愿望。

mutate "破坏内容边界(字段名不再比对禁用清单)" \
  's/if k.lower() in _FORBIDDEN_FIELDS/if False/' \
  audit.py test_audit.py

mutate "破坏长文本拦截(取消 500 字符上限)" \
  's/if isinstance(v, str) and len(v) > 500:/if False:/' \
  audit.py test_audit.py

mutate "破坏租户隔离(月度统计不按 tenant 过滤)" \
  's/WHERE tenant=? AND ts>=? AND ts<?"/WHERE ts>=? AND ts<? AND ?=?"/' \
  audit.py test_audit.py

mutate "破坏隐私事后核查(不再筛 tier!=local)" \
  "s/AND sensitivity='high' AND tier!='local'/AND sensitivity='high' AND 1=0/" \
  audit.py test_audit.py

mutate "破坏账单时区(月份边界改回服务器本地时区)" \
  's|        start = datetime(y, m, 1, tzinfo=tz).timestamp()|        start = time.mktime((y, m, 1, 0, 0, 0, 0, 0, -1))|' \
  audit.py test_audit.py

# 反向对照:改一处**不影响规则**的东西,测试应当仍然通过
sed -i.tmp 's/# 按名字取/# 注释改动/' routing.py 2>/dev/null; rm -f routing.py.tmp
if $PY test_routing.py >/dev/null 2>&1; then
  echo "  ${GRN}✓${OFF} 反向对照:无害改动后测试仍通过(无假阳性)"
else
  echo "  ${RED}✗${OFF} 反向对照:无害改动竟然让测试变红 —— 测试太脆"
  fail=1
fi
cp .routing.bak routing.py

echo
if [ "$fail" -eq 0 ]; then
  echo "${GRN}✓ 变异测试通过:${n_mut} 条规则各自都被测试真正兜住,且无假阳性${OFF}"
else
  echo "${RED}✗ 变异测试失败:上面标 ✗ 的规则形同虚设${OFF}"
fi
exit $fail
