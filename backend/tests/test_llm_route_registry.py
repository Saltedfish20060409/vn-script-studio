"""所有能到达模型调用的 HTTP 路由，都必须登记在案（含"为什么不用管"的也要写明理由）。

## 为什么需要这个测试

前端预算表（`frontend/src/api/timeouts.test.ts`）是**白名单**：新加一个会调模型的端点、
忘了给它预算，就回到"前端到点掐断、后端其实还在跑"的老 bug（用户报的正是这个）。
这个测试用 AST 自动找出「路由 → 处理函数 → 是否触达 chat_completions」，
漏登记的、或登记了却已改名的，都会立刻红。

识别范围与局限（写清楚，避免误以为它很聪明）：
- 触达关系按**函数名**在同模块内做一层展开（`run_x` 调 `_chat`，`_chat` 调模型）；
  跨模块的多层间接调用（如 `run_agent` → `_agent_steps` → `_chat_json`）不在自动发现范围内，
  这类端点要么在下面登记，要么走 EXEMPT 并写明"SSE/作业，不受前端总超时约束"。
- 因此它**宁多勿漏**：名字撞车导致多报时，在登记表里补一条并写清理由即可。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
API = APP / "api" / "v1"
FRONTEND_CONTRACTS = (
    Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "api" / "timeouts.test.ts"
)

CALL = re.compile(r"(chat_completions|stream_chat_completions)\s*\(")

#: 已登记的路由：值 = 这个端点的预算/作业化处置（写给人看，便于复核）。
REGISTERED: dict[str, str] = {
    "POST /projects/{project_id}/brainstorm": "两轮串行：UI 走 async_mode 作业，同步路径保留并给 long 档",
    "POST /projects/{project_id}/characters/{character_id}/voice/generate": "单次生成 → chat",
    "POST /projects/{project_id}/characters/{character_id}/voice/synthesize": "单次生成 → chat",
    "POST /projects/{project_id}/characters/{character_id}/workshop/chat": "单轮对话 → chat",
    "POST /{project_id}/consistency/audit": "单次审计 → write",
    "POST /projects/{project_id}/harness/run": "API-only（前端无调用方）：预算由调用方自定",
    "POST /{project_id}/marks/revise": "首轮 + 校验不过时一轮重写 → long",
    "POST /projects/{project_id}/pipeline/ledger/digest": "单次补全 → quick",
    "POST /projects/{project_id}/pipeline/run": "SSE/作业：前端只等登记（upload 档），进度走 SSE 或作业轮询",
    # 下面两条**自动发现扫不到**（它们是二级间接触达：路由 → gate.py → stage_check_async
    # → beat_check / voice_check），属于该发现机制的已知盲区，所以手工登记在这里。
    "POST /projects/{project_id}/pipeline/gate": "两轮串行（节拍 QUICK → 声线 CHAT）→ write；二级间接触达",
    "POST /projects/{project_id}/pipeline/check": "同 gate 的检查路径（API-only）→ 预算由调用方自定",
    "POST /{project_id}/generate-rpy": "正文→Ren'Py 单次生成 → chat",
    "POST /{project_id}/map/extract": "单次抽取 → chat",
    "POST /{project_id}/localization/translate": "一批句子的单次翻译 → chat",
    "POST /{project_id}/analysis/consistency-scan": "窗口并发（HTTP 入口默认 16 窗上界）→ long",
    "POST /{project_id}/analysis/facts/scan": "单次抽取 → chat",
    "POST /{project_id}/agent/chapter-revise": "两轮（json+text）→ batch；同时支持 async_mode 作业",
    "POST /{project_id}/agent/ingest-settings": "单次摄入 → chat",
    "POST /{project_id}/agent/pre-questions": "短问答 → quick",
    "POST /{project_id}/voice-check": "单次核对 → chat",
    "POST /{project_id}/ai": "API-only（前端无调用方，legacy）",
    "POST /{project_id}/recap": "单次生成 → write",
    "POST /test-llm": "设置页测试连接 → probe",
    "POST /{project_id}/style-memory/learn": "单次学习 → write",
}

#: 已自动发现到、但**不需要**前端预算的路由（必须写明理由）。
EXEMPT: dict[str, str] = {
    "POST /{project_id}/agent/stream": (
        "SSE：不设总超时，靠 : keepalive 心跳判活 + 前端 90s 无字节看门狗；"
        "断点续跑靠 run_state 检查点。它经 run_agent → _agent_steps → _chat_json "
        "二级间接触达，自动发现扫不到，属手工登记。"
    ),
}


def llm_entry_names() -> set[str]:
    """收集「函数名」：调用了模型的函数，以及同模块内调用它们的函数（一层展开）。"""
    names: set[str] = set()
    for path in sorted(APP.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        if not CALL.search(src):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:  # pragma: no cover - 语法错误应由 ruff/import 先拦住
            continue
        direct: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                seg = ast.get_source_segment(src, node) or ""
                if CALL.search(seg):
                    direct.add(node.name)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                seg = ast.get_source_segment(src, node) or ""
                if any(re.search(rf"\b{re.escape(d)}\s*\(", seg) for d in direct):
                    direct.add(node.name)
        names |= direct
    return names


def routes() -> dict[str, tuple[str, str]]:
    """返回 {路由: (所在文件, 处理函数源码)}。"""
    found: dict[str, tuple[str, str]] = {}
    for path in sorted(API.glob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            m = re.match(r'@router\.(get|post|put|patch|delete)\("([^"]+)"', line.strip())
            if not m:
                continue
            route = f"{m.group(1).upper()} {m.group(2)}"
            for j in range(i + 1, min(i + 12, len(lines))):
                if not re.match(r"^(?:async\s+)?def\s+\w+", lines[j]):
                    continue
                end = len(lines)
                for k in range(j + 1, len(lines)):
                    if re.match(r"^(?:async\s+)?def\s|@router\.", lines[k]):
                        end = k
                        break
                found[route] = (path.name, "\n".join(lines[j:end]))
                break
    return found


def discovered_llm_routes() -> set[str]:
    """"自动发现"：处理函数体里出现了任一 LLM 入口函数名，就认为这个路由会调模型。"""
    names = llm_entry_names()
    out: set[str] = set()
    for route, (_file, body) in routes().items():
        if any(re.search(rf"\b{re.escape(n)}\s*\(", body) for n in names):
            out.add(route)
    return out


def test_every_llm_route_is_registered():
    """漏登记 = 将来又出现"前端掐断、后端还在跑"。"""
    missing = sorted(discovered_llm_routes() - set(REGISTERED) - set(EXEMPT))
    assert not missing, (
        "这些路由会调用模型，但既没登记也没写明豁免理由：\n  "
        + "\n  ".join(missing)
        + "\n\n请在前端 frontend/src/api/timeouts.test.ts 的 CONTRACTS 里给它一个预算，"
        "或在这里按 EXEMPT 登记并写明为什么不需要（SSE/作业/仅内部调用）。"
    )


def test_registered_routes_still_exist():
    """登记了却已改名/删除 = 预算表与实际脱节，必须同步。"""
    actual = set(routes())
    stale = sorted((set(REGISTERED) | set(EXEMPT)) - actual)
    assert not stale, "登记表里的这些路由在 api/v1 里已不存在（改名了？）：\n  " + "\n  ".join(
        stale
    )


def test_registered_and_exempt_entries_explain_themselves():
    """每条登记都要有说明——否则后人无从判断该给多少预算。"""
    thin = [k for k, v in {**REGISTERED, **EXEMPT}.items() if len(v.strip()) < 8]
    assert not thin, f"这些登记缺少说明：{thin}"


def test_frontend_budget_table_is_wired_to_the_same_backend():
    """前端预算表必须真的在读后端源码（否则它只是自说自话）。"""
    src = FRONTEND_CONTRACTS.read_text(encoding="utf-8")
    for needle in ("llm_budget.py", "config.py", "thinkingFactor", "backendBudgets"):
        assert needle in src, f"前端预算表不再引用 {needle}，跨语言校验已失效"
    # 作业化端点必须在两边都留痕（后端 async_mode + 前端 startBrainstormJob）
    assert 'kind="brainstorm"' in (API / "lenses.py").read_text(encoding="utf-8")
    assert "startBrainstormJob" in src
