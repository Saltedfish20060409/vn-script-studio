"""写作导师包：加载、裁剪与注入拼装。

设计见 ``backend/vendor/MENTOR_PACK_DESIGN.md``。
导师包（L2）不得推翻 ``style_guide``（L0）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

PACKS_DIR = Path(__file__).resolve().parent / "packs"
TEMPLATE_PATH = Path(__file__).resolve().parent / "template.md"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

# 注入时优先保留的节（按重要度）
_PRIORITY_SECTIONS = (
    "人格一句话",
    "反模式",
    "阶段检查清单",
    "心智模型",
    "决策启发式",
    "表达 DNA",
    "诚实边界",
)


@dataclass
class MentorPack:
    id: str
    name: str
    version: str = "1.0"
    kind: str = "writing_mentor"
    media: List[str] = field(default_factory=lambda: ["light_novel", "visual_novel"])
    locale: str = "zh-Hans"
    tags: List[str] = field(default_factory=list)
    stages: List[str] = field(default_factory=lambda: ["plan", "write", "check"])
    budget_chars: int = 2800
    provenance: str = "handcrafted"
    body: str = ""
    sections: Dict[str, str] = field(default_factory=dict)
    raw: str = ""
    source: str = "builtin"  # builtin | custom

    def meta(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "kind": self.kind,
            "media": list(self.media),
            "locale": self.locale,
            "tags": list(self.tags),
            "stages": list(self.stages),
            "budget_chars": self.budget_chars,
            "provenance": self.provenance,
            "source": self.source,
        }


def _parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return ""
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [p.strip().strip("\"'") for p in inner.split(",") if p.strip()]
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    return s


def _parse_frontmatter(block: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        data[key.strip()] = _parse_scalar(val)
    return data


def _split_sections(body: str) -> Dict[str, str]:
    matches = list(_SECTION_RE.finditer(body))
    if not matches:
        return {"_full": body.strip()}
    out: Dict[str, str] = {}
    # 标题前的引言忽略或并入 _preface
    if matches[0].start() > 0:
        pref = body[: matches[0].start()].strip()
        if pref:
            out["_preface"] = pref
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out[title] = body[start:end].strip()
    return out


def parse_mentor_markdown(
    markdown: str,
    *,
    fallback_id: str = "custom",
    source: str = "custom",
) -> MentorPack:
    raw = markdown or ""
    meta: Dict[str, Any] = {}
    body = raw
    m = _FRONTMATTER_RE.match(raw.strip())
    if m:
        meta = _parse_frontmatter(m.group(1))
        body = m.group(2).strip()
    sections = _split_sections(body)
    pack_id = str(meta.get("id") or fallback_id).strip() or fallback_id
    name = str(meta.get("name") or pack_id).strip()
    media = meta.get("media")
    if not isinstance(media, list):
        media = ["light_novel", "visual_novel"]
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    stages = meta.get("stages") if isinstance(meta.get("stages"), list) else ["plan", "write", "check"]
    budget = meta.get("budget_chars")
    if not isinstance(budget, int) or budget <= 0:
        budget = 2800
    return MentorPack(
        id=pack_id,
        name=name,
        version=str(meta.get("version") or "1.0"),
        kind=str(meta.get("kind") or "writing_mentor"),
        media=[str(x) for x in media],
        locale=str(meta.get("locale") or "zh-Hans"),
        tags=[str(x) for x in tags],
        stages=[str(x) for x in stages],
        budget_chars=budget,
        provenance=str(meta.get("provenance") or "unknown"),
        body=body,
        sections=sections,
        raw=raw,
        source=source,
    )


def _clip(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if max_chars <= 0 or len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def _stage_checklist_slice(checklist: str, stage: Optional[str]) -> str:
    if not checklist or not stage:
        return checklist
    stage_title = stage.strip().capitalize()
    # Plan / Write / Check 子节
    pattern = re.compile(
        rf"(###\s*{re.escape(stage_title)}\s*\n)(.*?)(?=\n###\s|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(checklist)
    if not m:
        return checklist
    return f"### {stage_title}\n{m.group(2).strip()}"


def pack_prompt_block(
    pack: MentorPack,
    *,
    stage: Optional[str] = None,
    max_chars: Optional[int] = None,
) -> str:
    """单包注入块。"""
    budget = max_chars if max_chars is not None else pack.budget_chars
    parts: List[str] = [
        f"## 写作导师：{pack.name}",
        f"（id=`{pack.id}`；方法论参考，不得推翻项目 style_guide 硬门禁。）",
    ]
    used = "\n".join(parts)
    for title in _PRIORITY_SECTIONS:
        content = pack.sections.get(title)
        if not content:
            continue
        if title == "阶段检查清单":
            content = _stage_checklist_slice(content, stage)
        chunk = f"### {title}\n{content}"
        if len(used) + 2 + len(chunk) > budget:
            remain = budget - len(used) - 2
            if remain < 80:
                break
            chunk = _clip(chunk, remain)
            parts.append(chunk)
            break
        parts.append(chunk)
        used = "\n\n".join(parts)
    return _clip("\n\n".join(parts), budget)


def mentors_prompt_block(
    packs: Sequence[MentorPack],
    *,
    stage: Optional[str] = None,
    total_budget: int = 4500,
) -> str:
    """多包合并；合计字符上限。"""
    if not packs:
        return ""
    n = len(packs)
    per = max(600, total_budget // n)
    blocks = [
        pack_prompt_block(p, stage=stage, max_chars=min(p.budget_chars, per)) for p in packs
    ]
    return _clip("\n\n".join(b for b in blocks if b.strip()), total_budget)


@lru_cache(maxsize=1)
def load_builtin_packs() -> Dict[str, MentorPack]:
    out: Dict[str, MentorPack] = {}
    if not PACKS_DIR.is_dir():
        return out
    for path in sorted(PACKS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8-sig")
        pack = parse_mentor_markdown(text, fallback_id=path.stem, source="builtin")
        if pack.id.startswith("_"):
            continue
        out[pack.id] = pack
    return out


def reload_builtin_packs() -> Dict[str, MentorPack]:
    load_builtin_packs.cache_clear()
    return load_builtin_packs()


def list_builtin_meta() -> List[Dict[str, Any]]:
    return [p.meta() for p in load_builtin_packs().values()]


def get_builtin(pack_id: str) -> Optional[MentorPack]:
    return load_builtin_packs().get(pack_id)


def resolve_packs(
    ids: Iterable[str],
    *,
    custom: Optional[Sequence[Dict[str, Any]]] = None,
    max_active: int = 1,
) -> List[MentorPack]:
    """按 id 解析内置 + 工程自定义包；默认只启用 1 个（完整写作导师）。"""
    custom_map: Dict[str, MentorPack] = {}
    for row in custom or []:
        md = (row.get("markdown") or "").strip()
        if not md:
            continue
        cid = str(row.get("id") or "custom").strip()
        custom_map[cid] = parse_mentor_markdown(md, fallback_id=cid, source="custom")
        if row.get("name"):
            custom_map[cid].name = str(row["name"])

    builtins = load_builtin_packs()
    resolved: List[MentorPack] = []
    seen = set()
    for raw_id in ids:
        pid = (raw_id or "").strip()
        # legacy ids already normalized by callers; still map here
        if pid in ("ln-vn-stagecraft", "ln-hook-and-heat"):
            pid = "ln-vn-editor"
        if not pid or pid in seen:
            continue
        pack = custom_map.get(pid) or builtins.get(pid)
        if not pack:
            continue
        resolved.append(pack)
        seen.add(pid)
        if len(resolved) >= max_active:
            break
    return resolved


def default_active_ids() -> List[str]:
    """无工程配置时的默认：统一写作导师（不切换角色）。"""
    packs = load_builtin_packs()
    if "ln-vn-editor" in packs:
        return ["ln-vn-editor"]
    # 兼容旧工程曾选用的包 id → 映射到统一导师
    if packs:
        return [next(iter(packs.keys()))]
    return ["ln-vn-editor"]


_TASK_TO_STAGE = {
    "outline": "plan",
    "chat": "plan",
    "continue": "write",
    "scene": "write",
    "rewrite": "write",
    "branch": "write",
    "polish": "check",
    "voice": "check",
    "consistency": "check",
}


def stage_for_agent_task(task: Optional[str]) -> str:
    return _TASK_TO_STAGE.get((task or "").strip(), "write")


def _project_mentor_state(project: Any) -> Dict[str, Any]:
    raw = getattr(project, "writingMentors", None)
    if raw is None and isinstance(project, dict):
        raw = project.get("writingMentors")
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump(mode="json")
    return raw if isinstance(raw, dict) else {}


_LEGACY_PACK_IDS = {
    "ln-vn-stagecraft": "ln-vn-editor",
    "ln-hook-and-heat": "ln-vn-editor",
}


def _normalize_pack_id(pid: str) -> str:
    p = (pid or "").strip()
    return _LEGACY_PACK_IDS.get(p, p)


def active_ids_for_project(
    project: Any,
    *,
    override_ids: Optional[Sequence[str]] = None,
) -> List[str]:
    # 产品默认：一个完整写作导师；override 仍允许导入自定义，但内置只推一个
    if override_ids is not None:
        ids = [_normalize_pack_id(str(x)) for x in override_ids if str(x).strip()]
        # 去重保序，最多 1 个内置+自定义合计仍 cap 在 resolve 里
        out: List[str] = []
        for i in ids:
            if i and i not in out:
                out.append(i)
        return out[:1] or default_active_ids()
    state = _project_mentor_state(project)
    ids = state.get("activeIds")
    if isinstance(ids, list) and ids:
        norm = [_normalize_pack_id(str(x)) for x in ids if str(x).strip()]
        out: List[str] = []
        for i in norm:
            if i and i not in out:
                out.append(i)
        if out:
            return out[:1]
    return default_active_ids()


def custom_packs_for_project(project: Any) -> List[Dict[str, Any]]:
    state = _project_mentor_state(project)
    packs = state.get("customPacks")
    return [p for p in packs if isinstance(p, dict)] if isinstance(packs, list) else []


def resolve_project_mentors(
    project: Any,
    *,
    override_ids: Optional[Sequence[str]] = None,
    max_active: int = 1,
) -> List[MentorPack]:
    return resolve_packs(
        active_ids_for_project(project, override_ids=override_ids),
        custom=custom_packs_for_project(project),
        max_active=max_active,
    )


def build_mentor_prompt_for_project(
    project: Any,
    *,
    stage: Optional[str] = None,
    task: Optional[str] = None,
    override_ids: Optional[Sequence[str]] = None,
    total_budget: int = 3600,
) -> str:
    packs = resolve_project_mentors(project, override_ids=override_ids)
    if not packs:
        return ""
    st = stage or stage_for_agent_task(task)
    return mentors_prompt_block(packs, stage=st, total_budget=total_budget)


# 旧别名一律指向统一写作导师（兼容历史话术）
MENTOR_ALIASES: Dict[str, str] = {
    "写作导师": "ln-vn-editor",
    "文学编辑": "ln-vn-editor",
    "编辑": "ln-vn-editor",
    "导师": "ln-vn-editor",
    "舞台": "ln-vn-editor",
    "舞台导师": "ln-vn-editor",
    "钩子": "ln-vn-editor",
    "热度": "ln-vn-editor",
    "钩子导师": "ln-vn-editor",
    "ln-vn-editor": "ln-vn-editor",
    "ln-vn-stagecraft": "ln-vn-editor",
    "ln-hook-and-heat": "ln-vn-editor",
}


def match_mentor_ids_from_text(text: str) -> List[str]:
    """历史兼容：任何导师话术都解析为统一写作导师。"""
    t = (text or "").strip()
    if not t:
        return []
    # 提到导师/编辑/旧包名 → 统一包
    if any(k in t for k in ("导师", "编辑", "舞台", "钩子", "热度", "ln-vn")):
        return ["ln-vn-editor"]
    return ["ln-vn-editor"] if "mentor" in t.lower() else []
