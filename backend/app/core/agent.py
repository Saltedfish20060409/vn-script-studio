"""Ported from packages/core/src/agent.ts"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.domain.types import (
    AgentAction,
    AgentContextMeta,
    AgentRequest,
    AgentResponse,
    Character,
    Location,
    ScriptBlock,
    SceneChapter,
    StoryBible,
    VnProject,
)

from .agent_context import build_agent_context, infer_agent_task, is_agent_task, task_hint
from .ai import DeepSeekConfig
from .narrative_lint import lint_has_blockers, lint_narrative_draft
from .narrative_review import (
    apply_reviewed_script,
    chapter_tail_plain,
    extract_script_from_actions,
    run_narrative_self_review,
    should_self_review,
)
from .project import _to_base36, new_location_link, uid
from .writing_craft import build_writing_craft_prompt, select_craft_mode

AGENT_SYSTEM = """你是「VN Script Studio」的驻场轻小说 / 视觉小说责编（Editor Agent）。

你不是通用聊天框：你服务于**这一部作品**的专业化写作任务（续写、改写、润色、分支、大纲、语气审校、一致性排查、写一场戏）。

身份：
- 轻小说责编 + VN 脚本顾问：把故事写好是第一位；增删角色/地点/章节是创作手段。
- 上下文由工作室检索拼装（当前章优先、相关设定/角色/地点/变量、他章摘要），不是全库倾倒——缺材料时主动问用户或请其切换章节。

关键（务必遵守）：
- 作品档案里的人设 / bible / 变量 = **内部参考**，用来指导「怎么演」，禁止整段搬进对白或旁白当说明书。
- 续写/写戏时：叙事逻辑与节奏 > 展示设定完整度。受众要沉浸，不要设定展柜。
- 若工艺 Skills 与「写全上下文」冲突，以工艺 Skills 为准。

创作原则：
1. 先对齐任务模式、章末节拍与人设语气，再给方案或可上演正文。
2. 正文优先 Ren'Py 可粘贴风格：旁白 "..."、对白 name "..."、必要时 scene/show/menu/jump/label。
3. 审稿要具体到句子：口气崩、信息倾倒、假选择、地点氛围不一致，并给改法。
4. 尊重 Variables（好感/flag）与 Sprites 表情槽；需要时可在对白旁注释 show 标签。
5. 纯讨论/大纲/点评：actions=[]，精华放 message。
6. 快捷任务若已要求写入，或用户说「写入/追加/应用/创建…」，再用 actions。
7. 禁止擅自大删既有剧情；replace_script 仅在用户明确要求整章重写时。
8. message 里可先用一两句说明本段「接了什么节拍、故意没写哪些设定」；正文仍走 actions。

输出（单一 JSON，无 markdown 围栏）：
{
  "message": "中文：讨论/审稿/大纲；正文要点可先展示",
  "actions": []
}

可用 op（字段名必须是 "op"，不要写成 action）：
add_character / update_character / delete_character /
add_location / update_location / delete_location /
add_location_link / delete_location_link /
add_chapter / delete_chapter / rename_chapter /
append_script { "op":"append_script", "chapterRef"?, "text" } /
replace_script { "op":"replace_script", "chapterRef"?, "text" } /
update_bible / update_meta

defineName：英文小写+数字下划线。relation：adjacent|contains|inside|above|below|leads_to|visible_from|other。"""


def _slug_define(name: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", name)
    ascii_ = re.sub(r"[^\w]+", "_", ascii_, flags=re.ASCII)
    ascii_ = re.sub(r"^_+|_+$", "", ascii_)
    ascii_ = ascii_.lower()
    if ascii_ and re.match(r"^[a-z]", ascii_):
        return ascii_[:32]
    return f"char_{_to_base36(int(time.time() * 1000))}"


def _find_character(project: VnProject, ref: str) -> Optional[Character]:
    r = ref.strip().lower()
    return next(
        (
            c
            for c in project.characters
            if c.id.lower() == r or c.defineName.lower() == r or c.displayName.lower() == r
        ),
        None,
    )


def _find_location(project: VnProject, ref: str) -> Optional[Location]:
    r = ref.strip().lower()
    return next(
        (
            l
            for l in (project.locations or [])
            if l.id.lower() == r or l.name.lower() == r or (l.imageTag and l.imageTag.lower() == r)
        ),
        None,
    )


def _find_chapter(project: VnProject, ref: Optional[str] = None) -> Optional[SceneChapter]:
    if not ref:
        return project.chapters[0] if project.chapters else None
    r = ref.strip().lower()
    found = next(
        (c for c in project.chapters if c.id.lower() == r or c.title.lower() == r), None
    )
    return found if found is not None else (project.chapters[0] if project.chapters else None)


def _text_to_blocks(text: str) -> List[ScriptBlock]:
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: List[ScriptBlock] = []
    for line in lines:
        t = line.rstrip()
        if not t.strip():
            continue
        blocks.append({"type": "raw", "code": t})
    return blocks


def _coerce_script_text(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(
            line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)
            for line in value
        )
    if isinstance(value, dict):
        for key in ("text", "content", "script", "body", "code"):
            inner = _coerce_script_text(value.get(key))
            if inner is not None:
                return inner
    return None


def _nvl(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


def _normalize_agent_actions(raw: Any) -> List[AgentAction]:
    if not isinstance(raw, list):
        return []
    out: List[AgentAction] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        obj: Dict[str, Any] = dict(item)
        # Models drift: action / type / name / operation instead of op
        if not isinstance(obj.get("op"), str):
            for key in ("action", "type", "name", "operation", "command"):
                if isinstance(obj.get(key), str):
                    obj["op"] = obj[key]
                    break
        for key in ("action", "type", "operation", "command"):
            obj.pop(key, None)
        if not isinstance(obj.get("op"), str):
            continue
        obj["op"] = str(obj["op"]).strip()

        if obj["op"] in ("append_script", "replace_script"):
            text = _coerce_script_text(
                _nvl(obj.get("text"), obj.get("content"), obj.get("script"), obj.get("body"), obj.get("code"))
            )
            if text is not None:
                obj["text"] = text
            # chapter title sometimes sent as chapter / chapterId / chapter_name
            if obj.get("chapterRef") is None:
                ref = _nvl(
                    obj.get("chapter"),
                    obj.get("chapterId"),
                    obj.get("chapter_name"),
                    obj.get("chapterTitle"),
                )
                if isinstance(ref, str):
                    obj["chapterRef"] = ref

        out.append(obj)
    return out


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def _parse_agent_json(raw: str) -> Tuple[str, List[AgentAction]]:
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    parsed = json.loads(text)
    message = parsed.get("message")
    message = message.strip() if isinstance(message, str) and message.strip() else "已处理。"
    return message, _normalize_agent_actions(parsed.get("actions"))


async def run_agent(config: DeepSeekConfig, request: AgentRequest) -> AgentResponse:
    if not config.apiKey or "your-key" in config.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")
    base_url = (config.baseUrl or "https://api.deepseek.com").rstrip("/")
    model = config.model or "deepseek-chat"

    last_user = next(
        (m.content for m in reversed(request.messages) if m.role == "user"), None
    )

    task = request.task if is_agent_task(request.task) else infer_agent_task(last_user or "")

    craft = select_craft_mode(
        task=task,
        user_message=last_user,
        project=request.project,
        chapter_id=request.chapterId,
        preference=request.craftMode,
    )

    ctx = build_agent_context(
        request.project,
        chapterId=request.chapterId,
        selection=request.selection,
        userMessage=last_user,
        task=task,
        maxChars=12000,
        chatMemory=request.chatMemory,
    )

    history = [
        {"role": m.role, "content": m.content} for m in request.messages[-20:]
    ] if request.messages else []

    if craft.mode == "off":
        temperature = 0.82
    elif task in ("polish", "voice", "consistency"):
        temperature = 0.55
    elif task == "outline":
        temperature = 0.7
    elif craft.mode == "lite":
        temperature = 0.72
    else:
        temperature = 0.78

    craft_block = build_writing_craft_prompt(task, craft.mode)

    async with httpx.AsyncClient(timeout=180) as client:
        res = await client.post(
            f"{base_url}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.apiKey}",
            },
            json={
                "model": model,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"{AGENT_SYSTEM}\n\n{task_hint(task)}\n\n{craft_block}\n\n"
                            f"—— 作品上下文（检索拼装；人设/设定为内部参考）——\n{ctx.text}"
                        ),
                    },
                    *history,
                ],
            },
        )

    if res.status_code >= 400:
        err_text = res.text
        raise RuntimeError(f"DeepSeek API {res.status_code}: {err_text[:400]}")

    data = res.json()
    choices = data.get("choices") or []
    content = "{}"
    if choices:
        content = ((choices[0] or {}).get("message") or {}).get("content", "{}") or "{}"
        content = content.strip() or "{}"
    message, actions = _parse_agent_json(content)

    review_note = ""
    review_pref = request.selfReview or "auto"
    if should_self_review(task, review_pref):
        script_hit = extract_script_from_actions(actions)
        if script_hit.op and script_hit.text:
            lint_issues = lint_narrative_draft(script_hit.text)
            critic_config = DeepSeekConfig(
                apiKey=request.criticApiKey or config.apiKey,
                baseUrl=request.criticApiBaseUrl or config.baseUrl,
                model=request.criticApiModel or config.model,
            )
            review = await run_narrative_self_review(
                critic_config,
                draft=script_hit.text,
                task=task,
                project=request.project,
                chapterTail=chapter_tail_plain(request.project, request.chapterId),
                lintIssues=lint_issues,
            )
            review_note = review.note
            if not review.ok and review.revisedText:
                actions = apply_reviewed_script(actions, script_hit.index, review.revisedText)
                if review.issues:
                    message = f"{message}\n\n（自检修订：{'；'.join(review.issues[:3])}）"
            elif lint_has_blockers(lint_issues) and not review.revisedText:
                error_msgs = [i.message for i in lint_issues if i.severity == "error"][:2]
                review_note = review_note or f"规则未过：{'；'.join(error_msgs)}"

    return AgentResponse(
        message=message,
        actions=actions,
        model=data.get("model") or model,
        contextMeta=AgentContextMeta(
            task=ctx.task,
            charsUsed=ctx.charsUsed,
            craftMode=craft.mode,
            craftReason=craft.reason,
            included=ctx.included,
            selfReview=review_note or None,
        ),
    )


@dataclass
class ApplyAgentResult:
    project: VnProject
    applied: List[str]
    skipped: List[str]


def apply_agent_actions(
    project: VnProject,
    actions: List[AgentAction],
    defaultChapterId: Optional[str] = None,
) -> ApplyAgentResult:
    """Apply agent actions immutably to a project."""
    next_project = project.model_copy(deep=True)
    if next_project.locations is None:
        next_project.locations = []
    if next_project.locationLinks is None:
        next_project.locationLinks = []
    if next_project.characterLinks is None:
        next_project.characterLinks = []
    if next_project.timeline is None:
        next_project.timeline = []
    if next_project.bible is None:
        next_project.bible = StoryBible()

    applied: List[str] = []
    skipped: List[str] = []

    for action in actions:
        op = action.get("op")
        try:
            if op == "add_character":
                display_name = action.get("displayName")
                if not display_name or not str(display_name).strip():
                    skipped.append("add_character 缺少 displayName")
                    continue
                raw_define = action.get("defineName")
                define_name = (
                    re.sub(r"[^A-Za-z0-9_]", "", raw_define) if raw_define else ""
                ) or _slug_define(display_name)
                char_id = define_name
                if any(
                    c.id == char_id or c.defineName == define_name
                    for c in next_project.characters
                ):
                    skipped.append(f"角色已存在: {display_name}")
                    continue
                next_project.characters.append(
                    Character(
                        id=char_id,
                        defineName=define_name,
                        displayName=display_name,
                        color=action.get("color") or "#6b7280",
                        voice=action.get("voice") or "",
                        bio=action.get("bio") or "",
                        relationships=action.get("relationships") or "",
                    )
                )
                applied.append(f"添加角色 {display_name}")
                continue

            if op == "update_character":
                ref = action.get("ref") or ""
                ch = _find_character(next_project, ref)
                if not ch:
                    skipped.append(f"未找到角色: {ref}")
                    continue
                patch = action.get("patch") or {}
                next_project.characters = [
                    c.model_copy(update=patch) if c.id == ch.id else c
                    for c in next_project.characters
                ]
                applied.append(f"更新角色 {ch.displayName}")
                continue

            if op == "delete_character":
                ref = action.get("ref") or ""
                ch = _find_character(next_project, ref)
                if not ch:
                    skipped.append(f"未找到角色: {ref}")
                    continue
                next_project.characters = [
                    c for c in next_project.characters if c.id != ch.id
                ]
                next_project.characterLinks = [
                    l
                    for l in (next_project.characterLinks or [])
                    if l.fromId != ch.id and l.toId != ch.id
                ]
                applied.append(f"删除角色 {ch.displayName}")
                continue

            if op == "add_location":
                loc_id = uid("loc")
                n = len(next_project.locations or []) + 1
                map_x = action.get("mapX")
                map_y = action.get("mapY")
                new_loc = Location(
                    id=loc_id,
                    name=action.get("name"),
                    imageTag=action.get("imageTag"),
                    description=action.get("description"),
                    tags=action.get("tags"),
                    mapX=map_x if map_x is not None else 200 + (n % 6) * 220,
                    mapY=map_y if map_y is not None else 180 + (n // 6) * 180,
                )
                next_project.locations = [*(next_project.locations or []), new_loc]
                applied.append(f"添加地点 {action.get('name')}")
                continue

            if op == "update_location":
                ref = action.get("ref") or ""
                loc = _find_location(next_project, ref)
                if not loc:
                    skipped.append(f"未找到地点: {ref}")
                    continue
                patch = action.get("patch") or {}
                next_project.locations = [
                    l.model_copy(update=patch) if l.id == loc.id else l
                    for l in (next_project.locations or [])
                ]
                applied.append(f"更新地点 {loc.name}")
                continue

            if op == "delete_location":
                ref = action.get("ref") or ""
                loc = _find_location(next_project, ref)
                if not loc:
                    skipped.append(f"未找到地点: {ref}")
                    continue
                next_project.locations = [
                    l for l in (next_project.locations or []) if l.id != loc.id
                ]
                next_project.locationLinks = [
                    l
                    for l in (next_project.locationLinks or [])
                    if l.fromId != loc.id and l.toId != loc.id
                ]
                applied.append(f"删除地点 {loc.name}")
                continue

            if op == "add_location_link":
                from_ref = action.get("fromRef") or ""
                to_ref = action.get("toRef") or ""
                from_loc = _find_location(next_project, from_ref)
                to_loc = _find_location(next_project, to_ref)
                if not from_loc or not to_loc:
                    skipped.append(f"连线失败: {from_ref} → {to_ref}")
                    continue
                relation = action.get("relation") or "leads_to"
                link = new_location_link(from_loc.id, to_loc.id, relation)
                link = link.model_copy(update={"note": action.get("note")})
                next_project.locationLinks = [*(next_project.locationLinks or []), link]
                applied.append(f"地图通路 {from_loc.name}→{to_loc.name}")
                continue

            if op == "delete_location_link":
                from_ref = action.get("fromRef") or ""
                to_ref = action.get("toRef") or ""
                from_loc = _find_location(next_project, from_ref)
                to_loc = _find_location(next_project, to_ref)
                if not from_loc or not to_loc:
                    skipped.append("未找到连线")
                    continue
                next_project.locationLinks = [
                    l
                    for l in (next_project.locationLinks or [])
                    if not (l.fromId == from_loc.id and l.toId == to_loc.id)
                ]
                applied.append(f"删除通路 {from_loc.name}→{to_loc.name}")
                continue

            if op == "add_chapter":
                new_id = uid("ch")
                next_project.chapters = [
                    *next_project.chapters,
                    SceneChapter(
                        id=new_id,
                        title=action.get("title"),
                        synopsis=action.get("synopsis"),
                        blocks=[{"type": "label", "id": "start", "name": "start"}],
                    ),
                ]
                applied.append(f"添加章节 {action.get('title')}")
                continue

            if op == "delete_chapter":
                if len(next_project.chapters) <= 1:
                    skipped.append("至少保留一章")
                    continue
                ref = action.get("ref")
                ch = _find_chapter(next_project, ref)
                if not ch:
                    skipped.append(f"未找到章节: {ref}")
                    continue
                next_project.chapters = [
                    c for c in next_project.chapters if c.id != ch.id
                ]
                applied.append(f"删除章节 {ch.title}")
                continue

            if op == "rename_chapter":
                ref = action.get("ref")
                ch = _find_chapter(next_project, ref)
                if not ch:
                    skipped.append(f"未找到章节: {ref}")
                    continue
                title = action.get("title")
                next_project.chapters = [
                    c.model_copy(update={"title": title}) if c.id == ch.id else c
                    for c in next_project.chapters
                ]
                applied.append(f"重命名章节为 {title}")
                continue

            if op == "append_script":
                chapter_ref = _nvl(action.get("chapterRef"), defaultChapterId)
                ch = _find_chapter(next_project, chapter_ref)
                if not ch:
                    skipped.append("无章节可写入")
                    continue
                text = _coerce_script_text(action.get("text"))
                if text is None or not str(text).strip():
                    skipped.append("append_script 缺少正文 text（模型未返回可写入内容）")
                    continue
                blocks = _text_to_blocks(str(text))
                if not blocks:
                    skipped.append("append_script 正文为空")
                    continue
                next_project.chapters = [
                    c.model_copy(update={"blocks": [*c.blocks, *blocks]})
                    if c.id == ch.id
                    else c
                    for c in next_project.chapters
                ]
                applied.append(f"向「{ch.title}」写入剧情")
                continue

            if op == "replace_script":
                chapter_ref = _nvl(action.get("chapterRef"), defaultChapterId)
                ch = _find_chapter(next_project, chapter_ref)
                if not ch:
                    skipped.append("无章节可写入")
                    continue
                text = _coerce_script_text(action.get("text"))
                if text is None:
                    skipped.append("replace_script 缺少正文 text")
                    continue
                blocks = _text_to_blocks(str(text))
                next_project.chapters = [
                    c.model_copy(
                        update={
                            "blocks": blocks
                            if blocks
                            else [{"type": "label", "id": "start", "name": "start"}]
                        }
                    )
                    if c.id == ch.id
                    else c
                    for c in next_project.chapters
                ]
                applied.append(f"重写「{ch.title}」")
                continue

            if op == "update_bible":
                patch = action.get("patch") or {}
                current_bible = next_project.bible.model_dump() if next_project.bible else {}
                next_project.bible = StoryBible.model_validate({**current_bible, **patch})
                if "world" in patch:
                    next_project.lore = patch["world"]
                applied.append("更新故事设定")
                continue

            if op == "update_meta":
                if "title" in action:
                    next_project.title = action["title"]
                if "logline" in action:
                    next_project.logline = action["logline"]
                if "genre" in action:
                    next_project.genre = action["genre"]
                applied.append("更新作品信息")
                continue

            skipped.append(f"未知动作: {op if op else '?'}")
        except Exception as err:  # noqa: BLE001 - mirror TS catch-all
            op_str = str(action.get("op") or "?")
            detail = str(err)
            skipped.append(f"{op_str} 执行失败: {detail[:120]}")

    next_project.updatedAt = datetime.now(timezone.utc).isoformat()
    return ApplyAgentResult(project=next_project, applied=applied, skipped=skipped)
