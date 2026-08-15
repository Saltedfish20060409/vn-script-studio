"""Deterministic LLM ingest: attachment text → bible / characters / meta actions."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.domain.types import AgentAction, Character, VnProject

from .agent import apply_agent_actions, _normalize_bible_patch
from .ai import DeepSeekConfig
from .file_text import format_attachment_block
from .llm_http import chat_completions, content_from_response

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")

INGEST_SYSTEM = """你是视觉小说设定编辑。根据用户上传资料与当前工程摘要，产出要写入工程的结构化 JSON（不要 markdown 围栏）。

只输出：
{
  "message": "中文：说明写入了哪些栏",
  "bible": {
    "world": "世界观/规则，可空字符串表示不改",
    "background": "故事背景/前情",
    "outline": "大纲/节拍",
    "themes": "主题/基调/禁忌",
    "notes": "其他备忘"
  },
  "meta": { "title": "", "logline": "", "genre": "" },
  "characters": [
    {
      "displayName": "角色名",
      "defineName": "yingwen_id",
      "voice": "语气",
      "bio": "简介",
      "relationships": "关系摘要",
      "color": "#6b7280"
    }
  ]
}

规则：
- bible/meta 某字段若资料不足：省略该键或给 ""（空=不改）。
- 有实质内容才填写；从资料提炼，勿编造无关剧情。
- characters：资料中出现的重要角色都列出；已有角色用同一中文名，系统会 update；新角色会 add。
- defineName 仅英文小写+数字下划线。
"""


@dataclass
class SettingsIngestResult:
    message: str
    actions: List[AgentAction] = field(default_factory=list)
    project: Optional[VnProject] = None
    applied: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


def _parse_json_obj(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _char_index(project: VnProject) -> Dict[str, Character]:
    idx: Dict[str, Character] = {}
    for c in project.characters:
        idx[c.displayName.strip().lower()] = c
        idx[c.defineName.strip().lower()] = c
        idx[c.id.strip().lower()] = c
    return idx


def plan_to_actions(project: VnProject, plan: Dict[str, Any]) -> List[AgentAction]:
    actions: List[AgentAction] = []
    bible_raw = plan.get("bible") if isinstance(plan.get("bible"), dict) else {}
    bible_patch = _normalize_bible_patch(bible_raw or {})
    # drop empty strings
    bible_patch = {k: v for k, v in bible_patch.items() if str(v).strip()}
    if bible_patch:
        actions.append({"op": "update_bible", "patch": bible_patch})

    meta = plan.get("meta") if isinstance(plan.get("meta"), dict) else {}
    meta_action: Dict[str, Any] = {"op": "update_meta"}
    for key in ("title", "logline", "genre"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            meta_action[key] = val.strip()
    if len(meta_action) > 1:
        actions.append(meta_action)

    idx = _char_index(project)
    chars = plan.get("characters")
    if isinstance(chars, list):
        for item in chars:
            if not isinstance(item, dict):
                continue
            name = str(item.get("displayName") or item.get("name") or "").strip()
            if not name:
                continue
            existing = idx.get(name.lower())
            patch = {
                k: str(item[k]).strip()
                for k in ("voice", "bio", "relationships", "color", "displayName", "defineName")
                if item.get(k) is not None and str(item.get(k)).strip()
            }
            if existing:
                # don't rename unless explicitly different
                body = {k: v for k, v in patch.items() if k not in ("defineName",)}
                if body:
                    actions.append(
                        {"op": "update_character", "ref": existing.id, "patch": body}
                    )
            else:
                actions.append(
                    {
                        "op": "add_character",
                        "displayName": name,
                        "defineName": patch.get("defineName"),
                        "voice": patch.get("voice") or "",
                        "bio": patch.get("bio") or "",
                        "relationships": patch.get("relationships") or "",
                        "color": patch.get("color") or "#6b7280",
                    }
                )
    return actions


def _project_digest(project: VnProject) -> str:
    b = project.bible
    lines = [
        f"标题：{project.title}",
        f"类型：{project.genre or ''}",
        f"一句话：{project.logline or ''}",
        "角色："
        + "；".join(
            f"{c.displayName}({c.defineName}) voice={c.voice or ''} bio={c.bio or ''}"
            for c in project.characters[:20]
        ),
    ]
    if b:
        lines.append(f"world：{(b.world or '')[:400]}")
        lines.append(f"background：{(b.background or '')[:400]}")
        lines.append(f"outline：{(b.outline or '')[:400]}")
        lines.append(f"themes：{(b.themes or '')[:200]}")
        lines.append(f"notes：{(b.notes or '')[:200]}")
    return "\n".join(lines)


async def ingest_attachments_to_settings(
    config: DeepSeekConfig,
    project: VnProject,
    attachments: List[Dict[str, Any]],
    *,
    user_note: str = "",
) -> SettingsIngestResult:
    if not config.apiKey or "your-key" in config.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")
    docs = format_attachment_block(attachments)
    if not docs.strip():
        raise RuntimeError("没有可用的附件正文")

    user_content = (
        f"## 当前工程摘要\n{_project_digest(project)}\n\n"
        f"{docs}\n\n"
        f"## 用户说明\n{(user_note or '请把附件信息写入设定页与角色卡').strip()}"
    )

    res = await chat_completions(
        config,
        messages=[
            {"role": "system", "content": INGEST_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
        timeout=120,
    )
    raw, _model = content_from_response(res)
    raw = (raw or "{}").strip() or "{}"
    plan = _parse_json_obj(raw)
    actions = plan_to_actions(project, plan)
    if not actions:
        return SettingsIngestResult(
            message=str(plan.get("message") or "附件里没有足够可写入设定页的信息。"),
            actions=[],
        )

    applied = apply_agent_actions(project, actions)
    msg = str(plan.get("message") or "").strip() or "已根据附件更新设定。"
    if applied.applied:
        msg = f"{msg}\n\n已落地：{'；'.join(applied.applied)}"
    if applied.skipped:
        msg = f"{msg}\n未执行：{'；'.join(applied.skipped)}"
    return SettingsIngestResult(
        message=msg,
        actions=actions,
        project=applied.project,
        applied=list(applied.applied),
        skipped=list(applied.skipped),
    )
