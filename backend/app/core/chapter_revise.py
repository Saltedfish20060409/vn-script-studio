"""Chapter revise: diagnose → rewrite → adversarial gate (optional second rewrite).

Studio-native责编回炉：把「人味回炉」协议固化进流水线，而不是靠用户手写提示词。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.domain.types import VnProject

from .agent_context import _blocks_to_plain
from .ai import DeepSeekConfig
from .llm_http import chat_completions, content_from_response, usage_from_response
from .narrative_lint import lint_narrative_draft

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")
_INNER_OS_RE = re.compile(r"[（(【\[]\s*内心\s*OS|内心\s*OS\s*[：:]", re.IGNORECASE)

# Locked editorial protocol — genre-agnostic execution layer.
REVISE_PROTOCOL = """## 固化改稿协议（必须遵守）

目标读感：读完应感到「关系有毛边 / 人在场」，不是「读者上完世界课」。

保留优先：有温度的动机、尴尬对视、起名/称呼时的刺痛感、角色用感知描述世界（而非定义）、旁人闲聊里的温度。

必须砍/改：
1. 问答词典：问→解释→原来如此/明白了（任务总结）
2. 场景/物件导览说明书（带你熟悉一下这里、这里是…那边是…）
3. 连续工序/常识课（为什么要…、什么时候放…、原理就是…——过程用旁白带过，留入口感受）
4. 「（内心OS：…）」或标注式心情；改成动作/视角旁白
5. 主角每问必答；允许沉默、答非所问、懒得说、不会答
6. 选项若全是正确解释：至少一项「说不清 / 不答 / 答偏」
7. **交互保真**：原文若有「请选择您的回答」+ A/B/C，改写稿必须保留同结构菜单（可改文案），禁止整段删掉；至少一项毛边

篇幅原则：**改稿不是缩写。** 删的是说明书与假温度，不是气氛与关系。
- 该砍：百科课、导览、任务总结、每问必答的长解释
- 该留/可扩：对视、沉默、入口感受、错位、毛边选项、旁人闲聊里的温度
- 禁止为了「变短」而抽干人味；也禁止用空旁白灌水凑字

结构偏好（按原文节拍回炉，勿换故事）：接人/会面 → 对视 → 称呼/起名（毛边）→ 压缩空间移动 → 日常互动（过程短感受长）→ 一处错位 → 余韵。
不要换故事，只回炉执行层。
"""

GOLDEN_FEWSHOT = """## 改法示范（执行层，照此刀法）

改前：带你熟悉一下这里。这里是客厅 / 那边是……
改后：你领她走过空间，没有解说。她自己停了一下，看向窗户。

改前：明白了。为了达成「要求」…… / 也不用当成任务来完成。
改后：她轻轻点头，把这句话留在空气里，没有收成任务清单。

改前：为什么要分开？什么时候放？原理就是……
改后：旁白两句带过工序；留入口感受。

改前：A/B/C 三句全是正确解释
改后：保留菜单；C. “……我也说不清。”

改前：私人空间，就是需要「尊重」对吧？接定义课
改后：锁门动作 + 一句错位；不讲定义。
"""

DIAGNOSE_SYSTEM = f"""你是资深视觉小说 / 轻小说责编。只做结构级审稿，不写完整改稿。

{REVISE_PROTOCOL}

额外硬查：
- 问答乒乓与百科课密度
- 内心OS标签
- 客观上帝旁白是否取代角色温度
- 选项是否假选择（三句正确解释）

只输出 JSON：
{{
  "verdict": "一句话总评（点名执行层问题）",
  "keep": [{{"what":"","why":""}}],
  "cut": [{{"what":"","why":""}}],
  "rewrite": [{{"what":"","how":"","before":"原句摘录","after":"改后示例"}}],
  "structure": ["新节拍 3～7 条"],
  "antiPatternsHit": ["qa_pingpong|inner_os|tour_lecture|always_answer|fake_choice|cold_narration"]
}}
keep/cut 至少各 1；rewrite 至少 2，before/after 尽量摘原文（before 必须能在原文中找到）。
"""

REWRITE_SYSTEM = f"""你是资深视觉小说责编兼改稿人。输出**完整改写后的章节正文**。

{REVISE_PROTOCOL}

{GOLDEN_FEWSHOT}

硬性要求：
- 只输出正文（场景/画面/对白/选项），不要前言、不要 JSON、不要「改写说明」。
- 必须落实诊断 keep/cut/rewrite/structure。
- 禁止问答词典串；禁止「（内心OS：…）」；禁止连续物件讲解课。
- **禁止**角色把名字总结成「明白了。为了达成…要求/任务…」。
- **禁止**场景导览说明书（这里是…/工作区 + 尊重定义课）。
- **禁止**工序/常识百科问答（为什么要分开、什么时候放、原理就是…）；过程旁白带过，只留入口感受。
- **原文有选择菜单则必须保留**：含「请选择您的回答」与 A/B/C；至少一项毛边（「……我也说不清」）。
- **改稿≠缩写**：砍说明书与假选择；相处、对视、入口感受、错位处该留则留，需要时允许略写长一点来保温度。
- 禁止空旁白灌水；禁止把已干净的短章灌成说明书。
- 对白要有毛边：沉默、跑题、不解释、答非所问。
- 保留人名、称谓、系统输入名、选项标记风格；假选择要改成真选择（含「说不清」）。
- 不换主线情节，只改执行层与节奏。结构优先：会面→对视→称呼/起名→删导览→日常留感受→错位→余韵。
"""

CRITIC_SYSTEM = f"""你是挑错责编，不是作者。默认假设回炉稿仍有说明书腔。

{REVISE_PROTOCOL}

若命中任一项 → ok=false，并给出 revised_text（完整正文）：
- 仍有问→答→明白了循环
- 角色把名字/相处总结成「为了达成…要求/任务」
- 仍有内心OS标签
- 仍有场景导览说明书（这里是…/工作区/私人空间=尊重）
- 仍有工序/常识百科问答（为什么要…、什么时候放…、原理就是…）
- 主角仍每问必答、长篇解释物件/规则定义
- 读感仍是「上课」不是「相处」
- 原文有菜单却被删光

硬删示例（若出现必须改掉）：
- 「明白了。为了达成…要求/任务…」
- 「私人空间，就是需要『尊重』对吧？」接定义讲解
- 连续「为什么要分开？」「什么时候放？」类工序课

输出 JSON：
{{
  "ok": false,
  "issues": ["..."],
  "revised_text": "完整改写正文（ok=false 时必填；必须真正删掉上述反模式，不要微调保留）",
  "note": "一句话"
}}
ok=true 时可省略 revised_text。
"""

PATCH_SYSTEM = """你是局部补丁编辑。只落实用户给出的 before→after 替换，输出完整正文。
硬性：禁止扩写；禁止回潮（任务总结/导览/工序百科/内心OS/假选择）；其余段落尽量原样；若原文要求保留 A/B/C 菜单则必须保留且含「说不清」。
只输出正文。
"""

SEGMENT_QA_SYSTEM = """你是问答去说明书编辑。用户给出若干「乒乓段」全文片段。
任务：把每段压成相处感——最多保留 1 次短问 + 短答或沉默/跑题；删百科解释与「明白了」总结。
输出 JSON：{"segments":[{"id":0,"text":"改后片段"},...]}
id 必须对应输入；text 为改后片段（可短于原文）。
"""


def _hard_fail_snippets(text: str) -> List[str]:
    """Deterministic leftovers the critic often soft-pedals."""
    hits: List[str] = []
    if re.search(
        r"为了达成.{0,12}(要求|任务)|当成任务来完成|一本正经的总结",
        text,
    ):
        hits.append("task_summary_ack")
    if re.search(r"私人空间.{0,20}尊重", text):
        hits.append("respect_lecture")
    if re.search(
        r"这里是(?:厨房|客厅|卧室|我的工作区)|带你熟悉一下这里|熟悉一下这个空间|"
        r"那边是吃饭的地方|冰箱里有食材.?饿了|带你熟悉一下|我来给你介绍一下这里",
        text,
    ):
        hits.append("apartment_tour")
    # Genre-agnostic process / encyclopedia Q&A (not cooking-demo-bound).
    if re.search(
        r"为什么要分开|什么时候(?:放|撒|加)|盐是现在撒|先焯水再|"
        r"原理是什么|简单来说就是|换句话说就是|需要先了解",
        text,
    ):
        hits.append("process_faq")
    if _INNER_OS_RE.search(text):
        hits.append("inner_os")
    if _has_fake_choice(text):
        hits.append("fake_choice")
    return hits


_ROUGH_OPT_RE = re.compile(r"说不清|不知道|不回答|也说不清|先不答|沉默|懒得说")
_MENU_PROMPT_RE = re.compile(r"(?:系统提示：?\s*)?请选择(?:您的)?回答")
_CHOICE_BLOCK_RE = re.compile(
    r"(?:系统提示：?\s*)?请选择(?:您的)?回答\s*\n+(?:[ \t]*[ABC]\.\s*.+\n*){2,}",
    re.M,
)
_ACK_LINE_RE = re.compile(r"^(?:明白了|原来如此|懂了)[。！.…]")
_LECTURE_HINT_RE = re.compile(r"因为|就是|所谓|定义|原理|需要先|换句话说|简单来说")


def _has_choice_menu(text: str) -> bool:
    if not _MENU_PROMPT_RE.search(text or ""):
        return False
    return len(re.findall(r"^[ \t]*[ABC]\.\s*.+$", text or "", flags=re.M)) >= 2


def _extract_choice_blocks(text: str) -> List[str]:
    return [m.group(0).strip() for m in _CHOICE_BLOCK_RE.finditer(text or "")]


def _has_fake_choice(text: str) -> bool:
    if not _has_choice_menu(text):
        return False
    opts = re.findall(r"^[ \t]*[ABC]\.\s*.+$", text, flags=re.M)
    if len(opts) < 2:
        return False
    return not any(_ROUGH_OPT_RE.search(o) for o in opts)


def _ensure_rough_choice(text: str) -> Tuple[str, bool]:
    """Inject a rough-edge option into A/B/C menus when all options are tidy explanations."""
    if not _has_fake_choice(text):
        return text, False

    def repl(m: re.Match[str]) -> str:
        letter = m.group(1)
        body = m.group(2)
        if letter == "C":
            return 'C. “……我也说不清。”'
        return f"{letter}. {body}"

    patched = re.sub(r"^([ABC])\.\s*(.+)$", repl, text, flags=re.M)
    return patched, True


def _force_rough_in_menu(menu: str) -> str:
    patched, _ = _ensure_rough_choice(menu)
    if _ROUGH_OPT_RE.search(patched):
        return patched
    if re.search(r"^[ \t]*C\.\s*", patched, flags=re.M):
        return re.sub(
            r"^[ \t]*C\.\s*.+$",
            'C. “……我也说不清。”',
            patched,
            count=1,
            flags=re.M,
        )
    return patched.rstrip() + '\nC. “……我也说不清。”'


def _find_menu_insert_pos(draft: str) -> int:
    """Prefer after naming/call beat; else ~35% into draft."""
    for pat in (r"起名", r"叫什么", r"给你取", r"名字", r"编号"):
        m = re.search(pat, draft)
        if m and m.end() > 40:
            nl = draft.find("\n\n", m.end())
            if nl > 0:
                return nl
    cut = max(80, int(len(draft) * 0.35))
    nl = draft.find("\n\n", cut)
    return nl if nl > 0 else cut


def _reseed_menus_from_source(draft: str, source: str) -> Tuple[str, bool]:
    """If source had A/B/C menus but draft dropped them, re-inject with rough edge."""
    if not _has_choice_menu(source):
        return draft, False
    if _has_choice_menu(draft):
        return draft, False
    blocks = _extract_choice_blocks(source)
    if not blocks:
        return draft, False
    menu = _force_rough_in_menu(blocks[0])
    pos = _find_menu_insert_pos(draft)
    injected = draft[:pos].rstrip() + "\n\n" + menu + "\n\n" + draft[pos:].lstrip()
    return injected.strip(), True


def _compress_qa_pingpong(text: str) -> Tuple[str, List[str]]:
    """Rule compression: drop ack-summaries and long lecture answers after questions."""
    tags: List[str] = []
    lines = (text or "").split("\n")
    out: List[str] = []
    prev_was_q = False
    for ln in lines:
        s = ln.strip()
        if not s:
            out.append(ln)
            continue
        if _ACK_LINE_RE.match(s) or re.search(r"明白了[。.].{0,8}为了达成", s):
            tags.append("ack_loop")
            prev_was_q = False
            continue
        is_q = ("？" in s or "?" in s) and len(s) <= 48
        if is_q:
            prev_was_q = True
            out.append(ln)
            continue
        if prev_was_q and len(s) >= 56 and _LECTURE_HINT_RE.search(s):
            tags.append("lecture_answer")
            prev_was_q = False
            continue
        if prev_was_q and len(s) >= 90:
            tags.append("long_answer")
            prev_was_q = False
            continue
        prev_was_q = False
        out.append(ln)
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, sorted(set(tags))


def _extract_qa_segments(text: str, *, limit: int = 3) -> List[Dict[str, Any]]:
    """Pull paragraph windows that look like Q&A lectures for short-context fix."""
    chunks = [c.strip() for c in re.split(r"\n{2,}", text or "") if c.strip()]
    segs: List[Dict[str, Any]] = []
    for i, c in enumerate(chunks):
        qmarks = c.count("？") + c.count("?")
        if qmarks >= 2 or (qmarks >= 1 and len(c) >= 120 and _LECTURE_HINT_RE.search(c)):
            segs.append({"id": len(segs), "text": c, "chunk_index": i})
        if len(segs) >= limit:
            break
    return segs


def _apply_segment_replacements(
    text: str, segments: List[Dict[str, Any]], replacements: List[Dict[str, Any]]
) -> str:
    chunks = [c.strip() for c in re.split(r"\n{2,}", text or "") if c.strip()]
    by_id = {int(r.get("id")): str(r.get("text") or "") for r in replacements if "id" in r}
    for seg in segments:
        sid = int(seg["id"])
        idx = int(seg["chunk_index"])
        if sid in by_id and 0 <= idx < len(chunks) and by_id[sid].strip():
            chunks[idx] = by_id[sid].strip()
    return "\n\n".join(chunks).strip()


def _apply_diagnosis_patches(
    text: str, diagnosis: Dict[str, Any]
) -> Tuple[str, int]:
    """Deterministic before→after from diagnose.rewrite when before is found."""
    items = diagnosis.get("rewrite")
    if not isinstance(items, list):
        return text, 0
    out = text
    n = 0
    for it in items[:6]:
        if not isinstance(it, dict):
            continue
        before = str(it.get("before") or "").strip()
        after = str(it.get("after") or "").strip()
        if len(before) < 6 or not after or before == after:
            continue
        if before in out:
            out = out.replace(before, after, 1)
            n += 1
    return out, n


def _commercial_score(
    text: str, *, source_chars: int = 0, source_text: str = ""
) -> Dict[str, Any]:
    """Commercial gate = hard antipatterns + menu fidelity.

    Length ratio is informational only. Revision is not abridgment: cutting
    lecture-voice is good; forcing 70–80% length is not a quality proxy.
    """
    hard = _hard_fail_snippets(text)
    dens_ratio = (len(text) / source_chars) if source_chars else 0.0
    menu_miss = bool(source_text) and _has_choice_menu(source_text) and not _has_choice_menu(text)
    return {
        "hard": hard,
        "chars": len(text),
        "density_vs_source": round(dens_ratio, 3) if source_chars else None,
        "too_dense": False,  # legacy field; no longer a fail condition
        "menu_miss": menu_miss,
        "pass": (not hard) and not menu_miss,
    }


@dataclass
class ChapterReviseResult:
    diagnosis: Dict[str, Any]
    diagnosis_md: str
    revised_text: str
    message: str
    chapter_id: Optional[str] = None
    chapter_title: str = ""
    source_chars: int = 0
    source_text: str = ""
    warnings: List[str] = field(default_factory=list)  # user-facing only
    debug_trace: List[str] = field(default_factory=list)  # pipeline internals
    model: str = ""
    critic_note: str = ""
    lint_issues: List[str] = field(default_factory=list)
    llm_calls: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0


_MODE_HINTS = {
    "cut_lecture": (
        "模式【只去说明书】：优先删除问答课、导览、内心OS、假选择；"
        "尽量保留原文语感与气氛，禁止为「人味」大段重写。"
    ),
    "human_warmth": (
        "模式【加强人味】：去说明书硬伤，并加强毛边、对视与相处感；"
        "改稿不是缩写，温度段可略写长。"
    ),
    "light_touch": (
        "模式【轻润不改结构】：只动硬伤与假选择；节拍、大段旁白、人物口吻尽量原样。"
    ),
}


def _prefs_hint(preferences: Optional[Dict[str, Any]]) -> str:
    if not isinstance(preferences, dict) or not preferences:
        return ""
    bits: List[str] = []
    locked = preferences.get("lockedNames") or preferences.get("locked_names")
    if isinstance(locked, list) and locked:
        names = "、".join(str(x).strip() for x in locked if str(x).strip())
        if names:
            bits.append(f"别动这些称呼/角色相关段落的口吻与戏份：{names}")
    if preferences.get("preferKeepOriginal") or preferences.get("prefer_keep_original"):
        bits.append("用户倾向保留原文气氛，少改大段旁白")
    notes = preferences.get("notes")
    if isinstance(notes, list):
        for n in notes[-4:]:
            t = str(n).strip()
            if t:
                bits.append(t)
    if not bits:
        return ""
    return "用户本章偏好：\n- " + "\n- ".join(bits)


def _looks_jumpy(text: str) -> bool:
    """Heuristic: excision left dangling connectors / tiny orphan paragraphs."""
    if re.search(r"(也不用当成任务|一本正经的总结|也不用当成)", text):
        return True
    for chunk in re.split(r"\n{2,}", text or ""):
        c = chunk.strip()
        if 1 <= len(c) <= 18 and re.match(r"^[也还于是不过而且]", c):
            return True
    return False


def _needs_smooth(before: str, after: str) -> bool:
    """Only spend a smooth LLM call when excision left a real jump cut."""
    dropped = len(before or "") - len(after or "")
    if dropped < 80:
        return False
    return _looks_jumpy(after)


def _soft_critic_needed(
    text: str, *, source_chars: int, source_text: str = ""
) -> Tuple[bool, List[str]]:
    """Whether a soft LLM critic pass is worth the cost after rule nets."""
    smells = _draft_smell_flags(text)
    lint_notes: List[str] = []
    for i in lint_narrative_draft(text):
        if i.severity != "error":
            continue
        if i.code in ("multi_question", "qa_pingpong") and "葵" in i.message:
            continue
        lint_notes.append(f"{i.code}:{i.message}")
    notes = sorted(set(smells + lint_notes))
    score = _commercial_score(text, source_chars=source_chars, source_text=source_text)
    if score["pass"]:
        return False, notes
    return True, notes


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


_ANTIPATTERN_LABELS = {
    "qa_pingpong": "问答乒乓",
    "inner_os": "内心OS标签",
    "tour_lecture": "空间导览课",
    "always_answer": "每问必答",
    "fake_choice": "假选择",
    "cold_narration": "冷旁白压温度",
    "apartment_tour": "场景导览",
    "process_faq": "工序/百科问答",
    "cooking_faq": "工序/百科问答",  # legacy alias
    "task_summary_ack": "任务总结腔",
    "respect_lecture": "尊重定义课",
    "ack_loop": "明白了循环",
    "why_what_dense": "为什么/是什么过密",
}


def _label_antipattern(code: str) -> str:
    c = str(code or "").strip()
    if not c:
        return ""
    if ":" in c:
        head, rest = c.split(":", 1)
        return f"{_ANTIPATTERN_LABELS.get(head, head)}（{rest.strip()}）"
    return _ANTIPATTERN_LABELS.get(c, c)


def _build_user_notes(
    *,
    score: Dict[str, Any],
    final_hard: List[str],
    final_smells: List[str],
    source_title: str,
) -> List[str]:
    notes: List[str] = ["预览尚未写入工程；确认后可点「写入当前章」，对话内可撤回。"]
    if source_title:
        notes.insert(0, f"回炉对象：{source_title}")
    if final_hard:
        notes.append(
            "仍有说明书硬伤未清干净："
            + "、".join(_label_antipattern(h) for h in final_hard)
        )
    elif score.get("menu_miss"):
        notes.append("原文有选择菜单，改写稿里缺失了，建议再回炉一次。")
    else:
        notes.append("结构闸门已过：说明书硬伤清空、选择菜单保留。")
    dens = score.get("density_vs_source")
    if isinstance(dens, float) and dens > 0:
        notes.append(
            f"篇幅对照：改写约原文 {dens:.0%}（仅供参考；改稿不是缩写，可再要求加温度或压说明书）。"
        )
    if final_smells:
        notes.append(
            "仍建议扫一眼："
            + "、".join(_label_antipattern(s) for s in final_smells)
            + "。"
        )
    return notes


def format_diagnosis_md(diag: Dict[str, Any]) -> str:
    lines: List[str] = ["### 章节回炉 · 诊断", ""]
    verdict = str(diag.get("verdict") or "").strip()
    if verdict:
        lines.append(verdict)
        lines.append("")

    hits = diag.get("antiPatternsHit")
    if isinstance(hits, list) and hits:
        labeled = [_label_antipattern(str(h)) for h in hits if str(h).strip()]
        lines.append("**主要问题：** " + "、".join(labeled))
        lines.append("")

    def _rows(key: str, title: str, fields: Tuple[str, ...]) -> None:
        items = diag.get(key)
        if not isinstance(items, list) or not items:
            return
        lines.append(f"**{title}**")
        for it in items:
            if not isinstance(it, dict):
                continue
            bits = [str(it.get(f) or "").strip() for f in fields]
            bits = [b for b in bits if b]
            if bits:
                lines.append(f"- {' —— '.join(bits)}")
        lines.append("")

    _rows("keep", "保留", ("what", "why"))
    _rows("cut", "删除 / 压缩", ("what", "why"))
    rewrite = diag.get("rewrite")
    if isinstance(rewrite, list) and rewrite:
        lines.append("**重写要点**")
        for it in rewrite:
            if not isinstance(it, dict):
                continue
            what = str(it.get("what") or "").strip()
            how = str(it.get("how") or "").strip()
            before = str(it.get("before") or "").strip()
            after = str(it.get("after") or "").strip()
            head = " — ".join(x for x in (what, how) if x)
            if head:
                lines.append(f"- {head}")
            if before:
                lines.append(f"  - 改前：{before}")
            if after:
                lines.append(f"  - 改后：{after}")
        lines.append("")

    structure = diag.get("structure")
    if isinstance(structure, list) and structure:
        lines.append("**建议节拍**")
        for i, s in enumerate(structure, 1):
            t = str(s).strip()
            if t:
                lines.append(f"{i}. {t}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def project_brief(project: VnProject, *, max_chars: int = 2200) -> str:
    lines = [
        f"作品：{project.title}",
        f"类型：{project.genre or ''}",
        f"一句话：{(project.logline or '')[:200]}",
        "角色（语气内部参考，禁止写成说明书对白）：",
    ]
    for c in project.characters[:12]:
        lines.append(
            f"- {c.displayName}/{c.defineName}: voice={c.voice or ''}；bio={(c.bio or '')[:120]}"
        )
    b = project.bible
    if b:
        if b.themes:
            lines.append(f"主题：{(b.themes or '')[:300]}")
        if b.outline:
            lines.append(f"大纲摘：{(b.outline or '')[:400]}")
        if b.world:
            lines.append(f"世界规则摘：{(b.world or '')[:280]}")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars]


def resolve_chapter_source(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    max_chars: int = 16000,
) -> Tuple[str, Optional[str], str, List[str]]:
    warnings: List[str] = []
    parts: List[str] = []
    for a in attachments or []:
        t = str(a.get("text") or "").strip()
        if t:
            parts.append(t)
    att_text = "\n\n".join(parts).strip()

    ch = None
    if chapter_id:
        ch = next((c for c in project.chapters if c.id == chapter_id), None)
    if ch is None and project.chapters:
        ch = project.chapters[0]

    chapter_plain = ""
    cid: Optional[str] = None
    title = ""
    if ch is not None:
        chapter_plain = (_blocks_to_plain(ch.blocks, project.characters) or "").strip()
        cid = ch.id
        title = ch.title or ""

    if att_text and len(att_text) >= 400:
        source = att_text
        warnings.append("以附件正文为回炉来源（优先于当前章）")
    elif chapter_plain:
        source = chapter_plain
    elif att_text:
        source = att_text
        warnings.append("当前章为空，使用附件正文")
    else:
        raise RuntimeError("没有可回炉的正文：请打开有内容的章节，或先上传章节附件")

    if len(source) > max_chars:
        source = source[:max_chars]
        warnings.append(f"正文过长，已截取前 {max_chars} 字做回炉")
    return source, cid, title, warnings


def _draft_smell_flags(text: str) -> List[str]:
    flags: List[str] = []
    if _INNER_OS_RE.search(text):
        flags.append("inner_os")
    if text.count("明白了") + text.count("原来如此") >= 2:
        flags.append("ack_loop")
    if text.count("为什么") + text.count("是什么") >= 5:
        flags.append("why_what_dense")
    for iss in lint_narrative_draft(text):
        if iss.code == "qa_pingpong":
            flags.append("qa_pingpong")
            break
    return sorted(set(flags))


async def _chat_json(
    config: DeepSeekConfig,
    *,
    system: str,
    user: str,
    temperature: float,
    max_tokens: Optional[int] = None,
) -> Tuple[str, str, Dict[str, int]]:
    res = await chat_completions(
        config,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        timeout=180,
    )
    raw, model = content_from_response(res)
    return raw or "{}", model or (config.model or "deepseek-chat"), usage_from_response(res)


async def _chat_text(
    config: DeepSeekConfig,
    *,
    system: str,
    user: str,
    temperature: float,
    max_tokens: Optional[int] = None,
) -> Tuple[str, str, Dict[str, int]]:
    res = await chat_completions(
        config,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=240,
    )
    raw, model = content_from_response(res)
    return raw.strip(), model or (config.model or "deepseek-chat"), usage_from_response(res)


def _strip_rewrite_wrapper(text: str) -> str:
    t = (text or "").strip()
    fence = _FENCE_RE.search(t)
    if fence and len(fence.group(1).strip()) > 200:
        return fence.group(1).strip()
    for marker in ("### 改写稿", "## 改写稿", "【改写稿】"):
        if marker in t:
            t = t.split(marker, 1)[-1].strip()
    return t.strip()


def _deterministic_excise(text: str) -> Tuple[str, List[str]]:
    """Rule-based excision when LLMs claim deletion but leave antipatterns."""
    removed: List[str] = []
    chunks = re.split(r"\n{2,}", text or "")
    kept: List[str] = []
    for chunk in chunks:
        c = chunk.strip()
        if not c:
            continue
        hit = _hard_fail_snippets(c)
        if not hit:
            kept.append(c)
            continue
        # Fake-choice alone: patch options instead of deleting the scene
        if set(hit) == {"fake_choice"}:
            patched, _ = _ensure_rough_choice(c)
            kept.append(patched)
            removed.append("fake_choice")
            continue
        # Try line-level salvage first
        lines = c.split("\n")
        new_lines: List[str] = []
        for ln in lines:
            lh = _hard_fail_snippets(ln)
            if lh:
                removed.extend(lh)
                continue
            new_lines.append(ln)
        salvaged = "\n".join(new_lines).strip()
        if salvaged:
            salvaged, _ = _ensure_rough_choice(salvaged)
        # If chunk still mostly a tour/faq block, drop entirely
        if salvaged and not _hard_fail_snippets(salvaged):
            if len(salvaged) >= 8:
                kept.append(salvaged)
        else:
            # last chance: only fake_choice left
            if salvaged and set(_hard_fail_snippets(salvaged)) <= {"fake_choice"}:
                patched, _ = _ensure_rough_choice(salvaged)
                kept.append(patched)
                removed.append("fake_choice")
            else:
                removed.extend(hit)
    # de-dupe removed tags
    removed = sorted(set(removed))
    out = "\n\n".join(kept).strip()
    # Final line sweep
    if _hard_fail_snippets(out):
        final_lines = []
        for ln in out.split("\n"):
            if _hard_fail_snippets(ln):
                removed.extend(_hard_fail_snippets(ln))
                continue
            final_lines.append(ln)
        out = "\n".join(final_lines)
        # collapse excess blank lines
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        removed = sorted(set(removed))
    return out, removed


SMOOTH_SYSTEM = """你是缝合编辑。正文刚被规则删掉若干说明书段落，可能出现跳切。
任务：只做最小衔接（一两句旁白/动作），禁止重新引入：
- 为了达成…要求/任务
- 场景导览（这里是…/工作区/带你熟悉）
- 工序/百科问答（为什么要分开、什么时候放、原理就是…）
- 私人空间=尊重讲义
- 内心OS标签
- 三选项全是正确解释（若有 A/B/C，保留含「说不清」的毛边项）
输出完整正文，不要说明。
"""

COMPRESS_SYSTEM = f"""你是压缩责编。用户明确要求压短时才启用。

{REVISE_PROTOCOL}

硬性：
- 优先删说明书与重复解释，不要抽干对视/入口感受/错位等温度
- 空间移动用动作带过，禁止导览课
- 若有 A/B/C，必须含「……我也说不清」类毛边项
- 禁止回潮：为了达成…、为什么要分开、什么时候放、带你熟悉一下这里、当成任务来完成、内心OS
输出完整正文。
"""

SURGICAL_SYSTEM = f"""你是手术刀式改稿编辑。只消灭残留硬伤，输出完整正文。

{REVISE_PROTOCOL}

本轮唯一任务：删除用户列出的残留硬反模式，其它好段落尽量原样保留。
- process_faq / cooking_faq：删掉「为什么要分开 / 什么时候放 / 原理就是…」整段问答；过程用两三句旁白带过，只留入口感受。
- apartment_tour：删导览说明书（含「熟悉一下这个空间 / 那边是吃饭的地方」）。
- task_summary_ack：删「为了达成…要求/任务」，以及孤儿句「当成任务来完成 / 一本正经的总结」。
- respect_lecture：删「私人空间=尊重」定义课。
- inner_os：删内心OS标签。
只输出完整正文。
"""


async def run_chapter_revise(
    config: DeepSeekConfig,
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    note: str = "",
    attachments: Optional[List[Dict[str, Any]]] = None,
    critic_config: Optional[DeepSeekConfig] = None,
    mode: Optional[str] = None,
    preferences: Optional[Dict[str, Any]] = None,
) -> ChapterReviseResult:
    import time

    t0 = time.perf_counter()
    llm_calls: List[Dict[str, Any]] = []

    def _track(stage: str, model: str, tokens: Dict[str, int]) -> None:
        llm_calls.append(
            {
                "stage": stage,
                "model": model,
                "prompt_tokens": tokens.get("prompt", 0),
                "completion_tokens": tokens.get("completion", 0),
                "total_tokens": tokens.get("total", 0),
            }
        )

    source, cid, title, warnings = resolve_chapter_source(
        project, chapter_id=chapter_id, attachments=attachments
    )
    brief = project_brief(project)
    note_bit = (note or "").strip() or "按固化改稿协议回炉：砍问答课与内心OS，留相处与毛边。"
    mode_key = (mode or "").strip() or "human_warmth"
    if mode_key not in _MODE_HINTS:
        mode_key = "human_warmth"
    mode_hint = _MODE_HINTS[mode_key]
    pref_hint = _prefs_hint(preferences)
    guidance = "\n\n".join(x for x in (mode_hint, pref_hint) if x)
    critic_cfg = critic_config or config

    # --- 1) Diagnose (bounded) ---
    diagnose_user = (
        f"## 工程摘要\n{brief}\n\n"
        f"## 用户说明\n{note_bit}\n\n"
        f"## 回炉指引\n{guidance}\n\n"
        f"## 章节{('「' + title + '」') if title else ''}\n{source}"
    )
    raw_diag, model_a, tok_a = await _chat_json(
        config,
        system=DIAGNOSE_SYSTEM,
        user=diagnose_user,
        temperature=0.3,
        max_tokens=1600,
    )
    _track("diagnose", model_a, tok_a)
    try:
        diagnosis = _parse_json_obj(raw_diag)
    except Exception:
        diagnosis = {
            "verdict": "诊断解析失败，仍按固化协议改写。",
            "keep": [{"what": "核心相处骨架", "why": "回炉执行层"}],
            "cut": [{"what": "问答百科串与内心OS", "why": "说明书腔"}],
            "rewrite": [],
            "structure": [],
            "antiPatternsHit": ["qa_pingpong", "inner_os"],
        }
        warnings.append("诊断 JSON 解析失败，已用兜底诊断")

    diagnosis_md = format_diagnosis_md(diagnosis)

    # --- 2) Rewrite (main cost) ---
    rewrite_user = (
        f"## 工程摘要\n{brief}\n\n"
        f"## 用户说明\n{note_bit}\n\n"
        f"## 回炉指引\n{guidance}\n\n"
        f"## 诊断报告（必须落实）\n{json.dumps(diagnosis, ensure_ascii=False)}\n\n"
        f"## 原章节正文\n{source}\n\n"
        "请直接输出完整改写正文。"
    )
    revised_raw, model_b, tok_b = await _chat_text(
        config, system=REWRITE_SYSTEM, user=rewrite_user, temperature=0.5
    )
    _track("rewrite", model_b, tok_b)
    revised = _strip_rewrite_wrapper(revised_raw)
    if len(revised) < 80:
        raise RuntimeError("改写结果过短，请重试章节回炉")

    critic_note = ""
    lint_notes: List[str] = []

    # --- 3) Rule nets: rough choice → menu reseed → hard excise → QA compress ---
    before_rules = revised
    revised, injected0 = _ensure_rough_choice(revised)
    if injected0:
        warnings.append("规则补丁：选项已植入毛边项「我也说不清」")
    revised, reseeded = _reseed_menus_from_source(revised, source)
    if reseeded:
        warnings.append("交互保真：已从原文回植 A/B/C 菜单并加毛边项")
        revised, _ = _ensure_rough_choice(revised)

    hard_before = _hard_fail_snippets(revised)
    if hard_before:
        excised, removed_tags = _deterministic_excise(revised)
        if len(excised) >= 80:
            revised = excised
            warnings.append(
                "规则硬删："
                + ("、".join(removed_tags) if removed_tags else "、".join(hard_before))
            )
            # menus may be collateral-damaged; reseed again
            revised, reseeded2 = _reseed_menus_from_source(revised, source)
            if reseeded2:
                warnings.append("硬删后再次回植菜单")
            if _needs_smooth(before_rules, revised):
                smooth_raw, model_sm, tok_sm = await _chat_text(
                    critic_cfg,
                    system=SMOOTH_SYSTEM,
                    user=f"## 已硬删标记\n{removed_tags or hard_before}\n\n## 正文\n{revised}",
                    temperature=0.15,
                )
                _track("smooth", model_sm, tok_sm)
                smooth = _strip_rewrite_wrapper(smooth_raw)
                if len(smooth) >= 80 and not _hard_fail_snippets(smooth):
                    revised = smooth
                    model_b = model_sm or model_b
                    warnings.append("缝合轮：已平滑跳切且未回潮硬伤")
                    revised, _ = _reseed_menus_from_source(revised, source)
                elif len(smooth) >= 80 and _hard_fail_snippets(smooth):
                    warnings.append("缝合轮回潮硬伤，已丢弃缝合结果，保留规则硬删稿")
            else:
                warnings.append("跳过缝合轮：硬删后无明显跳切（降本）")

    qa_text, qa_tags = _compress_qa_pingpong(revised)
    if qa_tags and len(qa_text) >= 80:
        revised = qa_text
        warnings.append("规则压乒乓：" + "、".join(qa_tags))

    # --- 3b) Diagnosis local patches (free) + optional short patch LLM ---
    patched, n_pat = _apply_diagnosis_patches(revised, diagnosis)
    if n_pat:
        revised = patched
        warnings.append(f"诊断局部替换：落实 {n_pat} 处 before→after")
    pending_pairs = []
    for it in diagnosis.get("rewrite") or []:
        if not isinstance(it, dict):
            continue
        before = str(it.get("before") or "").strip()
        after = str(it.get("after") or "").strip()
        if len(before) >= 6 and after and before not in revised and before in source:
            pending_pairs.append({"before": before, "after": after})
    if pending_pairs[:3] and ("qa_pingpong" in _draft_smell_flags(revised) or n_pat == 0):
        patch_user = (
            f"## 必须落实的替换（找不到原句时可按语义就近改）\n"
            f"{json.dumps(pending_pairs[:3], ensure_ascii=False)}\n\n"
            f"## 正文\n{revised}"
        )
        patch_raw, model_p, tok_p = await _chat_text(
            critic_cfg,
            system=PATCH_SYSTEM,
            user=patch_user,
            temperature=0.2,
            max_tokens=8192,
        )
        _track("local_patch", model_p, tok_p)
        patch_out = _strip_rewrite_wrapper(patch_raw)
        if len(patch_out) >= 80 and not _hard_fail_snippets(patch_out):
            revised = patch_out
            warnings.append("局部补丁轮：已按诊断 before/after 微调")
            revised, _ = _reseed_menus_from_source(revised, source)
            revised, _ = _ensure_rough_choice(revised)
        else:
            warnings.append("局部补丁轮未采用（过短或回潮硬伤）")

    # --- 3c) Short-context QA segment fix when smell remains & still dense-ish ---
    dens_now = len(revised) / max(len(source), 1)
    if "qa_pingpong" in _draft_smell_flags(revised) and dens_now > 0.62:
        segs = _extract_qa_segments(revised, limit=3)
        if segs:
            seg_user = json.dumps(
                [{"id": s["id"], "text": s["text"]} for s in segs],
                ensure_ascii=False,
            )
            raw_seg, model_sg, tok_sg = await _chat_json(
                critic_cfg,
                system=SEGMENT_QA_SYSTEM,
                user=f"## 乒乓段\n{seg_user}",
                temperature=0.2,
                max_tokens=2500,
            )
            _track("qa_segments", model_sg, tok_sg)
            try:
                seg_obj = _parse_json_obj(raw_seg)
                reps = seg_obj.get("segments") if isinstance(seg_obj, dict) else None
            except Exception:
                reps = None
            if isinstance(reps, list) and reps:
                revised2 = _apply_segment_replacements(revised, segs, reps)
                if len(revised2) >= 80 and len(revised2) <= len(revised):
                    revised = revised2
                    warnings.append(f"短上下文压乒乓：改写 {len(reps)} 段")
                    revised, _ = _reseed_menus_from_source(revised, source)

    # --- 4) Critic only if commercial bar still fails after rules ---
    need_critic, smell_notes = _soft_critic_needed(
        revised, source_chars=len(source), source_text=source
    )
    lint_notes = list(smell_notes)
    if need_critic:
        ban = _hard_fail_snippets(revised)
        ban_list = "\n".join(f"- {h}" for h in ban) or "- （软气味/密度/菜单）"
        critic_user = (
            f"## 工程摘要\n{brief}\n\n"
            f"## 诊断\n{json.dumps(diagnosis, ensure_ascii=False)}\n\n"
            f"## 必须消灭的残留标记\n{ban_list}\n\n"
            f"## 规则引擎已坐实\n{json.dumps(smell_notes, ensure_ascii=False)}\n\n"
            f"## 回炉稿\n{revised}\n\n"
            "请输出 ok=false 的完整 revised_text：删掉导览课、工序百科、任务总结句；"
            "起名保留毛边与菜单；晚饭留感受；锁门只留错位一句。"
            "改稿不是缩写：不要为了变短而抽干人味。"
        )
        raw_c, model_c, tok_c = await _chat_json(
            critic_cfg, system=CRITIC_SYSTEM, user=critic_user, temperature=0.25
        )
        _track("critic", model_c, tok_c)
        try:
            critic = _parse_json_obj(raw_c)
        except Exception:
            critic = {"ok": False, "issues": ["critic_parse_failed"], "note": "挑错解析失败"}
        critic_note = str(critic.get("note") or "").strip()
        ok = bool(critic.get("ok"))
        revised2 = _strip_rewrite_wrapper(str(critic.get("revised_text") or ""))
        if (not ok) and len(revised2) >= 80:
            revised = revised2
            warnings.append("挑错责编未通过，已自动二轮改写")
            critic_note = critic_note or "；".join(
                str(x) for x in (critic.get("issues") or [])[:4]
            )
            model_b = model_c or model_b
            revised, inj_c = _ensure_rough_choice(revised)
            if inj_c:
                warnings.append("挑错后补丁：选项毛边")
            revised, _ = _reseed_menus_from_source(revised, source)
            if _hard_fail_snippets(revised):
                excised2, tags2 = _deterministic_excise(revised)
                if len(excised2) >= 80:
                    revised = excised2
                    warnings.append(
                        "挑错后硬删：" + ("、".join(tags2) if tags2 else "残留硬伤")
                    )
                    revised, _ = _reseed_menus_from_source(revised, source)
        elif ok:
            critic_note = critic_note or "挑错通过"
        else:
            warnings.append("挑错未通过且未给出可用二轮稿，请人工审一下预览")
    else:
        warnings.append("跳过全文挑错：规则网后已达商用闸门或无需软改写（降本）")
        if smell_notes:
            critic_note = "已跳过全文挑错；软气味作提示"
        else:
            critic_note = "未触发挑错"

    # --- 5) Compress only when user explicitly asks to shorten ---
    score = _commercial_score(revised, source_chars=len(source), source_text=source)
    wants_short = bool(
        re.search(r"压短|压缩|删减|缩短|再短|更短一点|缩短篇幅", note_bit)
    )
    if wants_short:
        dens = float(score.get("density_vs_source") or 0)
        comp_raw, model_cp, tok_cp = await _chat_text(
            critic_cfg,
            system=COMPRESS_SYSTEM,
            user=(
                f"## 用户要求压短\n原文 {len(source)} 字，当前 {len(revised)} 字"
                f"（约原文 {dens:.0%}）。删说明书与重复，保留温度。\n\n"
                f"## 正文\n{revised}"
            ),
            temperature=0.25,
        )
        _track("compress", model_cp, tok_cp)
        comp = _strip_rewrite_wrapper(comp_raw)
        if len(comp) >= 80:
            comp, _ = _ensure_rough_choice(comp)
            comp, _ = _reseed_menus_from_source(comp, source)
            if _hard_fail_snippets(comp):
                comp, _ = _deterministic_excise(comp)
                comp, _ = _reseed_menus_from_source(comp, source)
            if len(comp) >= 80 and len(comp) < len(revised):
                revised = comp
                model_b = model_cp or model_b
                warnings.append(f"压缩轮（用户要求）：{score['chars']}→{len(revised)} 字")
    else:
        warnings.append("跳过压缩轮：改稿不是缩写；用户未要求压短")

    # --- Final insurance ---
    revised, injected2 = _ensure_rough_choice(revised)
    if injected2:
        warnings.append("终检补丁：选项毛边")
    revised, reseeded_f = _reseed_menus_from_source(revised, source)
    if reseeded_f:
        warnings.append("终检：菜单回植")
    if _hard_fail_snippets(revised):
        excised_f, tags_f = _deterministic_excise(revised)
        if len(excised_f) >= 80:
            revised = excised_f
            warnings.append(
                "终检硬删：" + ("、".join(tags_f) if tags_f else "残留硬伤")
            )
            revised, _ = _reseed_menus_from_source(revised, source)

    final_smells = _draft_smell_flags(revised)
    final_hard = _hard_fail_snippets(revised)
    score = _commercial_score(revised, source_chars=len(source), source_text=source)
    if final_smells:
        warnings.append("仍可能残留：" + "、".join(final_smells))
    if final_hard:
        warnings.append("硬反模式仍在：" + "、".join(final_hard) + "（未达商用闸门）")
    elif score.get("menu_miss"):
        warnings.append("交互保真未通过：原文有菜单但改写稿缺失（未达商用闸门）")
    else:
        warnings.append("商用闸门：通过（硬反模式 + 菜单保真；篇幅不作硬门槛）")

    total_tokens = sum(int(c.get("total_tokens") or 0) for c in llm_calls)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    stages = "→".join(c["stage"] for c in llm_calls)
    warnings.append(
        f"降本画像：{len(llm_calls)} 轮 LLM（{stages}），约 {total_tokens} tokens，{elapsed_ms} ms"
    )

    debug_trace = list(warnings)
    user_notes = _build_user_notes(
        score=score,
        final_hard=final_hard,
        final_smells=final_smells,
        source_title=title or (cid or ""),
    )

    dens = score.get("density_vs_source")
    dens_bit = (
        f"（约原文 {dens:.0%}，仅对照）"
        if isinstance(dens, float)
        else ""
    )
    title_bit = f"「{title}」" if title else ""
    gate_lines = [
        f"改稿预览已就绪{title_bit}。",
        f"- 说明书硬伤：{'已处理' if not final_hard else '仍有残留，建议在对照里多留原文'}",
        f"- 选择菜单：{'已保留' if not score.get('menu_miss') else '可能缺失，写入前请检查'}",
        f"- 篇幅：{len(revised)} 字{dens_bit}",
    ]
    if final_smells:
        gate_lines.append("- 仍建议在对照面板扫一眼问答是否偏密")

    message = (
        "\n".join(gate_lines)
        + "\n\n请点本条回复下方的「打开改稿对照」挑选改稿/原文；关闭后仍可再点（刷新后也还在）。\n"
        "也可以继续说：「再润」「别动某某」「打开对照」。\n"
        "——\n"
        + "\n".join(f"- {n}" for n in user_notes)
    )
    return ChapterReviseResult(
        diagnosis=diagnosis,
        diagnosis_md=diagnosis_md,
        revised_text=revised,
        message=message,
        chapter_id=cid,
        chapter_title=title,
        source_chars=len(source),
        source_text=source,
        warnings=user_notes,
        debug_trace=debug_trace,
        model=model_b or model_a,
        critic_note=critic_note,
        lint_issues=lint_notes,
        llm_calls=llm_calls,
        elapsed_ms=elapsed_ms,
    )
