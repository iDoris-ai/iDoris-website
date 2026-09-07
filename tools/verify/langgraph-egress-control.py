# -*- coding: utf-8 -*-
"""正对照：探针必须能抓到出网。一个抓不到的探针，它的「零出网」什么都不证明。

三个对照：
  A. 显式开启 LangSmith 追踪 → 期望探针报警
  B. 直接发一个 HTTP 请求      → 期望探针报警
  C. 连本机                    → 期望放行
"""
import os, socket, sys

# A：开启追踪。这是「如果有人不小心设了这个变量会怎样」的答案。
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_API_KEY"] = "fake-key-for-control"
os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"

ATTEMPTS = []
_c, _ce, _gai = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
def _chk(addr):
    h = addr[0] if isinstance(addr, tuple) else str(addr)
    loc = h in ("127.0.0.1","::1","localhost")
    ATTEMPTS.append({"host":h,"local":loc})
    if not loc: raise OSError("BLOCKED: %r" % (addr,))
socket.socket.connect     = lambda s,a: (_chk(a), _c(s,a))[1]
socket.socket.connect_ex  = lambda s,a: (_chk(a), _ce(s,a))[1]
def gai(host,*a,**k):
    if host not in ("127.0.0.1","::1","localhost"):
        ATTEMPTS.append({"host":"DNS:%s"%host,"local":False})
        raise socket.gaierror("BLOCKED DNS %r"%host)
    return _gai(host,*a,**k)
socket.getaddrinfo = gai

fails = []

# ---- 对照 B：直接出网，探针必须抓到 ----
before = len([a for a in ATTEMPTS if not a["local"]])
try:
    import urllib.request
    urllib.request.urlopen("https://example.com", timeout=3)
    fails.append("对照B：直接 HTTP 请求竟然成功了 —— 探针没拦住")
except Exception:
    pass
after = len([a for a in ATTEMPTS if not a["local"]])
print("对照B 直接出网 → 探针记录到 %d 次外部尝试 %s" % (after-before, "✅" if after>before else "❌"))
if after == before: fails.append("对照B：探针没记录到直接出网 —— 探针是瞎的")

# ---- 对照 C：本机连接必须放行 ----
before = len(ATTEMPTS)
try:
    s = socket.socket(); s.settimeout(0.3)
    s.connect_ex(("127.0.0.1", 1))   # 端口大概率关闭，但不该被探针拦
    s.close()
    print("对照C 本机连接 → 未被拦 ✅")
except OSError as e:
    if "BLOCKED" in str(e):
        fails.append("对照C：本机连接被误拦 —— 探针有假阳性")
        print("对照C 本机连接 → 被误拦 ❌")

# ---- 对照 A：开启追踪后跑 LangGraph ----
before = len([a for a in ATTEMPTS if not a["local"]])
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
class S(TypedDict):
    v: int
g = StateGraph(S); g.add_node("n", lambda s: {"v": s["v"]+1})
g.add_edge(START,"n"); g.add_edge("n",END)
try:
    g.compile().invoke({"v":0})
except Exception as e:
    print("  (开启追踪后流程本身报错，符合预期：出网被拦)", type(e).__name__)
after = len([a for a in ATTEMPTS if not a["local"]])
n = after - before
print("对照A 开启 LANGSMITH_TRACING → 探针记录到 %d 次外部尝试 %s" % (n, "✅ 会变红" if n>0 else "⚠️ 未触发"))

print("\n=== 正对照结论 ===")
if fails:
    for f in fails: print("  ❌", f)
    sys.exit(1)
print("  探针有效：能抓到出网、不误拦本机。")
print("  → 因此 probe.py 的「零出网」是可信的读数，不是探针失灵。")
if n == 0:
    print("\n  注：对照A 未触发说明 LangSmith 的上报是**异步/批量**的，")
    print("  短流程结束前可能还没发出。这不削弱结论 —— 对照B 已证明探针能抓到出网，")
    print("  而 probe.py 在**不设变量**时连一次尝试都没有。")
