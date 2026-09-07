#!/usr/bin/env bash
# 变异测试:破坏 DocIR 的关键属性,测试必须变红。
# 最要紧的两条:出处能回溯、泰文按字符切(不按空格)。
set -uo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
RED=$'\033[31m'; GRN=$'\033[32m'; OFF=$'\033[0m'
cp docir.py .docir.bak; cp extract.py .extract.bak; cp thai_dates.py .thai_dates.bak
cp summarize.py .summarize.bak
cp compare.py .compare.bak
cp rewrite.py .rewrite.bak
cp search.py .search.bak; cp translate.py .translate.bak
trap 'mv -f .docir.bak docir.py; mv -f .extract.bak extract.py; mv -f .thai_dates.bak thai_dates.py; mv -f .translate.bak translate.py; mv -f .summarize.bak summarize.py; mv -f .compare.bak compare.py; mv -f .rewrite.bak rewrite.py; mv -f .search.bak search.py' EXIT
fail=0
n_mut=0        # 自动计数 —— 写死数字会随着加变异而过期,
               # 而一句过期的「各条属性都被兜住」比不说更糟。
mutate() {   # $1=描述 $2=sed [$3=目标文件] [$4=测试文件]
  local f="${3:-docir.py}" t="${4:-test_docir.py}" b
  b=".${f%.py}.bak"
  n_mut=$((n_mut + 1))
  sed -i.tmp "$2" "$f" && rm -f "$f.tmp"
  # 变异必须真的改到文件。sed 匹配不上时会**静默无操作**,测试照常通过,
  # 于是一条过期变异会伪装成「测试漏洞」,把人引去改根本没问题的测试。
  # 重构挪走了被匹配的代码就会这样 —— 必须和真漏洞区分开。
  if cmp -s "$f" "$b"; then
    echo "  ${RED}✗${OFF} $1 —— 变异未生效(sed 没匹配上,多半是代码重构了),请更新这条变异"
    fail=1; return
  fi
  if $PY "$t" >/dev/null 2>&1; then    echo "  ${RED}✗${OFF} $1 —— 破坏后测试仍然通过,这条属性没有被兜住"; fail=1
  else
    echo "  ${GRN}✓${OFF} $1 —— 测试正确报警"
  fi
  cp "$b" "$f"
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

# ── thai_dates.py:不确定就不猜 ──────────────────────────────────
# 猜错 543 年,客户一眼看得出,然后不再相信这份文档里任何一个数字。

mutate "破坏歧义判定(歧义区间直接当佛历)" \
  's/    return YearResolution(\n/X/; s/^        raw_year, None, "ambiguous",$/        raw_year, y - BE_OFFSET, "BE",/' \
  thai_dates.py test_extract.py

mutate "破坏佛历换算(偏移量改错)" \
  's/^BE_OFFSET = 543/BE_OFFSET = 542/' \
  thai_dates.py test_extract.py

mutate "破坏佛历上界判定" \
  's/^_CERTAIN_BE_FROM = 2400/_CERTAIN_BE_FROM = 9999/' \
  thai_dates.py test_extract.py

mutate "破坏 resolve_or_raise(歧义时不再抛错)" \
  's/        raise DateAmbiguous(r.evidence)/        return 0/' \
  thai_dates.py test_extract.py

# ── extract.py:schema 与 citation 强制 ─────────────────────────

mutate "破坏多字段拒绝(schema 外的字段被忽略)" \
  's/        if spec is None:/        if False:/' \
  extract.py test_extract.py

mutate "破坏必填校验(缺字段也交付)" \
  's/^    if missing:/    if False:/' \
  extract.py test_extract.py

mutate "破坏 citation 强制(引用不存在的 block 也放行)" \
  's/        if blk is None:/        if False:/' \
  extract.py test_extract.py

mutate "破坏币种强制(无标记时默认 THB)" \
  's/    if currency is None:/    if False:/' \
  extract.py test_extract.py

mutate "破坏重复字段拒绝" \
  's/        if name in seen:/        if False:/' \
  extract.py test_extract.py

mutate "破坏不确定上报(uncertain 不再记录)" \
  's/                result.uncertain.append(name)/                pass/' \
  extract.py test_extract.py

# ── translate.py:两个坑 ─────────────────────────────────────────

mutate "破坏专有名词校验(被译掉也放行)" \
  's/        if lost:/        if False:/' \
  translate.py test_translate.py

mutate "破坏漏译拒绝(缺一段也交付)" \
  's/        if b.id not in model_output:/        if False and b.id not in model_output:/' \
  translate.py test_translate.py

mutate "破坏空译文拒绝" \
  's/        if not txt.strip():/        if False:/' \
  translate.py test_translate.py

mutate "破坏敬语一致检查(ครับ/ค่ะ 混用放行)" \
  's/    if _PARTICLE_MALE.search(text) and _PARTICLE_FEMALE.search(text):/    if False:/' \
  translate.py test_translate.py

mutate "破坏 formality 校验(任意值都收)" \
  's/    if formality not in FORMALITY:/    if False:/' \
  translate.py test_translate.py

mutate "破坏多余 block 拒绝" \
  's/    if extra:/    if False:/' \
  translate.py test_translate.py

mutate "破坏指示生成(不再列出不该翻的词)" \
  's/        lines.extend("  - %s" % t.source for t in terms)/        pass/' \
  translate.py test_translate.py

# ── summarize:合并不丢决议 ─────────────────────────────────────────
# 丢一条决议的表现是:输出完整、通顺、专业,没有任何东西报错,
# 而客户是照着这份纪要去执行的。这几条守的就是这件事。

mutate "破坏合并对账(丢了内容也不报)" \
  's/^    if lost:/    if False:/' summarize.py test_summarize.py

mutate "把决议列为可压缩(合并时允许丢)" \
  's/^    "decisions", "action_items", "obligations", "dates_and_amounts",/    "obligations", "dates_and_amounts",/' \
  summarize.py test_summarize.py

mutate "破坏去重身份(不含 owner/due —— 不同责任人的活被吃掉)" \
  's/^        return (_norm(self.text), self.block_id, _norm(self.owner), _norm(self.due))/        return (_norm(self.text), self.block_id, "", "")/' \
  summarize.py test_summarize.py

mutate "破坏空白归一(多个空格就算另一条 —— 对账形同虚设)" \
  's/^    return _WS.sub(" ", s).strip()/    return s/' summarize.py test_summarize.py

mutate "破坏出处校验(编造的 block_id 放行)" \
  's/^            if bid not in known:/            if False:/' summarize.py test_summarize.py

mutate "破坏骨架按类型分(一律用会议记录的骨架)" \
  's/^    skeleton = SKELETONS\[doc_type\]$/    skeleton = SKELETONS["meeting_minutes"]/' \
  summarize.py test_summarize.py

mutate "破坏类型校验(不认识的类型也放行)" \
  's/^    if doc_type not in DOC_TYPES:/    if False:/' summarize.py test_summarize.py

mutate "破坏多余小节拒绝(模型自由发挥也收下)" \
  's/^    if extra:/    if False:/' summarize.py test_summarize.py

mutate "破坏类型分歧留痕(默默取多数)" \
  's/^    if len(set(types)) > 1:/    if False:/' summarize.py test_summarize.py

mutate "破坏跨文档拦截(两份文档的决议混在一起)" \
  's/^    if len(doc_ids) != 1:/    if False:/' summarize.py test_summarize.py

# ── compare:漏一条就可能造成损失 ───────────────────────────────────
# 漏掉一条条款变更的表现是:差异清单看起来干净、专业、条理清楚,
# 少的那条不会以任何形式出现。客户签下去,损失是真金白银。

mutate "破坏覆盖对账(漏了块也不报)" \
  's/^    if problems:/    if False:/' compare.py test_compare.py

mutate "破坏漏配兜底(模型没提到的块就当没变)" \
  's/^        if bid.id not in used_old:/        if False:/' compare.py test_compare.py

mutate "破坏重复计入检测(同一块交代两次也放行)" \
  's/^            elif n > 1:/            elif False:/' compare.py test_compare.py

mutate "破坏重复配对拦截(同一块能配两次,凑数蒙混覆盖对账)" \
  's/^                if bid in used:/                if False:/' compare.py test_compare.py

mutate "破坏顺序调换判定(位置变了也算 unchanged)" \
  's/^            kind = "moved" if _position_changed(oid, nid, o_order, n_order) else "unchanged"/            kind = "unchanged"/' \
  compare.py test_compare.py

mutate "破坏数字风险升级(数字改了也用模型给的风险)" \
  's/^        if bn != nn:/        if False:/' compare.py test_compare.py

mutate "破坏泰文数字识别(泰数字的金额改动静默漏过)" \
  's/^    t = text.translate(_THAI_DIGITS)/    t = text/' compare.py test_compare.py

mutate "破坏空白归一(重新解析同一份文档就报一堆假改动)" \
  's/^    return _WS.sub(" ", s).strip()/    return s/' compare.py test_compare.py

mutate "破坏双向出处强制(只指一头也放行)" \
  's/^            if self.before is None or self.after is None:/            if False:/' \
  compare.py test_compare.py

mutate "破坏出处校验(编造的 block_id 放行)" \
  's/^            if bid is not None and bid not in table:/            if False:/' \
  compare.py test_compare.py

mutate "破坏同文档拦截(跟自己比也放行)" \
  's/^    if old.doc_id == new.doc_id:/    if False:/' compare.py test_compare.py

# ── rewrite:输出本来就该和原文不一样,所以编造最难被发现 ────────────
# 模型多写一句「保证当天回复」,读起来通顺、专业、符合语气要求,
# 没有任何东西会觉得不对劲 —— 然后它被发给客户,成了我们没打算做的承诺。

mutate "破坏编造数字拦截(原文没有的数字也放行)" \
  's/^        if fake_nums:/        if False:/' rewrite.py test_rewrite.py

mutate "破坏泰文数字识别(泰数字编造的金额静默漏过)" \
  's/^    return {n.replace(",", "") for n in _NUM.findall(text.translate(_THAI_DIGITS))}/    return {n.replace(",", "") for n in _NUM.findall(text)}/' \
  rewrite.py test_rewrite.py

mutate "破坏千分位归一(45,000 与 45000 被当成两个数)" \
  's/^    return {n.replace(",", "") for n in _NUM.findall(text.translate(_THAI_DIGITS))}/    return set(_NUM.findall(text.translate(_THAI_DIGITS)))/' \
  rewrite.py test_rewrite.py

mutate "破坏凭空承诺拦截" \
  's/^        if new_promises:/        if False:/' rewrite.py test_rewrite.py

mutate "破坏承诺检查的大小写不敏感(改个大小写就绕过)" \
  's/^    low = text.lower()/    low = text/' rewrite.py test_rewrite.py

mutate "承诺清单只留中文(英泰的承诺静默漏过)" \
  's/^    "guarantee", "guaranteed", "we promise", "commit to", "full refund",/    #/' \
  rewrite.py test_rewrite.py

mutate "破坏受众必填(没有判据也照改)" \
  's/^        if not self.target_audience.strip():/        if False:/' rewrite.py test_rewrite.py

mutate "破坏语气必填" \
  's/^        if not self.tone.strip():/        if False:/' rewrite.py test_rewrite.py

mutate "破坏长度上限(模型扩写多少都收下)" \
  's/^        if ratio > req.max_length_ratio:/        if False:/' rewrite.py test_rewrite.py

mutate "破坏长度的空白归一(空白多少影响判定)" \
  's/^    b = len(_norm(before))/    b = len(before)/' rewrite.py test_rewrite.py

mutate "破坏缺块拦截(少一块也交付)" \
  's/^    if missing:/    if False:/' rewrite.py test_rewrite.py

mutate "破坏丢数字留痕(漏掉的金额一声不吭)" \
  's/^        if lost:/        if False:/' rewrite.py test_rewrite.py

# ── search:一个自信地答错的检索系统,比没有检索系统更糟 ─────────────
# 坏法不对称:「什么都答没有」客户第一天就投诉;
# 「没命中也编一个」表现为回答率 100%,看起来像做得好,而它是编的。

mutate "破坏没命中就说没有(没检索到也让模型答)" \
  's/^    if not has_hit(retrieved, min_score):/    if False:/' search.py test_search.py

mutate "破坏命中阈值(返回了东西就算命中 —— 于是永远不会说没有)" \
  's/^    return bool(retrieved) and max(c.score for c in retrieved) >= min_score/    return bool(retrieved)/' \
  search.py test_search.py

mutate "破坏阈值可配(写死忽略传入值)" \
  's/^def has_hit(retrieved: list\[RetrievedChunk\], min_score: float = MIN_SCORE) -> bool:/def has_hit(retrieved, min_score=MIN_SCORE):\n    min_score = 0.0/' \
  search.py test_search.py

mutate "破坏「没有」的标准措辞(让模型自由发挥那句话)" \
  's/^        if text and text not in NOT_FOUND_TEXTS:/        if False:/' search.py test_search.py

mutate "破坏出处强制(声称找到却不给出处也放行)" \
  's/^    if not cited_ids:/    if False:/' search.py test_search.py

mutate "破坏出处真实性(引用没被检索到的块也放行)" \
  's/^    if unknown:/    if False:/' search.py test_search.py

mutate "破坏答案数字校验(编造的金额直接发给客户)" \
  's/^    if fabricated:/    if False:/' search.py test_search.py

mutate "破坏泰文数字识别(泰数字编造的金额静默漏过)" \
  's/^    return {n.replace(",", "") for n in _NUM.findall(text.translate(_THAI_DIGITS))}/    return {n.replace(",", "") for n in _NUM.findall(text)}/' \
  search.py test_search.py

mutate "破坏多语言「没有」(三种语言退化成同一句)" \
  's/^    text = {"th": NOT_FOUND_TH, "en": NOT_FOUND_EN}.get(lang, NOT_FOUND_ZH)/    text = NOT_FOUND_ZH/' \
  search.py test_search.py

mutate "破坏命中却答不了的留痕(标定阈值的依据没了)" \
  's/^        a.notes.append(/        _ = (/' search.py test_search.py

# 反向对照
sed -i.tmp 's/# 泰文字符范围/# 注释改动/' docir.py 2>/dev/null; rm -f docir.py.tmp
if $PY test_docir.py >/dev/null 2>&1; then
  echo "  ${GRN}✓${OFF} 反向对照:无害改动后测试仍通过(无假阳性)"
else
  echo "  ${RED}✗${OFF} 反向对照:无害改动竟然让测试变红 —— 测试太脆"; fail=1
fi
cp .docir.bak docir.py

echo
[ "$fail" -eq 0 ] && echo "${GRN}✓ 变异测试通过:${n_mut} 条属性都被测试真正兜住,且无假阳性${OFF}" \
                  || echo "${RED}✗ 变异测试失败${OFF}"
exit $fail
