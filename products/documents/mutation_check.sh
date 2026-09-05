#!/usr/bin/env bash
# 变异测试:破坏 DocIR 的关键属性,测试必须变红。
# 最要紧的两条:出处能回溯、泰文按字符切(不按空格)。
set -uo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
RED=$'\033[31m'; GRN=$'\033[32m'; OFF=$'\033[0m'
cp docir.py .docir.bak
trap 'mv -f .docir.bak docir.py' EXIT
fail=0
mutate() {
  sed -i.tmp "$2" docir.py && rm -f docir.py.tmp
  # 变异必须真的改到文件。sed 匹配不上时会**静默无操作**,测试照常通过,
  # 于是一条过期变异会伪装成「测试漏洞」,把人引去改根本没问题的测试。
  # 重构挪走了被匹配的代码就会这样 —— 必须和真漏洞区分开。
  if cmp -s docir.py .docir.bak; then
    echo "  ${RED}✗${OFF} $1 —— 变异未生效(sed 没匹配上,多半是代码重构了),请更新这条变异"
    fail=1; return
  fi
  if $PY test_docir.py >/dev/null 2>&1; then
    echo "  ${RED}✗${OFF} $1 —— 破坏后测试仍然通过,这条属性没有被兜住"; fail=1
  else
    echo "  ${GRN}✓${OFF} $1 —— 测试正确报警"
  fi
  cp .docir.bak docir.py
}

echo "== 变异测试:破坏关键属性,测试必须变红 =="

mutate "破坏泰文分块(改回按空格切)" \
  's|_SENT_END = re.compile(r"(?<=\[。．.!?！？;；\\n\])\|(?<=ๆ )")|_SENT_END = re.compile(r" ")|'

mutate "破坏长句硬切(超长句直接整块返回)" \
  's|^            out.extend(_hard_split(s, max_chars, overlap))|            out.append(s)|'

mutate "破坏超长块兜底(拼接后不再硬切)" \
  's/            if len(cur) > max_chars:/            if False:/'

# 刻意**不**对末尾那条不变式断言做变异。
#
# 它是**防御性兜底**:主修复(拼接后立刻硬切)正确时,它永远不触发。
# 所以删掉它不改变任何可观测行为 —— 正确行为的测试**不可能**抓到它,
# 这正是「防御性」的定义。
#
# 试过一次,变异测试如实报告「没有被兜住」。那不是测试的漏洞,
# 是那条变异本身不恰当。记在这里,免得下一个人再加一遍。

mutate "破坏出处回溯(分块不带 locators)" \
  's/"locators": \[b.locator()\],/"locators": [],/'

mutate "破坏出处回溯(分块不带 block_ids)" \
  's/"block_ids": \[b.id\],/"block_ids": [],/'

mutate "破坏 NFC 归一化(入口不再归一化)" \
  's/text=normalize_thai(b.text)/text=b.text/'

mutate "破坏页码校验(page 越界不再拒绝)" \
  's/if not 1 <= self.page <= max_page:/if False:/'

mutate "破坏 bbox 校验(非法矩形放行)" \
  's/if not (x1 > x0 and y1 > y0):/if False:/'

mutate "破坏重复 id 校验" \
  's/if b.id in seen:/if False:/'

mutate "破坏空文档校验(解析失败静默通过)" \
  's/if not self.blocks:/if False:/'

mutate "破坏 table 一致性校验" \
  's/if self.type == "table" and self.table is None:/if False:/'

mutate "破坏泰文识别(has_thai 永远为假)" \
  's/return bool(_THAI_RE.search(text))/return False/'

# 反向对照
sed -i.tmp 's/# 泰文字符范围/# 注释改动/' docir.py 2>/dev/null; rm -f docir.py.tmp
if $PY test_docir.py >/dev/null 2>&1; then
  echo "  ${GRN}✓${OFF} 反向对照:无害改动后测试仍通过(无假阳性)"
else
  echo "  ${RED}✗${OFF} 反向对照:无害改动竟然让测试变红 —— 测试太脆"; fail=1
fi
cp .docir.bak docir.py

echo
[ "$fail" -eq 0 ] && echo "${GRN}✓ 变异测试通过:各条属性都被测试真正兜住,且无假阳性${OFF}" \
                  || echo "${RED}✗ 变异测试失败${OFF}"
exit $fail
