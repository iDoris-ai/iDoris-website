#!/usr/bin/env bash
#
# iDoris.ai — 发布到 Cloudflare Pages
#
#   ./scripts/deploy.sh              发布
#   ./scripts/deploy.sh --check      只做本地检查，不发布（dry run）
#
# 流程：本地自检 → 推到 Cloudflare → 校验线上每个页面返回 200
#
# 自检的设计原则：只拦「不会自己报错的错」。语法错、404，浏览器和 CI 都会喊；
# 真正危险的是那些悄悄不生效的东西 —— i18n.js 改名后中英切换静默失效、
# 忘了压图导致首页悄悄变重 3MB。这些没人会发现，所以在这里设硬闸。
#
set -euo pipefail

PROJECT="idoris-website"
DIST="site"
PROD_URL="https://${PROJECT}.pages.dev"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
ok()   { echo "${GRN}✓${OFF} $1"; }
warn() { echo "${YEL}!${OFF} $1"; }
die()  { echo "${RED}✗ $1${OFF}" >&2; exit 1; }

# 站点里所有需要存在的页面（新增页面时加到这里）
PAGES=(
  "/"
  "/join"
  "/friends"
  "/buy"
  "/cards"
  "/card"
  "/hello"
  "/pricing"
  "/services"
)

# ─────────────────────────────────────────────
# 1. 本地自检
# ─────────────────────────────────────────────
echo "${DIM}── 本地自检 ──${OFF}"

[ -d "$DIST" ] || die "找不到 $DIST/ 目录"
[ -f "$DIST/index.html" ] || die "缺少 $DIST/index.html"

for p in "${PAGES[@]}"; do
  f="$DIST${p}"
  [ "$p" = "/" ] && f="$DIST/index.html"
  # Cloudflare Pages 的 clean URL 有两种落地方式：/join 由 join.html 提供（补 .html 再找一次），
  # /hello 由 hello/index.html 提供（补 /index.html 再找一次）——都试过还没有才算缺失。
  [ -f "$f" ] || f="${f}.html"
  [ -f "$f" ] || f="$DIST${p}/index.html"
  [ -f "$f" ] || die "页面缺失：${p}（PAGES 里声明了但文件不在）"
done
ok "${#PAGES[@]} 个页面文件齐全"

# 站内引用自检：href 和 src 都要查。
# src 尤其重要 —— assets/i18n.js 是硬依赖，它缺失/改名不会让页面报错，
# 只会让中英切换静默失效。只查 href 的话，这种断裂根本拦不住。
broken=0
while IFS= read -r link; do
  target="$DIST${link}"
  [ "$link" = "/" ] && target="$DIST/index.html"
  # clean URL：/join 命中 join.html 也算存在
  if [ ! -e "$target" ] && [ ! -e "${target}.html" ]; then
    echo "  ${RED}断链${OFF} $link"
    broken=$((broken + 1))
  fi
done < <(grep -rhoE '(href|src)="/[^"#]*"' "$DIST" --include='*.html' \
         | sed -E 's/^(href|src)="([^"]*)"$/\2/' | sort -u)

[ "$broken" -eq 0 ] || die "发现 $broken 条站内断链，已中止发布"
ok "站内引用（href + src）无断链"

# 逐页检查两件事。用 -print0 / read -d '' 遍历：`for f in $(find …)` 会按空白
# 切词，文件名一旦含空格就被拆成两半，两个片段都 grep 不到 —— 检查会静默跳过
# 那个页面，而不是报错。这正是这些闸要防的那类「悄悄不生效」。
#
# 1) 多语硬依赖：页面有切换按钮就必须引入 i18n 脚本，否则点了没反应。
#    探针用 lang-btn 而非 class="lang" —— 后者是精确串匹配，容器一旦变成
#    class="lang xxx" 就会失配，检查悄悄退化成死代码。
#
# 2) 首帧正确性：<html> 必须静态带 data-lang="en"。按语言分支的 CSS
#    （:root[data-lang="zh"] .hero h1 …）挂在这个属性上。少了它，首帧退回
#    基础样式，等 i18n.js 跑完才跳 —— 布局抖一下。i18n.js 自己也会设这个
#    属性，但那太晚了。
missing_i18n=0
missing_lang=0
while IFS= read -r -d '' f; do
  # macOS 自带 bash 3.2（2007 年）的两个坑：
  #   1. 不认 ${f#"$DIST"} 这种嵌套引号 —— $DIST 固定是 "site"，无通配符，直接展开安全
  #   2. 变量名解析不是多字节感知的：写 "$rel（…" 会把全角括号的字节吃进变量名，
  #      于是 set -u 报 rel? unbound。必须写成 ${rel} 来界定边界。
  rel="${f#$DIST}"
  if grep -q 'lang-btn' "$f" && ! grep -qE 'assets/i18n[^"]*\.js' "$f"; then
    echo "  ${RED}缺 i18n 脚本${OFF} ${rel}（有切换按钮却没引入脚本）"
    missing_i18n=$((missing_i18n + 1))
  fi
  if ! grep -qE '<html[^>]*data-lang="en"' "$f"; then
    echo "  ${RED}缺 data-lang${OFF} ${rel}（首帧样式会错，随后抖动）"
    missing_lang=$((missing_lang + 1))
  fi
done < <(find "$DIST" -name '*.html' -print0)

[ "$missing_i18n" -eq 0 ] || die "发现 $missing_i18n 个页面的语言切换会失效，已中止发布"
ok "多语脚本引入完整"
[ "$missing_lang" -eq 0 ] || die "发现 $missing_lang 个页面首帧样式会错，已中止发布"
ok "首帧语言属性完整"

# HTML 结构：标签平衡 + data-zh/data-th 属性值没被裸引号截断。
# 上面所有检查都是文本级的（grep 断链、grep 脚本名、比文件大小），一行 HTML 都不解析，
# 所以对「属性被截断、整页结构塌掉」这类错完全无感 —— 2026-09-05 真栽过一次，
# /pricing 的横幅写成 data-zh="…<span class="sub">…"，页面结构从那行起全乱，
# 而这个脚本当时全绿。浏览器也不喊：HTML 是容错的，它照样渲染一棵错的树。
# 判据本身带正对照（会先自证「能变红」），细节见 check-html.py 的注释。
python3 "$ROOT/scripts/check-html.py" "$DIST" || die "HTML 结构有问题，已中止发布"

# 单文件不能超过 Cloudflare Pages 的 25MB 上限
big=""
while IFS= read -r -d '' f; do big="$f"; break; done < <(find "$DIST" -type f -size +20M -print0)
[ -z "$big" ] || die "文件过大，超出 Cloudflare Pages 限制：$big"

# 图片预算：忘记压缩不会报错，只会让页面悄悄变重 —— 所以设一道硬闸。
# Doris 插画走量化压缩后通常在 250-380KB。生成器直出的原始 PNG
# 常常 1-2MB，一旦有人直接扔进来，这里拦住。
IMG_BUDGET_KB=400
oversized=0
while IFS= read -r -d '' f; do
  kb=$(( $(wc -c < "$f") / 1024 ))
  if [ "$kb" -gt "$IMG_BUDGET_KB" ]; then
    echo "  ${RED}图片过大${OFF} ${f#$DIST} — ${kb}KB（上限 ${IMG_BUDGET_KB}KB，忘记压缩了？）"
    oversized=$((oversized + 1))
  fi
done < <(find "$DIST/assets" \( -name '*.png' -o -name '*.jpg' -o -name '*.jpeg' -o -name '*.gif' -o -name '*.webp' \) -print0)

[ "$oversized" -eq 0 ] || die "发现 $oversized 张图片超出预算，已中止发布。先跑 scripts/ink-to-transparent.py。"
ok "图片体积在预算内（每张 ≤ ${IMG_BUDGET_KB}KB）"

ok "资源体积正常（$(du -sh "$DIST" | cut -f1)）"

if [ "${1:-}" = "--check" ]; then
  echo "${GRN}本地检查通过${OFF}（--check 模式，未发布）"
  exit 0
fi

# ─────────────────────────────────────────────
# 2. 发布
# ─────────────────────────────────────────────
echo
echo "${DIM}── 发布到 Cloudflare Pages ──${OFF}"
npx wrangler pages deploy "$DIST" \
  --project-name="$PROJECT" \
  --branch=main \
  --commit-dirty=true

# ─────────────────────────────────────────────
# 3. 线上校验
# ─────────────────────────────────────────────
echo
echo "${DIM}── 线上校验（边缘节点可能有几十秒延迟）──${OFF}"

failed=0
for p in "${PAGES[@]}"; do
  code=""
  # 边缘冷启动时会短暂返回 5xx，重试几次再判失败
  for _ in 1 2 3 4 5 6; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -L "${PROD_URL}${p}" || echo 000)
    [ "$code" = "200" ] && break
    sleep 5
  done

  if [ "$code" = "200" ]; then
    ok "$(printf '%-24s' "$p") 200"
  else
    echo "${RED}✗${OFF} $(printf '%-24s' "$p") $code"
    failed=$((failed + 1))
  fi
done

echo
if [ "$failed" -eq 0 ]; then
  echo "${GRN}发布完成${OFF} → ${PROD_URL}"
else
  warn "$failed 个页面未返回 200。若刚发布，可能只是边缘还没同步——稍等再访问一次；持续异常就去 Cloudflare 面板看构建日志。"
  exit 1
fi
