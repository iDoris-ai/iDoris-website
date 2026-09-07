#!/usr/bin/env bash
# 变异测试:逐条破坏安全属性,测试**必须**变红。
#
# 这个模块的两条最不能形同虚设:「超时不自动放行」和「白名单默认为空」。
# 它们保护的是客户的真实订单与口碑 —— 一条错误的自动回复对本地小生意的伤害,
# 远大于省下的那点人工。
set -uo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
RED=$'\033[31m'; GRN=$'\033[32m'; OFF=$'\033[0m'

cp approval.py .approval.bak
cp egress_guard.py .egress_guard.bak
cp ../demo_meeting_to_tasks.py .demo.bak
restore() {
  mv -f .approval.bak approval.py
  mv -f .egress_guard.bak egress_guard.py
  mv -f .demo.bak ../demo_meeting_to_tasks.py
}
trap restore EXIT

fail=0
n_mut=0        # 自动计数 —— 写死数字会随着加变异而过期,
               # 而一句过期的「各条属性都被兜住」比不说更糟。
mutate() {   # $1=描述 $2=sed [$3=目标文件] [$4=测试文件] [$5=备份文件]
  local f="${3:-approval.py}" t="${4:-test_approval.py}" b="${5:-}"
  [ -n "$b" ] || b=".$(basename "${f%.py}").bak"
  n_mut=$((n_mut + 1))
  sed -i.tmp "$2" "$f" && rm -f "$f.tmp"
  # 变异必须真的改到文件。sed 匹配不上时会**静默无操作**,测试照常通过,
  # 于是一条过期变异会伪装成「属性没被兜住」,把人引去改根本没问题的测试。
  if cmp -s "$f" "$b"; then
    echo "  ${RED}✗${OFF} $1 —— 变异未生效(sed 没匹配上,多半是代码重构了),请更新这条变异"
    fail=1; return
  fi
  if $PY "$t" >/dev/null 2>&1; then
    echo "  ${RED}✗${OFF} $1 —— 破坏后测试仍然通过,这条属性没有被兜住"
    fail=1
  else
    echo "  ${GRN}✓${OFF} $1 —— 测试正确报警"
  fi
  cp "$b" "$f"
}

echo "== 变异测试:破坏安全属性,测试必须变红 =="

mutate "破坏出处强制(允许无 sources 的草稿)" \
  's/if not self.sources:/if False:/'

mutate "破坏编辑放行(总是用原始草稿,忽略人的修改)" \
  's/final = row\["body"\] if edited_body is None else edited_body/final = row["body"]/'

mutate "破坏白名单默认为空(空白名单变成全放行)" \
  's/return False, "白名单为空（默认）→ 全部人工审批"/return True, "空白名单被当成全放行"/'

mutate "破坏白名单开关(关掉也照样放行)" \
  's/if not self.enabled:/if False:/'

mutate "破坏置信度门槛(低置信度也放行)" \
  's/if d.confidence < self.min_confidence:/if False:/'

mutate "破坏 PII 拦截(含个人信息也自动放行)" \
  's/if self.require_no_pii and d.contains_pii:/if False:/'

# 超时语义:让 escalations 在返回前把 pending 项标成已放行。
# 无条件生效 —— 早先写过一版用 `or` 拼接的,列表非空时短路,等于没破坏,
# 而变异测试正确地报告了「这条属性没有被兜住」。变异本身也要能变红。
mutate "破坏超时语义(escalations 顺手把超时项放行)" \
  's/cutoff = now - self.escalate_after_s/cutoff = now - self.escalate_after_s; self._conn.execute("UPDATE approvals SET status=\x27approved\x27, final_body=body WHERE status=\x27pending\x27"); self._conn.commit()/'

mutate "破坏重复决策拦截(已决策的项能再决策一次)" \
  's/if row\["status"\] != PENDING:/if False:/'

mutate "破坏租户隔离(pending 不按 tenant 过滤)" \
  's/sql = ("SELECT \* FROM approvals WHERE tenant=? AND status=?")/sql = ("SELECT * FROM approvals WHERE ?=? OR status=?")/'

mutate "破坏驳回理由强制(空理由也能驳回)" \
  's/if not reason.strip():/if False:/'

# ── 出网闸门 ───────────────────────────────────────────────────────
# 这几条守的是「客户的会议转写稿不会被发到 api.smith.langchain.com」。
# 坏掉的方向不对称:永远拒绝会被运维立刻发现,**永远放行不会有任何人发现**。

mutate "破坏出网闸门(环境脏也放行)" \
  's/^    if hits:/    if False:/' egress_guard.py test_egress_guard.py

mutate "破坏失败关闭(认不出来的带前缀变量放过)" \
  's|^        hits.append((name, "带追踪前缀且非空（值长度 %d）" % len(value)))|        pass|' \
  egress_guard.py test_egress_guard.py

mutate "破坏前缀扫描(只认写死的那几个开关)" \
  's/^        if not name.startswith(WATCHED_PREFIXES):/        if name not in _TOGGLES:/' \
  egress_guard.py test_egress_guard.py

mutate "破坏真值判定(false 也当成开着 —— 会被运维整条注释掉)" \
  's/^    return value.strip().lower() in _TRUTHY/    return True/' \
  egress_guard.py test_egress_guard.py

mutate "报错信息里打印变量值(可能是 API key)" \
  's|^        hits.append((name, "带追踪前缀且非空（值长度 %d）" % len(value)))|        hits.append((name, "值 %s" % value))|' \
  egress_guard.py test_egress_guard.py

mutate "闸门从入口摘掉(模块还在,只是没人调用)" \
  's/^assert_no_tracing_env()/pass  # /' \
  ../demo_meeting_to_tasks.py test_egress_guard.py .demo.bak

# 反向对照:无害改动,测试应仍通过
sed -i.tmp 's/# 状态机。刻意不做/# 注释改动。刻意不做/' approval.py 2>/dev/null; rm -f approval.py.tmp
if $PY test_approval.py >/dev/null 2>&1; then
  echo "  ${GRN}✓${OFF} 反向对照:无害改动后测试仍通过(无假阳性)"
else
  echo "  ${RED}✗${OFF} 反向对照:无害改动竟然让测试变红 —— 测试太脆"
  fail=1
fi
cp .approval.bak approval.py

echo
if [ "$fail" -eq 0 ]; then
  echo "${GRN}✓ 变异测试通过:${n_mut} 条安全属性都被测试真正兜住,且无假阳性${OFF}"
else
  echo "${RED}✗ 变异测试失败:上面标 ✗ 的属性形同虚设${OFF}"
fi
exit $fail
