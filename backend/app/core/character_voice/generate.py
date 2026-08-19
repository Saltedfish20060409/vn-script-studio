"""Generate differentiated dialogue variants for preference calibration.

Axes are dynamic per character (card + optional tags + confirmed directions),
not a global fixed triad.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from app.core.ai import DeepSeekConfig
from app.core.character_voice.corpus import (
    confirmed_axes,
    find_character,
    format_corpus_for_prompt,
)
from app.core.character_voice.extract import format_script_anchors_for_prompt
from app.core.llm_http import content_from_response
from app.core.llm_provider import provider_from_config
from app.domain.types import Character, VnProject
from app.llm_models import DEFAULT_LLM_MODEL

# longSuitable: better for multi-turn「长场次」; still usable in 三选一.
SCENARIO_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "misunderstood",
        "label": "被误解时",
        "prompt": "对方误会了你的意图；你想澄清，但不愿显得在求饶或失控。",
        "longSuitable": True,
    },
    {
        "id": "care_awkward",
        "label": "想关心却别扭",
        "prompt": "你其实在担心对方，但嘴上说不出口，只能用别扭的方式靠近。",
        "longSuitable": True,
    },
    {
        "id": "authority",
        "label": "面对权威",
        "prompt": "老师/上司/前辈施压提问；你要守住边界，又不能无谓树敌。",
        "longSuitable": False,
    },
    {
        "id": "romance_edge",
        "label": "对恋爱对象",
        "prompt": "气氛暧昧，对方试探真心；你既想回应又怕暴露软肋。",
        "longSuitable": True,
    },
    {
        "id": "lie_edge",
        "label": "撒谎边缘",
        "prompt": "你必须隐瞒一件事；对方追问，你选择含糊、转移或半真半假。",
        "longSuitable": True,
    },
    {
        "id": "tired_truth",
        "label": "疲惫本音",
        "prompt": "一天结束，防护掉了一点；对信任的人露出更本音的一两句。",
        "longSuitable": True,
    },
    {
        "id": "refuse_request",
        "label": "拒绝请求",
        "prompt": "对方提出你办不到或不想办的事；你要拒绝，但留下关系余地。",
        "longSuitable": False,
    },
    {
        "id": "praise_awkward",
        "label": "被当面夸奖",
        "prompt": "对方真诚夸你；你不习惯被看见优点，反应要符合人设。",
        "longSuitable": False,
    },
    {
        "id": "apology",
        "label": "不得不道歉",
        "prompt": "你确实有错或伤了人；要道歉，但不愿卑微到失去自我。",
        "longSuitable": True,
    },
    {
        "id": "jealousy",
        "label": "吃醋却不承认",
        "prompt": "你在意对方和别人亲近，嘴上否认，情绪却漏出来。",
        "longSuitable": True,
    },
    {
        "id": "farewell",
        "label": "分别前夜",
        "prompt": "可能很久不见；有话想说，又怕说破后收不回来。",
        "longSuitable": True,
    },
    {
        "id": "secret_keep",
        "label": "被拜托保密",
        "prompt": "对方托你守住一个秘密；有人旁敲侧击，你要守口如瓶又显得自然。",
        "longSuitable": True,
    },
    {
        "id": "confrontation",
        "label": "当面拆穿",
        "prompt": "你发现对方在瞒你或说谎；要摊牌，但关系还想留。",
        "longSuitable": True,
    },
    {
        "id": "crisis_team",
        "label": "危机里协作",
        "prompt": "突发状况要一起扛；压力大，语气会露真性情，仍要配合完成事。",
        "longSuitable": True,
    },
    {
        "id": "idle_chat",
        "label": "无事闲聊",
        "prompt": "没什么大事，两人并排或隔桌闲聊；从琐事里露出习惯口吻。",
        "longSuitable": False,
    },
    {
        "id": "caught_soft",
        "label": "软肋被看见",
        "prompt": "对方无意撞见你不设防的一面；你又羞又防，想把场面圆回去。",
        "longSuitable": True,
    },
    {
        "id": "custom",
        "label": "自定义…",
        "prompt": "",
        "longSuitable": True,
    },
]

# Built-in tone tags users can pick (1–3). Not a closed world — LLM may invent
# nearby axes when fewer than 3 tags are chosen or none are chosen.
VOICE_AXIS_TAGS: List[Dict[str, str]] = [
    {"id": "taciturn", "label": "寡言克制", "hint": "话少、短句、情绪含蓄，信息点到为止。"},
    {"id": "gentle_persuade", "label": "温柔劝说", "hint": "软、安抚、把对方往安全处领，不压人。"},
    {"id": "formal_duty", "label": "公事公办", "hint": "礼貌疏离、讲规则与分工，少私人情绪。"},
    {"id": "chatty_warm", "label": "热络话痨", "hint": "话密、热络、用碎碎念拉近距离。"},
    {"id": "dry_humor", "label": "冷幽默", "hint": "淡淡挖苦或反差好笑，不吵不闹。"},
    {"id": "sharp_guard", "label": "毒舌防护", "hint": "用刺与抬杠挡软肋，外热内防。"},
    {"id": "soft_selfdeprec", "label": "软自嘲", "hint": "自嘲收尾留白，温度高但不卖惨。"},
    {"id": "lecture", "label": "正经说教", "hint": "讲道理、划边界，像前辈或老师口吻。"},
    {"id": "childlike", "label": "孩子气直球", "hint": "直白、情绪外露、少拐弯。"},
    {"id": "aristocrat", "label": "贵族疏离", "hint": "端、疏、用敬语或距离感压住亲密。"},
    {"id": "flustered", "label": "慌张口吃", "hint": "乱、重复、词不达意，心虚或害羞。"},
    {"id": "steady_soothe", "label": "沉稳安抚", "hint": "稳、慢、给安全感，少戏剧冲突。"},
    {"id": "calculating", "label": "算计试探", "hint": "旁敲侧击、留信息差，先摸底再表态。"},
    {"id": "cynical", "label": "愤世讽刺", "hint": "冷嘲世情，对人不对己时更锋利。"},
    {"id": "clingy", "label": "黏人撒娇", "hint": "黏、求关注，用软语气要回应。"},
    {"id": "social_avoid", "label": "社恐回避", "hint": "躲、转移话题、想逃出现场。"},
    {"id": "leader", "label": "领袖口吻", "hint": "下判断、给指令，带责任与决断。"},
    {"id": "scholar", "label": "学者咬文", "hint": "术语或精确措辞，用理性挡情绪。"},
    {"id": "cold_short", "label": "冷短回避", "hint": "更冷、短句、回避情绪词；留白多。"},
    {"id": "hot_banter", "label": "热吐槽防护", "hint": "更热、话稍多、吐槽抬杠作防护。"},
    {"id": "soft_blank", "label": "软留白", "hint": "轻声、省略、把未说完的留给对方。"},
    {"id": "loyal_blunt", "label": "忠直硬梆", "hint": "不会绕弯，忠诚但措辞生硬。"},
]

# Cold-start only when no card signal and no tags
_FALLBACK_AXES = [
    VOICE_AXIS_TAGS[18],  # cold_short
    VOICE_AXIS_TAGS[19],  # hot_banter
    VOICE_AXIS_TAGS[6],  # soft_selfdeprec
]

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")

# Sentinel used to mark variants the model failed to produce. Such variants are
# never acceptable as corpus samples (frontend hides them, API rejects them).
_PLACEHOLDER_MARKER = "（请重新生成）"


def list_scenarios() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in SCENARIO_TEMPLATES:
        row = dict(s)
        row["longSuitable"] = bool(row.get("longSuitable"))
        out.append(row)
    return out


def list_axis_tags() -> List[Dict[str, str]]:
    return [dict(t) for t in VOICE_AXIS_TAGS]


def _tag_by_id(tag_id: str) -> Optional[Dict[str, str]]:
    tid = (tag_id or "").strip()
    for t in VOICE_AXIS_TAGS:
        if t["id"] == tid:
            return dict(t)
    return None


def axes_from_tag_ids(tag_ids: Optional[Sequence[str]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for raw in tag_ids or []:
        t = _tag_by_id(str(raw))
        if not t or t["id"] in seen:
            continue
        seen.add(t["id"])
        out.append(t)
        if len(out) >= 3:
            break
    return out


def confirmed_direction_labels(char: Character, *, limit: int = 8) -> List[str]:
    return confirmed_axes(char, limit=limit)


def _card_signal(char: Character) -> bool:
    return bool(
        (char.voice or "").strip()
        or (char.bio or "").strip()
        or (char.relationships or "").strip()
        or (char.voiceCorpus or [])
        or (char.voiceMind or "").strip()
    )


def _scenario_by_id(
    scenario_id: str,
    scenario_label: str = "",
    *,
    scenario_prompt: str = "",
) -> Dict[str, Any]:
    sid = (scenario_id or "").strip()
    label_in = (scenario_label or "").strip()
    # custom:<name> or plain custom
    if sid == "custom" or sid.startswith("custom:"):
        from app.core.character_voice.corpus import normalize_scenario_key

        key = normalize_scenario_key(sid, label_in, prompt=scenario_prompt)
        name = key.split(":", 1)[1] if key.startswith("custom:") else (label_in or "未命名")
        return {
            "id": key,
            "label": name,
            "prompt": "",
            "longSuitable": True,
        }
    for s in SCENARIO_TEMPLATES:
        if s["id"] == sid:
            row = dict(s)
            if label_in and sid == "custom":
                row["label"] = label_in
            return row
    return {
        "id": sid or "custom",
        "label": label_in or sid or "自定义",
        "prompt": "",
        "longSuitable": False,
    }


_SPEAKER_ALIASES = {
    "self": "self",
    "me": "self",
    "character": "self",
    "角色": "self",
    "本角色": "self",
    "protagonist": "self",
    "other": "other",
    "对手": "other",
    "对方": "other",
    "npc": "other",
    "interviewer": "other",
    "采访": "other",
}


def _norm_speaker(raw: Any) -> str:
    key = str(raw or "self").strip().lower()
    # keep original CJK lookup
    raw_s = str(raw or "self").strip()
    if raw_s in _SPEAKER_ALIASES:
        return _SPEAKER_ALIASES[raw_s]
    if key in _SPEAKER_ALIASES:
        return _SPEAKER_ALIASES[key]
    return raw_s or "self"


def _line_text(ln: Dict[str, Any]) -> str:
    for k in ("text", "content", "line", "dialogue", "say"):
        v = ln.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _parse_script_string(raw: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(.+?)[:：]\s*(.+)$", line)
        if m:
            out.append({"speaker": _norm_speaker(m.group(1)), "text": m.group(2).strip()})
        else:
            out.append({"speaker": "self", "text": line})
    return out


def _extract_lines_payload(parsed: Dict[str, Any]) -> Any:
    for k in ("lines", "dialogue", "script", "turns", "transcript", "conversation"):
        if k in parsed and parsed[k] is not None:
            return parsed[k]
    # occasional nesting
    for nest in ("result", "data", "scene"):
        inner = parsed.get(nest)
        if isinstance(inner, dict):
            found = _extract_lines_payload(inner)
            if found is not None:
                return found
    return None


async def generate_voice_variants(
    cfg: DeepSeekConfig,
    project: VnProject,
    *,
    character_id: str,
    scenario_id: str = "",
    scenario_prompt: str = "",
    scenario_label: str = "",
    extra_constraints: str = "",
    axis_tags: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    char = find_character(project, character_id)
    sc = _scenario_by_id(
        scenario_id, scenario_label, scenario_prompt=scenario_prompt
    )
    prompt = (scenario_prompt or "").strip() or sc.get("prompt") or "日常对峙后的一两句回应。"
    if sc.get("id", "").startswith("custom") and not (scenario_prompt or "").strip():
        raise RuntimeError("自定义场景请填写「场景压力」后再生成")
    label = (scenario_label or "").strip() or sc.get("label") or scenario_id or "场景"

    pinned = axes_from_tag_ids(axis_tags)
    confirmed = confirmed_direction_labels(char)
    seed_axes, axes_rule = _build_axes_brief(char, pinned=pinned, confirmed=confirmed)

    corpus_bit = format_corpus_for_prompt(
        char,
        max_samples=6,
        max_chars=1100,
        scenario_id=sc.get("id") or scenario_id,
        scenario_label=label,
        scenario_prompt=prompt,
    )
    script_bit = format_script_anchors_for_prompt(project, character_id, limit=4, max_chars=700)
    system = (
        "你是视觉小说角色口吻设计师。任务：为同一压力场景生成三组**可感知差异**的对白变体，"
        "供作者挑选最像脑中角色的一组。\n"
        "硬规则：\n"
        "- 输出 JSON 对象，键 variants 为长度 3 的数组；另含 axes 数组（本轮三条差异轴）。\n"
        "- 每组含：axisId, axisLabel, hypothesis（一句本组人设假设）, lines（2～5 条）。\n"
        "- lines 每项：speaker（self=本角色，other=对手）, text（中文台词，像能演的 VN 对白）。\n"
        "- 三组必须分别对齐本轮三条差异轴，禁止只是同义改写。\n"
        "- 轴必须贴合该角色，禁止默认套用「冷短回避 / 热吐槽防护 / 软自嘲留白」除非角色卡确实如此。\n"
        "- 若有已确认方向，在其邻近气质空间拉开，而不是每轮重置成无关三极。\n"
        "- 优先对齐【偏好】与高权重正例（金句/剧本）；与【忌讳】冲突时服从忌讳。\n"
        "- 有【剧本锚点】时对齐用词习惯与人设，禁止照抄原文；情节服从当前场景压力。\n"
        "- 禁止设定说明书、禁止旁白讲解、禁止用括号写动作（可极短动作词嵌入台词内）。\n"
        "- 服从角色卡；若有已选正例，对齐其感觉但勿照抄。"
    )
    user = "\n".join(
        p
        for p in [
            f"角色：{char.displayName}（{char.defineName}）",
            f"语气摘要：{char.voice or '（空）'}",
            f"简介：{char.bio or '（空）'}",
            f"关系：{char.relationships or '（空）'}",
            corpus_bit,
            script_bit,
            f"场景标签：{label}",
            f"场景压力：{prompt}",
            f"额外约束：{extra_constraints.strip()}" if extra_constraints.strip() else "",
            f"已确认方向：{'、'.join(confirmed)}" if confirmed else "已确认方向：（尚无）",
            "本轮差异轴规则：",
            axes_rule,
            '返回形如：{"axes":[{"id":"...","label":"...","hint":"..."}],"variants":[{"axisId":"...","axisLabel":"...","hypothesis":"...","lines":[{"speaker":"other","text":"..."},{"speaker":"self","text":"..."}]}]}',
        ]
        if p
    )

    parsed, model_name = await _post_json_with_model(cfg, system=system, user=user, temperature=0.75)
    variants, used_axes = _parse_preference_variants(parsed, seed_axes=seed_axes)

    return {
        "scenarioId": sc.get("id") or scenario_id or "custom",
        "scenarioLabel": label,
        "scenarioPrompt": prompt,
        "axes": used_axes,
        "variants": variants[:3],
        "model": model_name,
        "characterId": character_id,
        "kind": "preference",
        "confirmedAxes": confirmed,
        "pinnedTags": [a["id"] for a in pinned],
    }


def _slug_axis_id(label: str, fallback: str = "axis") -> str:
    raw = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (label or "").strip(), flags=re.UNICODE)[:28]
    return raw.strip("_") or fallback


def _build_axes_brief(
    char: Character,
    *,
    pinned: List[Dict[str, str]],
    confirmed: List[str],
) -> tuple[List[Dict[str, str]], str]:
    """Return (seed_axes_for_fallback, instruction text for the model)."""
    if len(pinned) >= 3:
        axes = pinned[:3]
        desc = "\n".join(f"- {a['id']} / {a['label']}: {a['hint']}" for a in axes)
        return axes, f"必须严格使用以下三条轴（一一对应三组），勿改名：\n{desc}"

    if pinned:
        desc = "\n".join(f"- {a['id']} / {a['label']}: {a['hint']}" for a in pinned)
        need = 3 - len(pinned)
        return (
            list(pinned),
            f"必须包含以下用户指定轴，并再自拟 {need} 条**贴合此人**的互补轴，凑满互异的三条：\n{desc}\n"
            "自拟轴请给短 id（英文蛇形）与中文 label、hint。",
        )

    if not _card_signal(char):
        axes = [dict(a) for a in _FALLBACK_AXES]
        desc = "\n".join(f"- {a['id']} / {a['label']}: {a['hint']}" for a in axes)
        return axes, f"角色卡信号不足，使用冷启动兜底三轴（一一对应）：\n{desc}"

    converge = ""
    if confirmed:
        converge = (
            f"作者已确认更偏「{' / '.join(confirmed)}」。"
            "请在邻近气质空间再拉开三条可感知差异轴，勿重复完全相同的旧轴，也勿跳到完全无关的人格。"
        )
    tag_hint = "、".join(t["label"] for t in VOICE_AXIS_TAGS[:12]) + "…"
    return (
        [],
        "根据角色卡与正例，自拟本轮三条差异轴（贴合此人，禁止套用全局死轴）。"
        f"{converge}\n可参考标签气质（不必照搬）：{tag_hint}\n"
        "每条轴含 id（英文蛇形）、label（中文短名）、hint（一句）。",
    )


def _parse_axes_from_model(parsed: Dict[str, Any], seed_axes: List[Dict[str, str]]) -> List[Dict[str, str]]:
    raw = parsed.get("axes") if isinstance(parsed, dict) else None
    out: List[Dict[str, str]] = []
    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or row.get("axisLabel") or "").strip()
            aid = str(row.get("id") or row.get("axisId") or "").strip() or _slug_axis_id(label)
            hint = str(row.get("hint") or row.get("hypothesis") or "").strip()
            if not label and not aid:
                continue
            out.append({"id": aid, "label": label or aid, "hint": hint or label or aid})
            if len(out) >= 3:
                break
    if len(out) >= 3:
        return out[:3]
    # merge seed then pad
    seen = {a["id"] for a in out}
    for a in seed_axes:
        if a["id"] in seen:
            continue
        out.append(dict(a))
        seen.add(a["id"])
        if len(out) >= 3:
            break
    while len(out) < 3:
        fb = _FALLBACK_AXES[len(out) % len(_FALLBACK_AXES)]
        if fb["id"] in seen:
            out.append(
                {
                    "id": f"{fb['id']}_{len(out)}",
                    "label": fb["label"],
                    "hint": fb["hint"],
                }
            )
        else:
            out.append(dict(fb))
            seen.add(fb["id"])
    return out[:3]


def _parse_preference_variants(
    parsed: Dict[str, Any],
    *,
    seed_axes: List[Dict[str, str]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    axes = _parse_axes_from_model(parsed, seed_axes)
    raw_vars = parsed.get("variants") if isinstance(parsed, dict) else None
    if not isinstance(raw_vars, list):
        raise RuntimeError("缺少 variants")

    variants: List[Dict[str, Any]] = []
    for i, row in enumerate(raw_vars[:3]):
        if not isinstance(row, dict):
            continue
        axis = axes[i] if i < len(axes) else axes[-1]
        lines_in = row.get("lines") if isinstance(row.get("lines"), list) else []
        lines: List[Dict[str, str]] = []
        for ln in lines_in:
            if not isinstance(ln, dict):
                continue
            text = str(ln.get("text") or "").strip()
            if not text or _PLACEHOLDER_MARKER in text:
                continue
            speaker = str(ln.get("speaker") or "self").strip() or "self"
            lines.append({"speaker": speaker, "text": text})
        if not lines:
            continue
        label = str(row.get("axisLabel") or axis["label"]).strip() or axis["label"]
        aid = str(row.get("axisId") or axis["id"]).strip() or axis["id"]
        # keep axes list in sync with what variants actually claim
        axes[i] = {
            "id": aid,
            "label": label,
            "hint": axis.get("hint") or str(row.get("hypothesis") or "").strip(),
        }
        variants.append(
            {
                "axisId": aid,
                "axisLabel": label,
                "hypothesis": str(row.get("hypothesis") or "").strip(),
                "lines": lines,
            }
        )

    while len(variants) < 3:
        axis = axes[len(variants)] if len(variants) < len(axes) else _FALLBACK_AXES[0]
        variants.append(
            {
                "axisId": axis["id"],
                "axisLabel": axis["label"],
                "hypothesis": axis.get("hint") or axis["label"],
                # placeholder: model returned fewer than 3 — never accept this as a sample
                "placeholder": True,
                "lines": [],
            }
        )
    return variants[:3], axes[:3]


async def _post_json_with_model(
    cfg: DeepSeekConfig,
    *,
    system: str,
    user: str,
    temperature: float = 0.8,
) -> tuple[Dict[str, Any], str]:
    provider = provider_from_config(cfg)
    res = await provider.chat_completions(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
        timeout=120,
    )
    content, model_name = content_from_response(res)
    content = (content or "{}").strip()
    m = _FENCE_RE.search(content)
    if m:
        content = m.group(1).strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("模型未返回有效 JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("模型返回非对象 JSON")
    model_name = model_name or (cfg.model or DEFAULT_LLM_MODEL)
    parsed["_model"] = model_name
    return parsed, model_name


async def _post_json(cfg: DeepSeekConfig, *, system: str, user: str, temperature: float = 0.8) -> Dict[str, Any]:
    parsed, model_name = await _post_json_with_model(
        cfg, system=system, user=user, temperature=temperature
    )
    parsed["_model"] = model_name
    return parsed


def _parse_lines(raw: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if isinstance(raw, str):
        return _parse_script_string(raw)
    if not isinstance(raw, list):
        return out
    for ln in raw:
        if isinstance(ln, str):
            chunk = _parse_script_string(ln)
            out.extend(chunk)
            continue
        if not isinstance(ln, dict):
            continue
        text = _line_text(ln)
        if not text:
            continue
        speaker = _norm_speaker(ln.get("speaker") or ln.get("role") or ln.get("name") or "self")
        out.append({"speaker": speaker, "text": text})
    return out


async def generate_long_scene(
    cfg: DeepSeekConfig,
    project: VnProject,
    *,
    character_id: str,
    scenario_id: str = "",
    scenario_prompt: str = "",
    scenario_label: str = "",
    extra_constraints: str = "",
    turns: int = 10,
) -> Dict[str, Any]:
    char = find_character(project, character_id)
    sc = _scenario_by_id(
        scenario_id, scenario_label, scenario_prompt=scenario_prompt
    )
    prompt = (scenario_prompt or "").strip() or sc.get("prompt") or "一段有压力的对峙。"
    if sc.get("id", "").startswith("custom") and not prompt:
        raise RuntimeError("自定义场景请填写「场景压力」后再生成")
    label = (scenario_label or "").strip() or sc.get("label") or scenario_id or "长场次"
    turns = max(6, min(14, int(turns or 10)))
    corpus_bit = format_corpus_for_prompt(
        char,
        max_samples=6,
        max_chars=1200,
        scenario_id=sc.get("id") or scenario_id,
        scenario_label=label,
        scenario_prompt=prompt,
    )
    script_bit = format_script_anchors_for_prompt(project, character_id, limit=4, max_chars=700)
    mind = (char.voiceMind or "").strip()[:1600]
    system = (
        "你是视觉小说场次编剧。为指定角色写一段可演对白长场次，供作者审阅后整段入库。\n"
        "必须输出 JSON 对象，键名固定为 lines（数组）。\n"
        '形如：{"lines":[{"speaker":"other","text":"..."},{"speaker":"self","text":"..."},...]}\n'
        "speaker 仅用 self（本角色）或 other（对手）。\n"
        f"共约 {turns} 条台词（双方交替），本角色台词要充分体现人设与已有正例感觉。\n"
        "优先对齐【偏好】与高权重正例；有【剧本锚点】时对齐用词习惯，禁止照抄；情节服从场景压力。\n"
        "与【忌讳】冲突时服从忌讳。禁止设定说明书与旁白括号戏。不要用 markdown 代码围栏。"
    )
    user = "\n".join(
        p
        for p in [
            f"角色：{char.displayName}（{char.defineName}）",
            f"语气：{char.voice or ''}",
            f"简介：{char.bio or ''}",
            f"关系：{char.relationships or ''}",
            f"思维包摘要：\n{mind}" if mind else "",
            corpus_bit,
            script_bit,
            f"场景：{label}",
            f"压力：{prompt}",
            f"约束：{extra_constraints}" if extra_constraints.strip() else "",
        ]
        if p
    )
    parsed = await _post_json(cfg, system=system, user=user, temperature=0.75)
    lines = _parse_lines(_extract_lines_payload(parsed))
    if len(lines) < 4:
        preview = json.dumps(parsed, ensure_ascii=False)[:280]
        raise RuntimeError(f"长场次台词过少或格式不对，请重试。模型返回摘要：{preview}")
    return {
        "kind": "scene",
        "scenarioId": sc.get("id") or scenario_id or "custom",
        "scenarioLabel": f"长场次·{label}",
        "scenarioPrompt": prompt,
        "lines": lines,
        "model": parsed.get("_model"),
        "characterId": character_id,
    }


_INTERVIEW_TOPICS = [
    "你最怕别人发现你哪一点？",
    "对你在意的人，你会用什么方式靠近又收回？",
    "有一件你绝不会说出口的真心话是什么（用角色会说的方式绕开或点到）？",
    "被误解时，你宁可被怎么看也不愿被怎么看？",
    "疲惫到防线松动时，你会露出怎样的本音？",
    "如果必须拒绝亲近的人，你第一句会怎么挡？",
]


async def generate_interview_round(
    cfg: DeepSeekConfig,
    project: VnProject,
    *,
    character_id: str,
    question: str = "",
    extra_constraints: str = "",
    axis_tags: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    char = find_character(project, character_id)
    q = (question or "").strip() or _INTERVIEW_TOPICS[len(char.voiceCorpus or []) % len(_INTERVIEW_TOPICS)]
    pinned = axes_from_tag_ids(axis_tags)
    confirmed = confirmed_direction_labels(char)
    seed_axes, axes_rule = _build_axes_brief(char, pinned=pinned, confirmed=confirmed)
    corpus_bit = format_corpus_for_prompt(
        char,
        max_samples=5,
        max_chars=900,
        scenario_id="interview",
        scenario_label="扮演采访",
        scenario_prompt=q,
    )
    script_bit = format_script_anchors_for_prompt(project, character_id, limit=3, max_chars=500)
    system = (
        "你在做角色「扮演采访」。采访者已提问；请以该角色口吻给出三组差异化回答供作者挑选。\n"
        "输出 JSON：{ question, axes:[{id,label,hint}], variants:[{axisId,axisLabel,hypothesis,lines:[{speaker,text}]}] }。\n"
        "每组 lines 1～3 条，speaker 以 self 为主（可有 interviewer 作 other）。\n"
        "三组对齐本轮动态差异轴；优先对齐【偏好】与高权重正例；剧本锚点禁止照抄。"
        "禁止默认套用冷短/热吐槽/软自嘲除非人设如此。禁止说明书腔。"
    )
    user = "\n".join(
        p
        for p in [
            f"角色：{char.displayName}",
            f"语气：{char.voice or ''}",
            f"简介：{char.bio or ''}",
            corpus_bit,
            script_bit,
            f"采访问题：{q}",
            f"约束：{extra_constraints}" if extra_constraints.strip() else "",
            f"已确认方向：{'、'.join(confirmed)}" if confirmed else "",
            "本轮差异轴规则：",
            axes_rule,
        ]
        if p
    )
    parsed = await _post_json(cfg, system=system, user=user, temperature=0.75)
    # Normalize interview lines: accept text-only rows
    raw_vars = parsed.get("variants") if isinstance(parsed.get("variants"), list) else []
    normalized = dict(parsed)
    fixed_rows: List[Dict[str, Any]] = []
    for row in raw_vars[:3]:
        if not isinstance(row, dict):
            continue
        lines = _parse_lines(row.get("lines"))
        if not lines:
            text = str(row.get("text") or "").strip()
            if text:
                lines = [{"speaker": "self", "text": text}]
        if not lines:
            continue
        fixed_rows.append({**row, "lines": lines})
    normalized["variants"] = fixed_rows
    variants, used_axes = _parse_preference_variants(normalized, seed_axes=seed_axes)
    return {
        "kind": "interview",
        "question": str(parsed.get("question") or q),
        "scenarioId": "interview",
        "scenarioLabel": "扮演采访",
        "axes": used_axes,
        "variants": variants[:3],
        "model": parsed.get("_model"),
        "characterId": character_id,
        "confirmedAxes": confirmed,
        "pinnedTags": [a["id"] for a in pinned],
    }
