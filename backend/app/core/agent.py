"""Ported from packages/core/src/agent.ts"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.domain.types import (
    AgentAction,
    AgentRequest,
    AgentResponse,
    Character,
    Location,
    SceneChapter,
    ScriptBlock,
    StoryBible,
    VnProject,
)

from .ai import DeepSeekConfig
from .project import _to_base36, new_location_link, uid

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
5. 纯讨论/大纲/点评/征求意见：actions=[]，把完整意见写进 message（可长文、分点）；禁止只回「已处理」或空 message。
6. 快捷任务若已要求写入，或用户明确说「写入/追加/应用/改到工程里…」，再用 actions。
7. 禁止擅自大删既有剧情；replace_script 仅在用户明确要求整章重写并写入时。
8. 若本轮有脚本 actions：message 至少用几句说明改了什么、为什么这样改；不要空 message。
9. 用户粘贴他人审稿/长文分析并问「对吗 / 怎么改 / 提意见」：先在 message 里表态与细化方案（可摘改写示例对白）；未明确要求写入正文前不要 replace_script/append_script。

输出（单一 JSON，无 markdown 围栏）：
{
  "message": "中文：讨论/审稿/大纲必须写满；正文要点可先展示",
  "actions": []
}

可用 op（字段名必须是 "op"，不要写成 action）：
add_character / update_character / delete_character /
add_location / update_location / delete_location /
add_location_link / delete_location_link /
add_chapter / delete_chapter / rename_chapter /
append_script { "op":"append_script", "chapterRef"?, "text" } /
replace_script { "op":"replace_script", "chapterRef"?, "text" } /
update_bible / update_meta /
propose_character_link { fromRef, toRef, label?, quote? } — 进分析待审托盘，不直接改图 /
propose_timeline_event { title, when?, summary?, chapterRef? } — 进待审托盘 /
add_character_link / update_character_link / delete_character_link — 仅当用户明确要求写入/应用/填上关系图 /
add_timeline_event / update_timeline_event / delete_timeline_event — 仅当用户明确要求写入时间线 /
scan_facts { chapterRef?, includePaste? } — 触发增量事实扫描（批量结果进待审，勿静默直写）

用户上传参考资料：
- 上下文可能含「用户上传参考资料」（人设表、大纲、摘录等）。可据此讨论、propose_*；用户明示「整理进项目/写入/填上/更新设定」时再用 CRUD / update_bible / add_character 等写入。
- **设定页（工作室 → 故事设定）**对应 `update_bible.patch` 字段：
  - world＝世界观/规则
  - background＝故事背景/前情
  - outline＝大纲/节拍
  - themes＝主题/基调/禁忌
  - notes＝其他备忘
  作品标题/一句话/类型用 `update_meta`（title/logline/genre）。
  角色卡用 add_character / update_character（voice/bio/relationships）。
- 用户说「根据附件写入/更新设定/整理进设定页」时：必须输出 update_bible（可多项字段合并进一个 patch），必要时叠加 update_meta / add_character / update_character；message 用中文说明改了哪些栏。合并写入：保留工程里已有且附件未覆盖的内容，附件新信息追加或改写对应栏，勿无故清空未提及字段。
- 从附件整理关系/时间线：优先 propose_* 或 scan_facts（includePaste=true）；禁止把附件原文整段塞进对白。

事实层边界：
- 角色关系图 / 时间线 = 可对账事实；语气讨论与审稿意见 = 观点层，禁止用 message 假装已写入事实。
- 默认 propose_* 或 scan_facts；只有用户明确说写入/应用/填上/确认时才用 add_*_link / add_timeline_event。
- 用户消息里的长粘贴设定可作临时源：scan_facts.includePaste=true 或 propose 时附 quote。

defineName：英文小写+数字下划线。地图通路仅表示联通（无需填写 relation）。"""


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


def _normalize_bible_patch(raw: Any) -> Dict[str, str]:
    """Accept English keys or common Chinese aliases from the model."""
    if not isinstance(raw, dict):
        return {}
    aliases = {
        "world": ("world", "世界", "世界观", "世界规则", "lore"),
        "background": ("background", "背景", "前情", "故事背景", "背景设定"),
        "outline": ("outline", "大纲", "节拍", "故事大纲", "剧情大纲"),
        "themes": ("themes", "主题", "基调", "禁忌", "主题基调"),
        "notes": ("notes", "备忘", "其他", "备注", "其他备忘"),
    }
    out: Dict[str, str] = {}
    lower_map = {str(k).strip().lower(): v for k, v in raw.items()}
    for canon, keys in aliases.items():
        for key in keys:
            hit = raw.get(key)
            if hit is None:
                hit = lower_map.get(key.lower())
            if hit is None:
                continue
            text = str(hit).strip()
            if text:
                out[canon] = text
                break
    return out


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

        if obj["op"] in ("update_bible", "update_story_bible", "set_bible"):
            obj["op"] = "update_bible"
            patch = _normalize_bible_patch(obj.get("patch") or obj.get("bible") or {})
            if not patch:
                patch = _normalize_bible_patch(obj)
            if patch:
                obj["patch"] = patch

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
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # 模型没吐 JSON（如忽略 response_format 返回纯文本，或返回空串）：
        # 把原文当回复，绝不把裸 JSONDecodeError 抛给用户。
        prose = text.strip()
        if not prose:
            return "模型返回了无法解析的内容（空响应），请重试。", []
        return prose[:2000], []
    actions = _normalize_agent_actions(parsed.get("actions"))
    message = parsed.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip(), actions
    # Empty message is a common model failure mode; never leave a dead "已处理。"
    if actions:
        ops = []
        for a in actions:
            op = a.get("op")
            if isinstance(op, str) and op and op not in ops:
                ops.append(op)
        op_bit = "、".join(ops[:6]) if ops else "若干操作"
        return (
            f"已生成工程改动（{op_bit}），但模型未附文字说明。"
            f"若你要的是审稿/修改意见，请再说一次「只要意见、先不要写入」；"
            f"若要说明改了什么，直接问「刚才改了哪些」。",
            actions,
        )
    return (
        "我这一轮没产出可用的文字说明。请换个问法再试："
        "例如「先不要改工程，只根据上文给第一章修改意见」。",
        actions,
    )


async def run_agent(
    config: DeepSeekConfig,
    request: AgentRequest,
    *,
    on_event=None,
    on_checkpoint=None,
    resume=None,
) -> AgentResponse:
    """Editor agent entry — multi-step tool loop with trajectory."""
    from app.core.agent_loop import run_agent_loop

    return await run_agent_loop(
        config, request, on_event=on_event, on_checkpoint=on_checkpoint, resume=resume
    )


@dataclass
class ApplyAgentResult:
    project: VnProject
    applied: List[str]
    skipped: List[str]
    inbox_proposals: List[Dict[str, Any]] = field(default_factory=list)
    scan_request: Optional[Dict[str, Any]] = None


def apply_agent_actions(
    project: VnProject,
    actions: List[AgentAction],
    defaultChapterId: Optional[str] = None,
) -> ApplyAgentResult:
    """Apply agent actions immutably to a project."""
    from app.core.fact_extract import (
        accept_character_link,
        accept_timeline_event,
        link_dedupe_key,
        should_weak_sync_label,
        timeline_dedupe_key,
        weak_sync_relationships,
    )

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
    inbox_proposals: List[Dict[str, Any]] = []
    scan_request: Optional[Dict[str, Any]] = None

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
                raw_patch = action.get("patch") or action.get("bible") or action
                patch = _normalize_bible_patch(raw_patch)
                # Also allow top-level fields on the action itself
                if not patch:
                    patch = _normalize_bible_patch(action)
                if not patch:
                    skipped.append("update_bible 缺少可识别的设定字段（world/background/outline/themes/notes）")
                    continue
                current_bible = next_project.bible.model_dump() if next_project.bible else {}
                next_project.bible = StoryBible.model_validate({**current_bible, **patch})
                if "world" in patch:
                    next_project.lore = patch["world"]
                applied.append("更新故事设定：" + "、".join(patch.keys()))
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

            if op == "propose_character_link":
                from_ref = action.get("fromRef") or action.get("fromId") or ""
                to_ref = action.get("toRef") or action.get("toId") or ""
                a = _find_character(next_project, str(from_ref))
                b = _find_character(next_project, str(to_ref))
                if not a or not b:
                    skipped.append(f"提议关系失败: {from_ref} → {to_ref}")
                    continue
                label = str(action.get("label") or "关系")
                quote = action.get("quote")
                evidence = [
                    {
                        "source": "agent",
                        "quote": str(quote)[:200] if quote else None,
                    }
                ]
                inbox_proposals.append(
                    {
                        "kind": "character_link",
                        "payload": {
                            "fromId": a.id,
                            "toId": b.id,
                            "label": label,
                        },
                        "evidence": evidence,
                        "dedupe_key": link_dedupe_key(a.id, b.id, label),
                    }
                )
                applied.append(f"提议关系 {a.displayName}—{label}→{b.displayName}")
                continue

            if op == "propose_timeline_event":
                title = str(action.get("title") or "").strip()
                if not title:
                    skipped.append("propose_timeline_event 缺少 title")
                    continue
                chapter_ref = action.get("chapterRef")
                if chapter_ref:
                    ch = _find_chapter(next_project, str(chapter_ref))
                    chapter_ref = ch.id if ch else chapter_ref
                payload = {
                    "title": title,
                    "when": action.get("when"),
                    "summary": action.get("summary"),
                    "chapterRef": chapter_ref,
                    "order": action.get("order"),
                }
                inbox_proposals.append(
                    {
                        "kind": "timeline_event",
                        "payload": payload,
                        "evidence": [{"source": "agent", "quote": title}],
                        "dedupe_key": timeline_dedupe_key(title, chapter_ref),
                    }
                )
                applied.append(f"提议时间线「{title}」")
                continue

            if op == "add_character_link":
                from_ref = action.get("fromRef") or action.get("fromId") or ""
                to_ref = action.get("toRef") or action.get("toId") or ""
                a = _find_character(next_project, str(from_ref))
                b = _find_character(next_project, str(to_ref))
                if not a or not b:
                    skipped.append(f"添加关系失败: {from_ref} → {to_ref}")
                    continue
                label = str(action.get("label") or "关系")
                before = len(next_project.characterLinks or [])
                next_project = accept_character_link(
                    next_project,
                    from_id=a.id,
                    to_id=b.id,
                    label=label,
                    evidence=[{"source": "agent"}],
                    sync_cards=True,
                )
                if len(next_project.characterLinks or []) == before:
                    skipped.append(f"关系已存在: {label}")
                else:
                    applied.append(f"写入关系 {a.displayName}—{label}→{b.displayName}")
                continue

            if op == "update_character_link":
                link_id = action.get("id") or action.get("ref")
                label = action.get("label")
                links = list(next_project.characterLinks or [])
                hit = next((l for l in links if l.id == link_id), None)
                if not hit and action.get("fromRef") and action.get("toRef"):
                    a = _find_character(next_project, str(action.get("fromRef")))
                    b = _find_character(next_project, str(action.get("toRef")))
                    if a and b:
                        hit = next(
                            (
                                l
                                for l in links
                                if l.fromId == a.id and l.toId == b.id
                            ),
                            None,
                        )
                if not hit:
                    skipped.append("未找到角色关系边")
                    continue
                patch: Dict[str, Any] = {}
                if label:
                    patch["label"] = label
                next_project.characterLinks = [
                    l.model_copy(update=patch) if l.id == hit.id else l for l in links
                ]
                if label and should_weak_sync_label(str(label)):
                    next_project = weak_sync_relationships(
                        next_project, hit.fromId, hit.toId, str(label)
                    )
                applied.append("更新角色关系")
                continue

            if op == "delete_character_link":
                link_id = action.get("id") or action.get("ref")
                links = list(next_project.characterLinks or [])
                if link_id:
                    next_project.characterLinks = [
                        l for l in links if l.id != link_id
                    ]
                else:
                    a = _find_character(
                        next_project, str(action.get("fromRef") or "")
                    )
                    b = _find_character(
                        next_project, str(action.get("toRef") or "")
                    )
                    if not a or not b:
                        skipped.append("未找到要删除的关系")
                        continue
                    next_project.characterLinks = [
                        l
                        for l in links
                        if not (l.fromId == a.id and l.toId == b.id)
                    ]
                applied.append("删除角色关系")
                continue

            if op == "add_timeline_event":
                title = str(action.get("title") or "").strip()
                if not title:
                    skipped.append("add_timeline_event 缺少 title")
                    continue
                chapter_ref = action.get("chapterRef")
                if chapter_ref:
                    ch = _find_chapter(next_project, str(chapter_ref))
                    chapter_ref = ch.id if ch else chapter_ref
                before = len(next_project.timeline or [])
                next_project = accept_timeline_event(
                    next_project,
                    title=title,
                    when=action.get("when"),
                    summary=action.get("summary"),
                    chapter_ref=chapter_ref,
                    order=action.get("order"),
                    evidence=[{"source": "agent"}],
                )
                if len(next_project.timeline or []) == before:
                    skipped.append(f"时间线已存在: {title}")
                else:
                    applied.append(f"写入时间线「{title}」")
                continue

            if op == "update_timeline_event":
                ref = action.get("id") or action.get("ref")
                events = list(next_project.timeline or [])
                hit = next((e for e in events if e.id == ref or e.title == ref), None)
                if not hit:
                    skipped.append("未找到时间线节点")
                    continue
                patch = {
                    k: action[k]
                    for k in ("title", "when", "summary", "chapterRef", "order")
                    if k in action and action[k] is not None
                }
                next_project.timeline = [
                    e.model_copy(update=patch) if e.id == hit.id else e for e in events
                ]
                applied.append("更新时间线节点")
                continue

            if op == "delete_timeline_event":
                ref = action.get("id") or action.get("ref") or action.get("title")
                events = list(next_project.timeline or [])
                next_project.timeline = [
                    e for e in events if e.id != ref and e.title != ref
                ]
                if len(next_project.timeline) == len(events):
                    skipped.append("未找到要删除的时间线节点")
                else:
                    applied.append("删除时间线节点")
                continue

            if op == "scan_facts":
                scan_request = {
                    "chapterRef": action.get("chapterRef"),
                    "includePaste": bool(action.get("includePaste")),
                }
                applied.append("请求扫描事实")
                continue

            skipped.append(f"未知动作: {op if op else '?'}")
        except Exception as err:  # noqa: BLE001 - mirror TS catch-all
            op_str = str(action.get("op") or "?")
            detail = str(err)
            skipped.append(f"{op_str} 执行失败: {detail[:120]}")

    next_project.updatedAt = datetime.now(timezone.utc).isoformat()
    return ApplyAgentResult(
        project=next_project,
        applied=applied,
        skipped=skipped,
        inbox_proposals=inbox_proposals,
        scan_request=scan_request,
    )
