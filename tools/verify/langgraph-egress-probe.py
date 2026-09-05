# -*- coding: utf-8 -*-
"""P0 #1 验证：LangGraph 在不设任何环境变量时，是否有任何出网请求。

方法：在 socket 层打桩，记录所有 connect 目标，并**拒绝**非本机连接。
这比抓包更严格 —— 任何试图出网的行为都会被记录且失败，不会被静默重试掩盖。
"""
import os, sys, socket, json

# 关键：不设任何 LANGSMITH_* / LANGCHAIN_* 环境变量。先确认干净。
leaked = {k: v for k, v in os.environ.items()
          if k.upper().startswith(("LANGSMITH", "LANGCHAIN"))}
print("环境变量泄漏检查:", leaked if leaked else "干净（无 LANGSMITH_/LANGCHAIN_ 变量）")

ATTEMPTS = []
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex

def _log_and_block(addr):
    host = addr[0] if isinstance(addr, tuple) else str(addr)
    local = host in ("127.0.0.1", "::1", "localhost")
    ATTEMPTS.append({"host": host, "local": local})
    if not local:
        raise OSError("BLOCKED_BY_PROBE: 试图连接外部地址 %r" % (addr,))

def connect(self, addr):
    _log_and_block(addr)
    return _real_connect(self, addr)

def connect_ex(self, addr):
    _log_and_block(addr)
    return _real_connect_ex(self, addr)

socket.socket.connect = connect
socket.socket.connect_ex = connect_ex

# DNS 也拦：解析本身就是出网信号
_real_getaddrinfo = socket.getaddrinfo
def getaddrinfo(host, *a, **kw):
    if host not in ("127.0.0.1", "::1", "localhost"):
        ATTEMPTS.append({"host": "DNS:%s" % host, "local": False})
        raise socket.gaierror("BLOCKED_BY_PROBE: DNS 解析 %r" % host)
    return _real_getaddrinfo(host, *a, **kw)
socket.getaddrinfo = getaddrinfo

# ---- 跑一个真实的、带人工审批断点的 LangGraph 流程 ----
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command

class S(TypedDict):
    draft: str
    approved: bool

def draft_node(state: S):
    return {"draft": "会议纪要草稿：三条待办已抽出"}

def approval_node(state: S):
    decision = interrupt({"draft": state["draft"]})   # 这就是「等人点头」的断点
    return {"approved": decision == "approve"}

def publish_node(state: S):
    return {"draft": state["draft"] + " [已发布]"}

g = StateGraph(S)
g.add_node("draft", draft_node)
g.add_node("approval", approval_node)
g.add_node("publish", publish_node)
g.add_edge(START, "draft")
g.add_edge("draft", "approval")
g.add_edge("approval", "publish")
g.add_edge("publish", END)
app = g.compile(checkpointer=InMemorySaver())

cfg = {"configurable": {"thread_id": "t1"}}
r1 = app.invoke({"draft": "", "approved": False}, cfg)
print("① 流程在审批断点挂起:", "__interrupt__" in r1)
r2 = app.invoke(Command(resume="approve"), cfg)
print("② 恢复后完成:", r2["approved"], "|", r2["draft"])

ext = [a for a in ATTEMPTS if not a["local"]]
print("\n=== 结果 ===")
print("总连接尝试:", len(ATTEMPTS))
print("外部连接尝试:", len(ext), ext if ext else "（无）")
print("判定:", "零出网 ✅" if not ext else "有出网 ❌")
json.dump({"attempts": ATTEMPTS, "external": ext}, open("result.json","w"))
