"""Generate three differentiated dialogue variants for preference calibration."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

from app.core.ai import DeepSeekConfig
from app.core.character_voice.corpus import find_character, format_corpus_for_prompt
from app.domain.types import VnProject

SCENARIO_TEMPLATES: List[Dict[str, str]] = [
    {
        "id": "misunderstood",
        "label": "被误解时",
        "prompt": "对方误会了你的意图；你想澄清，但不愿显得在求饶或失控。",
    },
    {
        "id": "care_awkward",
        "label": "想关心却别扭",
        "prompt": "你其实在担心对方，但嘴上说不出口，只能用别扭的方式靠近。",
    },
    {
        "id": "authority",
        "label": "面对权威",
        "prompt": "老师/上司/前辈施压提问；你要守住边界，又不能无谓树敌。",
    },
    {
        "id": "romance_edge",
        "label": "对恋爱对象",
        "prompt": "气氛暧昧，对方试探真心；你既想回应又怕暴露软肋。",
    },
    {
        "id": "lie_edge",
        "label": "撒谎边缘",
        "prompt": "你必须隐瞒一件事；对方追问，你选择含糊、转移或半真半假。",
    },
    {
        "id": "tired_truth",
        "label": "疲惫本音",
        "prompt": "一天结束，防护掉了一点；对信任的人露出更本音的一两句。",
    },
    {
        "id": "refuse_request",
        "label": "拒绝请求",
        "prompt": "对方提出你办不到或不想办的事；你要拒绝，但留下关系余地。",
    },
    {
        "id": "praise_awkward",
        "label": "被当面夸奖",
        "prompt": "对方真诚夸你；你不习惯被看见优点，反应要符合人设。",
    },
    {
        "id": "custom",
        "label": "自定义…",
        "prompt": "",
    },
]

_AXES = [
    {
        "id": "cold_short",
        "label": "冷短回避",
        "hint": "更冷、短句、回避情绪词；信息密度低，留白多。",
    },
    {
        "id": "hot_banter",
        "label": "热吐槽防护",
        "hint": "更热、话稍多、用吐槽/抬杠作防护；情绪外露但有刺。",
    },
    {
        "id": "soft_selfdeprec",
        "label": "软自嘲留白",
        "hint": "更软、自我挖苦、收尾留白；不卖惨，但温度更高。",
    },
]

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def list_scenarios() -> List[Dict[str, str]]:
    return [dict(s) for s in SCENARIO_TEMPLATES]


def _scenario_by_id(scenario_id: str, scenario_label: str = "") -> Dict[str, str]:
    sid = (scenario_id or "").strip()
    label_in = (scenario_label or "").strip()
    # custom:<name> or plain custom
    if sid == "custom" or sid.startswith("custom:"):
        name = label_in or (sid.split(":", 1)[1].strip() if ":" in sid else "") or "自定义"
        return {"id": sid if sid.startswith("custom:") else f"custom:{name}", "label": name, "prompt": ""}
    for s in SCENARIO_TEMPLATES:
        if s["id"] == sid:
            if label_in and sid == "custom":
                return {**s, "label": label_in}
            return s
    return {
        "id": sid or "custom",
        "label": label_in or sid or "自定义",
        "prompt": "",
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
) -> Dict[str, Any]:
    char = find_character(project, character_id)
    sc = _scenario_by_id(scenario_id, scenario_label)
    prompt = (scenario_prompt or "").strip() or sc.get("prompt") or "日常对峙后的一两句回应。"
    if sc.get("id", "").startswith("custom") and not (scenario_prompt or "").strip():
        raise RuntimeError("自定义场景请填写「场景压力」后再生成")
    label = (scenario_label or "").strip() or sc.get("label") or scenario_id or "场景"

    corpus_bit = format_corpus_for_prompt(char, max_samples=5, max_chars=900)
    system = (
        "你是视觉小说角色口吻设计师。任务：为同一压力场景生成三组**可感知差异**的对白变体，"
        "供作者挑选最像脑中角色的一组。\n"
        "硬规则：\n"
        "- 输出 JSON 对象，键 variants 为长度 3 的数组。\n"
        "- 每组含：axisId, axisLabel, hypothesis（一句本组人设假设）, lines（2～5 条）。\n"
        "- lines 每项：speaker（self=本角色，other=对手）, text（中文台词，像能演的 VN 对白）。\n"
        "- 三组必须分别对齐给定的三条差异轴，禁止只是同义改写。\n"
        "- 禁止设定说明书、禁止旁白讲解、禁止用括号写动作（可极短动作词嵌入台词内）。\n"
        "- 服从角色卡；若有已选正例，对齐其感觉但勿照抄。"
    )
    axes_desc = "\n".join(f"- {a['id']} / {a['label']}: {a['hint']}" for a in _AXES)
    user = "\n".join(
        p
        for p in [
            f"角色：{char.displayName}（{char.defineName}）",
            f"语气摘要：{char.voice or '（空）'}",
            f"简介：{char.bio or '（空）'}",
            f"关系：{char.relationships or '（空）'}",
            corpus_bit,
            f"场景标签：{label}",
            f"场景压力：{prompt}",
            f"额外约束：{extra_constraints.strip()}" if extra_constraints.strip() else "",
            "差异轴（必须一一对应三组）：",
            axes_desc,
            '返回形如：{"variants":[{"axisId":"...","axisLabel":"...","hypothesis":"...","lines":[{"speaker":"other","text":"..."},{"speaker":"self","text":"..."}]}]}',
        ]
        if p
    )

    if not cfg.apiKey or "your-key" in cfg.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")
    base = (cfg.baseUrl or "https://api.deepseek.com").rstrip("/")
    model = cfg.model or "deepseek-chat"

    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.post(
            f"{base}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg.apiKey}",
            },
            json={
                "model": model,
                "temperature": 0.85,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
    if res.status_code >= 400:
        raise RuntimeError(f"DeepSeek API {res.status_code}: {res.text[:400]}")
    data = res.json()
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "{}"
    content = content.strip()
    m = _FENCE_RE.search(content)
    if m:
        content = m.group(1).strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("模型未返回有效 JSON") from exc

    raw_vars = parsed.get("variants") if isinstance(parsed, dict) else None
    if not isinstance(raw_vars, list):
        raise RuntimeError("缺少 variants")

    variants: List[Dict[str, Any]] = []
    for i, row in enumerate(raw_vars[:3]):
        if not isinstance(row, dict):
            continue
        axis = _AXES[i] if i < len(_AXES) else _AXES[-1]
        lines_in = row.get("lines") if isinstance(row.get("lines"), list) else []
        lines: List[Dict[str, str]] = []
        for ln in lines_in:
            if not isinstance(ln, dict):
                continue
            text = str(ln.get("text") or "").strip()
            if not text:
                continue
            speaker = str(ln.get("speaker") or "self").strip() or "self"
            lines.append({"speaker": speaker, "text": text})
        if not lines:
            continue
        variants.append(
            {
                "axisId": str(row.get("axisId") or axis["id"]),
                "axisLabel": str(row.get("axisLabel") or axis["label"]),
                "hypothesis": str(row.get("hypothesis") or "").strip(),
                "lines": lines,
            }
        )

    # Pad from axes if model returned fewer than 3
    while len(variants) < 3 and len(variants) < len(_AXES):
        axis = _AXES[len(variants)]
        variants.append(
            {
                "axisId": axis["id"],
                "axisLabel": axis["label"],
                "hypothesis": axis["hint"],
                "lines": [
                    {"speaker": "other", "text": "……你到底怎么想的？"},
                    {"speaker": "self", "text": "（请重新生成）"},
                ],
            }
        )

    return {
        "scenarioId": sc.get("id") or scenario_id or "custom",
        "scenarioLabel": label,
        "scenarioPrompt": prompt,
        "axes": _AXES,
        "variants": variants[:3],
        "model": data.get("model") or model,
        "characterId": character_id,
        "kind": "preference",
    }


def _chat_json(cfg: DeepSeekConfig, *, system: str, user: str, temperature: float = 0.8) -> Dict[str, Any]:
    if not cfg.apiKey or "your-key" in cfg.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")
    base = (cfg.baseUrl or "https://api.deepseek.com").rstrip("/")
    model = cfg.model or "deepseek-chat"
    return {
        "base": base,
        "model": model,
        "system": system,
        "user": user,
        "temperature": temperature,
    }


async def _post_json(cfg: DeepSeekConfig, *, system: str, user: str, temperature: float = 0.8) -> Dict[str, Any]:
    meta = _chat_json(cfg, system=system, user=user, temperature=temperature)
    async with httpx.AsyncClient(timeout=150) as client:
        res = await client.post(
            f"{meta['base']}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg.apiKey}",
            },
            json={
                "model": meta["model"],
                "temperature": temperature,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
    if res.status_code >= 400:
        raise RuntimeError(f"DeepSeek API {res.status_code}: {res.text[:400]}")
    data = res.json()
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "{}"
    content = content.strip()
    m = _FENCE_RE.search(content)
    if m:
        content = m.group(1).strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("模型未返回有效 JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("JSON 根须为对象")
    parsed["_model"] = data.get("model") or meta["model"]
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
    sc = _scenario_by_id(scenario_id, scenario_label)
    prompt = (scenario_prompt or "").strip() or sc.get("prompt") or "一段有压力的对峙。"
    if sc.get("id", "").startswith("custom") and not prompt:
        raise RuntimeError("自定义场景请填写「场景压力」后再生成")
    label = (scenario_label or "").strip() or sc.get("label") or scenario_id or "长场次"
    turns = max(6, min(14, int(turns or 10)))
    corpus_bit = format_corpus_for_prompt(char, max_samples=6, max_chars=1200)
    mind = (char.voiceMind or "").strip()[:1600]
    system = (
        "你是视觉小说场次编剧。为指定角色写一段可演对白长场次，供作者审阅后整段入库。\n"
        "必须输出 JSON 对象，键名固定为 lines（数组）。\n"
        '形如：{"lines":[{"speaker":"other","text":"..."},{"speaker":"self","text":"..."},...]}\n'
        "speaker 仅用 self（本角色）或 other（对手）。\n"
        f"共约 {turns} 条台词（双方交替），本角色台词要充分体现人设与已有正例感觉。\n"
        "禁止设定说明书与旁白括号戏。不要用 markdown 代码围栏。"
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
            f"场景：{label}",
            f"压力：{prompt}",
            f"约束：{extra_constraints}" if extra_constraints.strip() else "",
        ]
        if p
    )
    parsed = await _post_json(cfg, system=system, user=user, temperature=0.82)
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
) -> Dict[str, Any]:
    char = find_character(project, character_id)
    q = (question or "").strip() or _INTERVIEW_TOPICS[len(char.voiceCorpus or []) % len(_INTERVIEW_TOPICS)]
    corpus_bit = format_corpus_for_prompt(char, max_samples=5, max_chars=900)
    system = (
        "你在做角色「扮演采访」。采访者已提问；请以该角色口吻给出三组差异化回答供作者挑选。\n"
        "输出 JSON：{ question, variants:[{axisId,axisLabel,hypothesis,lines:[{speaker,text}]}] }。\n"
        "每组 lines 1～3 条，speaker 以 self 为主（可有 interviewer 作 other）。\n"
        "三组对齐：冷短回避 / 热吐槽防护 / 软自嘲留白。禁止说明书腔。"
    )
    axes_desc = "\n".join(f"- {a['id']} / {a['label']}: {a['hint']}" for a in _AXES)
    user = "\n".join(
        p
        for p in [
            f"角色：{char.displayName}",
            f"语气：{char.voice or ''}",
            f"简介：{char.bio or ''}",
            corpus_bit,
            f"采访问题：{q}",
            f"约束：{extra_constraints}" if extra_constraints.strip() else "",
            "差异轴：",
            axes_desc,
        ]
        if p
    )
    parsed = await _post_json(cfg, system=system, user=user, temperature=0.85)
    raw_vars = parsed.get("variants") if isinstance(parsed.get("variants"), list) else []
    variants: List[Dict[str, Any]] = []
    for i, row in enumerate(raw_vars[:3]):
        if not isinstance(row, dict):
            continue
        axis = _AXES[i] if i < len(_AXES) else _AXES[-1]
        lines = _parse_lines(row.get("lines"))
        if not lines:
            lines = [{"speaker": "self", "text": str(row.get("text") or "").strip()}]
            lines = [x for x in lines if x["text"]]
        if not lines:
            continue
        variants.append(
            {
                "axisId": str(row.get("axisId") or axis["id"]),
                "axisLabel": str(row.get("axisLabel") or axis["label"]),
                "hypothesis": str(row.get("hypothesis") or "").strip(),
                "lines": lines,
            }
        )
    while len(variants) < 3:
        axis = _AXES[len(variants)]
        variants.append(
            {
                "axisId": axis["id"],
                "axisLabel": axis["label"],
                "hypothesis": axis["hint"],
                "lines": [{"speaker": "self", "text": "……（请重新生成）"}],
            }
        )
    return {
        "kind": "interview",
        "question": str(parsed.get("question") or q),
        "scenarioId": "interview",
        "scenarioLabel": "扮演采访",
        "variants": variants[:3],
        "model": parsed.get("_model"),
        "characterId": character_id,
    }
