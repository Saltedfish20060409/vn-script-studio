"""线上 Writing Turn vs 本地新代码：双臂出稿 + 甲乙盲评包。

主结论必须来自人评五维（见 docs/blind-ab.md）；本模块只负责：
- 同夹具、同指令双臂出稿
- 随机甲乙标签（同 seed 可复现）
- 结构门禁（vn-sota overall 相对冻结基线）

环境变量：
- VNSS_BASELINE_URL：线上 API 根（如 https://example.com）
- VNSS_BASELINE_TOKEN：Bearer access token
- VNSS_BASELINE_PROJECT_ID：线上工程 id（可选；缺省用夹具仅跑本地臂）
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.domain.types import VnProject

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "vn_compare"
DEFAULT_EPSILON = 0.02

DISCLAIMER = (
    "主结论须来自人评五维盲测；结构门禁只证明「没变坏」。"
    "人评完成前不得宣称超过线上部署。"
)

DEFAULT_RUBRIC = {
    "连贯性": "人物状态/地点/已披露事实是否前后一致，有无死人说话或时空跳变",
    "声线": "主要角色口吻是否贴合人设，有无说明书腔/统一腔",
    "可演性": "是否适合视觉小说演出（对白+短旁白+动作），有无假选择或引擎语法泄漏",
    "钩子推进": "是否推进或呼应未回收氛围/伏笔，而非空转闲聊或另开无关支线",
    "克制与温度": "信息是否克制、情绪是否有毛边，有无总结前文或主题宣讲",
}

DEFAULT_VETO = [
    "死人出场或已否事实被推翻",
    "大量引擎指令（label/jump/menu:/scene）泄漏进正文",
    "选项全是整齐同意、无剧情代价（假选择）",
    "整段说明书/导览/任务总结，几乎无戏",
]


def fixture_dir() -> Path:
    return FIXTURE_DIR


def load_cases(*, limit: int = 0) -> List[Dict[str, Any]]:
    path = FIXTURE_DIR / "cases.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    if limit and limit > 0:
        return list(rows)[: int(limit)]
    return list(rows)


def load_compare_project() -> VnProject:
    """夹具工程：优先 project.json，否则用 demo。"""
    path = FIXTURE_DIR / "project.json"
    if path.is_file():
        from app.core.project import normalize_project

        raw = json.loads(path.read_text(encoding="utf-8"))
        return normalize_project(raw)
    from app.core.demo import create_demo_project

    return create_demo_project()


def load_structure_baseline() -> Dict[str, Any]:
    path = FIXTURE_DIR / "vn_sota_baseline.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_structure_baseline(path: Optional[Path] = None) -> Dict[str, Any]:
    """对夹具跑 vn-sota 并写入冻结基线。"""
    from app.core.eval_vn_sota import build_overall_table, run_vn_sota_suite

    project = load_compare_project()
    focus = project.chapters[0].id if project.chapters else None
    suite = run_vn_sota_suite(project, chapter_id=focus, seed=20260409)
    table = build_overall_table(suite)
    payload = {
        "overall": suite.get("overall"),
        "suite": suite.get("suite"),
        "seed": suite.get("seed"),
        "weighted": suite.get("weighted"),
        "table": table,
    }
    out = path or (FIXTURE_DIR / "vn_sota_baseline.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def structure_gate(
    *,
    epsilon: float = DEFAULT_EPSILON,
) -> Dict[str, Any]:
    """本地夹具 vn-sota vs 冻结基线。"""
    from app.core.eval_vn_sota import run_vn_sota_suite

    project = load_compare_project()
    focus = project.chapters[0].id if project.chapters else None
    suite = run_vn_sota_suite(project, chapter_id=focus, seed=20260409)
    baseline = load_structure_baseline()
    base_overall = baseline.get("overall")
    now = suite.get("overall")
    passed = True
    delta = None
    if isinstance(base_overall, (int, float)) and isinstance(now, (int, float)):
        delta = float(now) - float(base_overall)
        passed = delta >= -abs(float(epsilon))
    elif not baseline:
        passed = True  # 无基线时不挡，只提示
    return {
        "passed": passed,
        "epsilon": float(epsilon),
        "baselineOverall": base_overall,
        "currentOverall": now,
        "delta": delta,
        "suite": suite.get("suite"),
        "note": None if baseline else "missing_baseline",
    }


def _auth_headers(token: str) -> Dict[str, str]:
    t = (token or "").strip()
    if t.lower().startswith("bearer "):
        return {"Authorization": t, "Content-Type": "application/json"}
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def parse_sse_done_content(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """从 SSE 文本里取 done.content；返回 (content, error)。"""
    content = None
    err = None
    for block in (raw or "").split("\n\n"):
        line = next(
            (ln for ln in block.split("\n") if ln.startswith("data:")),
            "",
        )
        if not line:
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if evt.get("type") == "error":
            err = str(evt.get("message") or "error")[:300]
        if evt.get("type") == "done":
            content = str(evt.get("content") or "").strip() or content
    return content, err


async def fetch_deployed_draft(
    *,
    base_url: str,
    token: str,
    project_id: str,
    instruction: str,
    chapter_id: Optional[str],
    model_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """打线上 /agent/turn，取草稿。"""
    import httpx

    root = (base_url or "").rstrip("/")
    if root.endswith("/api/v1"):
        url = f"{root}/projects/{project_id}/agent/turn"
    else:
        url = f"{root}/api/v1/projects/{project_id}/agent/turn"
    body: Dict[str, Any] = {
        "capability": "write",
        "write_op": "continue",
        "instruction": instruction,
        "chapter_id": chapter_id,
        "writing_assist": "strong",
        "enrich_context": True,
        "run_capability_probes": True,
    }
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                url, headers=_auth_headers(token), json=body
            )
            if resp.status_code >= 400:
                return {
                    "arm": "deployed",
                    "error": f"HTTP {resp.status_code}: {resp.text[:240]}",
                    "text": "",
                }
            text, err = parse_sse_done_content(resp.text)
            if err and not text:
                return {"arm": "deployed", "error": err, "text": ""}
            return {
                "arm": "deployed",
                "text": text or "",
                "error": err,
                "modelHint": model_hint,
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "arm": "deployed",
            "error": f"{type(exc).__name__}:{str(exc)[:200]}",
            "text": "",
        }


async def run_local_draft(
    project: VnProject,
    *,
    instruction: str,
    chapter_id: Optional[str],
    api_key: str,
    base_url: str,
    model: str,
) -> Dict[str, Any]:
    """本机 stage_write（新代码）。"""
    from app.core.ai import DeepSeekConfig
    from app.core.pipeline.orchestrator import stage_write
    from app.core.writing_strategy import (
        profile_from_assist,
        reset_writing_strategy,
        set_writing_strategy,
    )

    if not (api_key or "").strip():
        return {"arm": "local", "error": "missing_local_api_key", "text": ""}
    cfg = DeepSeekConfig(
        apiKey=api_key.strip(),
        baseUrl=(base_url or "https://api.deepseek.com").strip(),
        model=(model or "deepseek-v4-flash").strip(),
    )
    reset_writing_strategy()
    set_writing_strategy(profile_from_assist("strong"))
    try:
        result = await stage_write(
            cfg,
            project,
            instruction=instruction,
            chapter_id=chapter_id,
            write_op="continue",
            writing_assist="strong",
            enrich_context=True,
        )
        return {
            "arm": "local",
            "text": str(result.get("content") or "").strip(),
            "model": result.get("model"),
            "contextIncluded": result.get("contextIncluded"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "arm": "local",
            "error": f"{type(exc).__name__}:{str(exc)[:200]}",
            "text": "",
        }


def build_blind_pack(
    cases: List[Dict[str, Any]],
    *,
    seed: int,
    model: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """cases 项需含 id/task/instruction/deployed/local 文本。"""
    rng = random.Random(int(seed))
    items = []
    key: Dict[str, Any] = {}
    for c in cases:
        labels = ["甲", "乙"]
        rng.shuffle(labels)
        mapping = {"deployed": labels[0], "local": labels[1]}
        d_txt = str((c.get("deployed") or {}).get("text") or "")
        l_txt = str((c.get("local") or {}).get("text") or "")
        if not d_txt or not l_txt:
            continue
        item = {
            "id": c.get("id"),
            "task": c.get("task"),
            "instruction": c.get("instruction"),
            mapping["deployed"]: d_txt,
            mapping["local"]: l_txt,
        }
        items.append(item)
        key[str(c.get("id"))] = {
            mapping["deployed"]: "deployed",
            mapping["local"]: "local",
        }
    blind = {
        "mode": "deploy_compare",
        "model": model,
        "seed": int(seed),
        "arms": {"deployed": "线上 Writing Turn", "local": "本地新代码"},
        "rubric": DEFAULT_RUBRIC,
        "一票否决": DEFAULT_VETO,
        "disclaimer": DISCLAIMER,
        "items": items,
    }
    return blind, key


def attach_human_scores_appendix(
    vn_sota_result: Dict[str, Any],
    scores_path: Path,
) -> Dict[str, Any]:
    """人评汇总 JSON 挂 appendix，不进主 overall。"""
    raw = json.loads(Path(scores_path).read_text(encoding="utf-8"))
    appendix = dict(vn_sota_result.get("appendix") or {})
    appendix["humanFiveDim"] = {
        "note": "人评五维为主结论，不计入垂直 overall",
        "source": str(scores_path),
        "data": raw,
    }
    out = dict(vn_sota_result)
    out["appendix"] = appendix
    return out


async def run_deploy_compare(
    *,
    seed: int = 20260409,
    case_limit: int = 0,
    baseline_url: Optional[str] = None,
    baseline_token: Optional[str] = None,
    baseline_project_id: Optional[str] = None,
    local_api_key: Optional[str] = None,
    local_base_url: Optional[str] = None,
    local_model: Optional[str] = None,
    skip_deployed: bool = False,
    mock_texts: Optional[Dict[str, Tuple[str, str]]] = None,
    epsilon: float = DEFAULT_EPSILON,
) -> Dict[str, Any]:
    """跑完整对照；``mock_texts`` 供单测（case_id -> (deployed, local)）。"""
    from app.config import get_settings

    settings = get_settings()
    url = (baseline_url or os.environ.get("VNSS_BASELINE_URL") or "").strip()
    token = (baseline_token or os.environ.get("VNSS_BASELINE_TOKEN") or "").strip()
    pid = (
        baseline_project_id
        or os.environ.get("VNSS_BASELINE_PROJECT_ID")
        or ""
    ).strip()
    api_key = (local_api_key or settings.deepseek_api_key or "").strip()
    base = (local_base_url or settings.deepseek_base_url or "").strip()
    model = (local_model or settings.deepseek_model or "deepseek-v4-flash").strip()

    project = load_compare_project()
    focus = project.chapters[0].id if project.chapters else None
    cases_spec = load_cases(limit=case_limit)
    gate = structure_gate(epsilon=epsilon)

    results: List[Dict[str, Any]] = []
    for spec in cases_spec:
        cid = str(spec.get("id") or "")
        instruction = str(spec.get("instruction") or "")
        entry: Dict[str, Any] = {
            "id": cid,
            "task": spec.get("task") or "continue",
            "instruction": instruction,
            "chapterId": focus,
        }
        if mock_texts and cid in mock_texts:
            d_txt, l_txt = mock_texts[cid]
            entry["deployed"] = {"arm": "deployed", "text": d_txt}
            entry["local"] = {"arm": "local", "text": l_txt}
        else:
            if skip_deployed or not url or not token or not pid:
                entry["deployed"] = {
                    "arm": "deployed",
                    "error": "skipped_or_missing_baseline_env",
                    "text": "",
                }
            else:
                entry["deployed"] = await fetch_deployed_draft(
                    base_url=url,
                    token=token,
                    project_id=pid,
                    instruction=instruction,
                    chapter_id=focus,
                    model_hint=model,
                )
            entry["local"] = await run_local_draft(
                project,
                instruction=instruction,
                chapter_id=focus,
                api_key=api_key,
                base_url=base,
                model=model,
            )
        results.append(entry)

    blind, key = build_blind_pack(results, seed=seed, model=model)
    return {
        "mode": "deploy_compare",
        "seed": seed,
        "model": model,
        "disclaimer": DISCLAIMER,
        "structureGate": gate,
        "baseline": {
            "url": url or None,
            "projectId": pid or None,
            "configured": bool(url and token and pid),
        },
        "cases": results,
        "blind": blind,
        "key": key,
        "summary": {
            "caseCount": len(results),
            "blindItemCount": len(blind.get("items") or []),
            "structurePassed": gate.get("passed"),
            "deployedErrors": sum(
                1 for c in results if (c.get("deployed") or {}).get("error")
            ),
            "localErrors": sum(
                1 for c in results if (c.get("local") or {}).get("error")
            ),
        },
    }


def format_blind_markdown(blind_doc: Dict[str, Any], key_name: str) -> str:
    """盲评工作纸 Markdown（不含答案）。与 cli.blind_markdown 同形。"""
    items = blind_doc.get("items") or []
    lines = [
        "# 对照盲评工作纸（甲 / 乙 · 线上 vs 本地）",
        "",
        f"- 模型：`{blind_doc.get('model') or ''}`　种子：`{blind_doc.get('seed')}`",
        "- 甲、乙两稿：同一指令；一臂为线上 Writing Turn，一臂为本地新代码。",
        "- 请只按 Rubric 打分，**不要猜**哪份是线上。",
        f"- 拆封用同目录的 `{key_name}`，评完再看。",
        "",
        f"> {DISCLAIMER}",
        "",
        "## Rubric（每维 1–4 分，必须引用原文作证据）",
        "",
    ]
    lines += [f"- **{k}**：{v}" for k, v in (blind_doc.get("rubric") or {}).items()]
    lines += ["", "## 一票否决（命中任一 → 该稿淘汰）", ""]
    lines += [f"- {v}" for v in (blind_doc.get("一票否决") or [])]
    lines += [
        "",
        "## 计分表",
        "",
        "| 用例 | 甲 总分 | 乙 总分 | 更好的一稿 | 一票否决 |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {it.get('id')} |  |  |  |  |" for it in items]
    lines += ["", f"> 汇总时把「更好的一稿」逐例对齐 `{key_name}`。", ""]
    for it in items:
        lines += [
            f"## {it.get('id')}（{it.get('task')}）",
            "",
            f"**要求**：{it.get('instruction') or ''}",
            "",
        ]
        for lab in ("甲", "乙"):
            lines += [f"### 稿 {lab}", "", it.get(lab) or "（缺失）", ""]
    return "\n".join(lines)


def write_compare_artifacts(report: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    """写出 out.json / blind.json / blind.md / key.json。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "report": str(out_dir / "deploy-compare.json"),
        "blind": str(out_dir / "blind-deploy.json"),
        "key": str(out_dir / "blind-deploy-key.json"),
        "md": str(out_dir / "blind-deploy.md"),
    }
    Path(paths["report"]).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    blind = report.get("blind") or {}
    key = report.get("key") or {}
    Path(paths["blind"]).write_text(
        json.dumps(blind, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(paths["key"]).write_text(
        json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(paths["md"]).write_text(
        format_blind_markdown(blind, Path(paths["key"]).name) + "\n",
        encoding="utf-8",
    )
    return paths
