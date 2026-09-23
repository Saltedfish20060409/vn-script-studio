"""best-of-N 候选采样 + 确定性打分重排。

为什么需要这一层
----------------
现在的写作链路是「单次采样 → 确定性体检 → 改写一轮」：一次只产出一份稿子，作者不满意
只能重来。而模型采样是**随机**的——同一提示词跑三次，质量方差往往比两次改稿的差别还大。
best-of-N 把这份方差当资源：一次并发要 N 份，再用**确定性量具**排序取最优。仓里唯一
存在的多候选（``core/mark_revise.py`` 的 1–3 版）**没有 scorer，直接返回第一版**，
所以那 2–3 版的差异从来没被利用过。

三个关键取舍
------------
1. **温度梯形，而不是同温重复**。同温重复 N 次是在同一个分布里再抽 N 次，得到的往往是
   N 份"差不多的平庸"；把温度按 ``TEMPERATURE_STEP``（±0.08）铺开，低温那份偏保守、
   高温那份偏大胆，N 份之间才有**结构性差异**——有差异，排序才有意义。0.08 是经验值：
   小于 0.05 时两份常几乎逐字相同，大于 0.15 时高温档开始胡编。温度会被夹取到
   ``llm_params`` 的合法区间（0.2–1.0），**靠边时梯形会被夹平**，所以每份的**实际**
   温度都记在返回值里，而不是让调用方以为"一定有 N 个不同温度"。
2. **打分必须纯确定性、不调模型**。若用 LLM 当评委，就变成"N 次生成 + N 次评判"，
   成本再翻一倍，而且同一份稿子两次评分可能不同——作者无法复现"为什么这份被选中"，
   也没法在 CI 里给量具做回归。这里只用现成的确定性量具：硬体检（``harness.audit_full``）、
   节拍覆盖（``pipeline.beat_check``）、声线偏离（``core.voice_fingerprint``）、长度。
   它们抓不到语义质量（见"已知边界"），但**可复现、可解释、零额外成本**。
3. **失败隔离**。一个候选超时/被上游拒绝，不该拖垮另外两份：每个候选各自 try/except，
   失败只记 ``error``。全部失败时返回 ``{"error": ..., "candidates": []}`` 而不抛异常
   ——调用方（HTTP 路由 / Agent 工具）拿到的永远是可渲染的结构。

成本必须说清楚
--------------
best-of-N 的代价是**线性**的模型调用与 token：N=3 就是 3 倍。并发只能省等待时间，
**不省计费**。所以主入口 ``generate_best_candidates`` 在返回值里固定给出 ``cost``
（调用次数、倍数、一句提示），调用方应当据此决定是否开启、N 取多少；不要把它悄悄
挂在默认路径上。``MAX_CANDIDATES`` 也做了封顶，防止线上把 N 传成 50 造成 50 倍账单。

已知边界
--------
- 打分器答不出"这个故事好不好看"：反转是否成立、人物动机是否可信、笑点是否响，都是
  语义层的事，规则看不见。best-of-N 只保证"在 N 份里挑出**没有硬伤、贴节拍、最像本人**
  的那一份"，不保证那一份就是好稿子；它降低的是方差，不是上限。
- 声线分项依赖作者已经写过的台词（``voice_fingerprint`` 的画像），样本不足的角色直接
  跳过——宁可不给分，也不给一个算不出分布的分。
- 长度分项优先解析 instruction 里的"约 N 字"，解析不到就用经验区间；它不是"读者感受"，
  只是"过短几乎一定丢信息"的兜底。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from app.core import llm_budget
from app.core.ai import DeepSeekConfig
from app.core.harness.audit_full import full_audit_draft
from app.core.llm_http import chat_completions, content_from_response
from app.core.llm_params import clamp_temperature, task_temperature
from app.core.pipeline.beat_check import lint_beat_sheet
from app.core.voice_fingerprint import build_voice_profile, score_voice
from app.domain.types import VnProject

#: 可注入的补全器。签名与 ``llm_http.chat_completions`` 一致（config + 关键字参数），
#: 返回值可以是纯字符串（正文），也可以是 httpx.Response——两种都由本模块归一化。
Completer = Callable[..., Awaitable[Any]]

# ------------------------------------------------------------------ 采样常量

TEMPERATURE_STEP = 0.08
"""温度梯形的半格。见模块 docstring：<0.05 区分不出候选，>0.15 高温档开始跑飞。"""

DEFAULT_CANDIDATES = 3
"""默认 N：3 份足以看出结构性差异，成本还在"值得"的范围内（4 份以上边际收益明显变差）。"""

MAX_CANDIDATES = 6
"""N 的上限。为什么封顶：N 的代价是线性的，一次误传 N=50 就是 50 倍调用与账单。"""

SAMPLE_TIMEOUT = llm_budget.WRITE
"""单个候选的超时（秒）。best-of-N 里最慢的那份决定整体耗时，所以要卡住。"""

# ---------------------------------------------------------------- 打分权重表
#
# 每一项都是 0–1 的"罚分"，总分 = 1 − Σ(生效权重 × 该罚分)。
# 权重这样配的理由：
# - ``lintError`` 给满 1.00，而下面所有软项权重**加起来正好 1.00** —— 于是"只要有一个
#   error 级问题"，罚分就 ≥ 1，总分被压到 0。**硬错误的一票否决是靠权重本身实现的**，
#   不是排序时特判出来的，所以任何一处代码改动都不会悄悄把这条规则弄丢。
# - 软项之间按"读者多快能察觉"排：AI 味和节拍缺失是读者一眼就皱眉的（0.22），声线跑偏
#   要连读几章才觉出（0.18），长度是最表层的（0.18），warn 级零碎问题最多（0.20）。
SOFT_WEIGHTS: Dict[str, float] = {
    "lintWarn": 0.20,
    "beat": 0.22,
    "voice": 0.18,
    "aiFlavor": 0.22,
    "length": 0.18,
}

W_LINT_ERROR = 1.00
"""硬错误罚分权重。见上表注释：它等于软项权重之和，这是故意的。"""

WARN_SATURATION = 6.0
"""warn 数到这个量级就记满罚分：再多数几条不影响"这份稿子很脏"的判断。"""

BEAT_WARN_SATURATION = 4.0
FLAVOR_SATURATION = 4.0
"""AI 味/套话类 issue 到这个数就记满罚分（4 处已经很显眼了）。"""

#: 判"AI 味"的依据：ai_flavor 自己的检查（code 前缀 ai_）、宅味外壳，
#: 以及风格 Skill 的全部命中（禁用项/心理标签/作者总结/万能回应）。
_FLAVOR_SOURCES = {"style_skill"}
_FLAVOR_CODES = {"otaku_shell"}
_FLAVOR_CODE_PREFIX = "ai_"

# ------------------------------------------------------------------ 长度区间

DEFAULT_MIN_CHARS = 260
DEFAULT_MAX_CHARS = 2000
"""没有 instruction 提示时的经验区间：一个"场"通常在 300–1500 字之间。"""

INSTRUCTION_RATIO_LOW = 0.5
INSTRUCTION_RATIO_HIGH = 1.6
"""instruction 写了"约 800 字"时允许的浮动区间。"""

_RANGE_CHARS_RE = re.compile(r"(\d{2,5})\s*[-–—~～至到]\s*(\d{2,5})\s*字")
_SINGLE_CHARS_RE = re.compile(r"(\d{2,5})\s*字")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z0-9]+")

# ------------------------------------------------------------------ 提示词常量

SYSTEM_PROMPT = (
    "你是资深视觉小说编剧。按给定要求写**可直接上演**的一段正文："
    "对白与旁白交替、动作具体、信息靠行动与对白推进。"
    "不要解说、不要总结、不要输出标题或分析，只输出正文本身。"
)

INSTRUCTION_CAP = 800
BEAT_CAP = 1200
CONTEXT_CAP = 2000


def _clip(text: Any, cap: int) -> str:
    value = str(text or "").strip()
    if len(value) <= cap:
        return value
    return value[: cap - 1] + "…"


def _clean(text: Any) -> str:
    return str(text or "").strip()


def count_chars(text: str) -> int:
    """字数口径与 ``writing_stats`` / ``novel_memory`` 一致：中日文字逐个算，拉丁词算一个。

    为什么复刻而不是 import：core 不该反向依赖 services（services 里还挂着 sqlalchemy），
    而"面板字数"和"记忆字数"用的必须是同一个口径——两边一旦分叉，作者会觉得工具在胡说。
    """
    value = str(text or "")
    return len(_CJK_RE.findall(value)) + len(_LATIN_RE.findall(value))


# ------------------------------------------------------------------ 采样阶段


def _clamp_n(n: Any) -> int:
    """候选数归一化：非法值退回默认值，0 或负数返回 0（由调用方报错），并封顶。"""
    if n is None:
        return DEFAULT_CANDIDATES
    try:
        value = int(n)
    except (TypeError, ValueError):
        return DEFAULT_CANDIDATES
    if value <= 0:
        return 0
    return min(value, MAX_CANDIDATES)


def _config_usable(config: Optional[DeepSeekConfig]) -> bool:
    key = str(getattr(config, "apiKey", "") or "")
    return bool(key) and "your-key" not in key


def temperature_ladder(base: float, n: int) -> List[float]:
    """温度梯形：以 base 为中心向两侧各铺半格，再夹取到 llm_params 的合法区间。

    返回的是**实际**使用的温度（已夹取、已定序：从低到高），调用方与返回值里都用它。
    """
    if n <= 0:
        return []
    mid = (n - 1) / 2.0
    return [
        round(clamp_temperature(float(base) + (i - mid) * TEMPERATURE_STEP), 4)
        for i in range(n)
    ]


def build_candidate_messages(
    *,
    task: str,
    instruction: str,
    beat_sheet: Optional[Dict[str, Any]] = None,
    chapter_id: Optional[str] = None,
    selection: str = "",
    context_text: str = "",
) -> List[Dict[str, str]]:
    """拼一次候选生成的提示词（纯函数，可单独测试；N 份候选共用同一份提示词）。"""
    parts: List[str] = []
    if _clean(task):
        parts.append(f"## 任务\n{_clean(task)}")
    parts.append(
        "## 要求\n" + (_clip(instruction, INSTRUCTION_CAP) or "续写下一小段可上演内容。")
    )
    if chapter_id:
        parts.append(f"## 位置\n章 {chapter_id}")
    if beat_sheet:
        payload = json.dumps(beat_sheet, ensure_ascii=False)
        parts.append("## 节拍表（必须落实）\n" + _clip(payload, BEAT_CAP))
    if context_text.strip():
        parts.append("## 上文\n" + _clip(context_text, CONTEXT_CAP))
    if selection.strip():
        parts.append("## 选区\n" + _clip(selection, CONTEXT_CAP))
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _extract_text(raw: Any) -> Tuple[str, str]:
    """把 completer 的返回值归一化成 (正文, 模型名)。

    同时接受纯字符串与 httpx.Response：测试里注入的假 completer 直接返回字符串最省事，
    而默认路径返回的是真实响应——两种都走这一处，调用方不必分别处理。
    """
    if isinstance(raw, str):
        return raw.strip(), ""
    content, model = content_from_response(raw)
    return _clean(content), _clean(model)


async def _sample_one(
    config: Optional[DeepSeekConfig],
    *,
    messages: List[Dict[str, str]],
    temperature: float,
    completer: Optional[Completer],
    timeout: float,
) -> Dict[str, Any]:
    """取一个候选。**任何异常都在这里被吃掉**：一个候选失败不影响其它候选。"""
    try:
        if completer is not None:
            raw = await completer(
                config, messages=messages, temperature=temperature, timeout=timeout
            )
        else:
            raw = await chat_completions(
                config,
                messages=messages,
                temperature=temperature,
                timeout=timeout,
            )
        text, model = _extract_text(raw)
        if not text:
            return {"text": "", "model": model, "error": "模型返回空内容"}
        return {"text": text, "model": model, "error": None}
    except Exception as exc:  # noqa: BLE001 — 单个候选失败必须被隔离
        return {
            "text": "",
            "model": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _cost(n: int) -> Dict[str, Any]:
    """成本提示：best-of-N 是线性成本，必须让调用方看见，不能悄悄多花钱。"""
    return {
        "modelCalls": n,
        "multiplier": n,
        "note": (
            f"best-of-{n}：本次并发发出 {n} 次模型调用，token 与费用约为单次生成的 {n} 倍。"
            "并发只压缩等待时间，不减少计费——请只在值得挑稿的场景开启。"
        ),
    }


def _failure(
    message: str, *, n: int = 0, temperatures: Optional[List[float]] = None
) -> Dict[str, Any]:
    """统一失败信封：调用方永远拿得到 ``error`` 与空的 ``candidates``，不需要 try/except。"""
    return {
        "error": message,
        "candidates": [],
        "n": n,
        "succeeded": 0,
        "failed": n,
        "temperatures": list(temperatures or []),
        "cost": _cost(n),
    }


async def generate_candidates(
    config: Optional[DeepSeekConfig],
    project: VnProject,
    *,
    task: str,
    instruction: str,
    n: int = DEFAULT_CANDIDATES,
    beat_sheet: Optional[Dict[str, Any]] = None,
    base_temperature: Optional[float] = None,
    completer: Optional[Completer] = None,
    chapter_id: Optional[str] = None,
    selection: str = "",
    context_text: str = "",
) -> Dict[str, Any]:
    """并发采样 N 份候选（温度梯形），只负责**生成**，不打分（打分见 ``score_candidate``）。

    ``completer`` 为 None 时走真实的 ``chat_completions``；测试一律注入假 completer，
    因此本模块的单元测试**不会产生任何网络请求**。``project`` 只用于拼提示词与后续打分。
    """
    want = _clamp_n(n)
    if want <= 0:
        return _failure("候选数量必须是 1 以上的整数", n=0)
    if completer is None and not _config_usable(config):
        return _failure("未配置模型密钥：请在「设置 → 模型」填入 Key，或注入 completer", n=want)

    base = clamp_temperature(
        float(base_temperature) if base_temperature is not None else task_temperature(task)
    )
    temperatures = temperature_ladder(base, want)
    messages = build_candidate_messages(
        task=task,
        instruction=instruction,
        beat_sheet=beat_sheet,
        chapter_id=chapter_id,
        selection=selection,
        context_text=context_text,
    )
    results = await asyncio.gather(
        *(
            _sample_one(
                config,
                messages=messages,
                temperature=temp,
                completer=completer,
                timeout=SAMPLE_TIMEOUT,
            )
            for temp in temperatures
        )
    )

    candidates: List[Dict[str, Any]] = []
    for index, (temp, row) in enumerate(zip(temperatures, results), start=1):
        candidates.append(
            {
                "index": index,
                "temperature": temp,
                "text": row.get("text") or "",
                "chars": count_chars(row.get("text") or ""),
                "model": row.get("model") or "",
                "error": row.get("error"),
            }
        )

    failures = [c for c in candidates if c.get("error")]
    if len(failures) == len(candidates):
        reasons = "；".join(f"#{c['index']} {c['error']}" for c in failures)
        return {
            **_failure(f"全部候选生成失败：{reasons}", n=want, temperatures=temperatures),
            "candidates": candidates,
        }

    return {
        "task": task,
        "n": want,
        "succeeded": len(candidates) - len(failures),
        "failed": len(failures),
        "baseTemperature": round(base, 4),
        "temperatures": temperatures,
        "candidates": candidates,
        "cost": _cost(want),
    }


# ------------------------------------------------------------------ 打分阶段


def _flavor_issues(issues: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从体检 issues 里挑出"AI 味/套话"那几类（按 source 与 code 归类）。"""
    out: List[Dict[str, Any]] = []
    for issue in issues:
        code = str(issue.get("code") or "")
        source = str(issue.get("source") or "")
        if (
            source in _FLAVOR_SOURCES
            or code in _FLAVOR_CODES
            or code.startswith(_FLAVOR_CODE_PREFIX)
        ):
            out.append(
                {
                    "code": code,
                    "severity": str(issue.get("severity") or ""),
                    "source": source,
                    "message": _clip(issue.get("message"), 80),
                }
            )
    return out


def _beat_total(beat_sheet: Dict[str, Any]) -> int:
    """节拍表里"有效节拍"的条数。

    与 ``beat_check.lint_beat_sheet`` 的计数规则保持一致（有 name 或 action 就计一条），
    这样"覆盖 x/y"里的 y 与体检报出的 beat_missing 条数能对上账。
    """
    total = 0
    beats = beat_sheet.get("beats") or []
    if not isinstance(beats, list):
        return 0
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        if str(beat.get("name") or "").strip() or str(beat.get("action") or "").strip():
            total += 1
    return total


def _beat_term(text: str, beat_sheet: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """节拍覆盖分项。没有 beat_sheet 时 ``checked=False``、``penalty=None``（不参与总分）。"""
    if not beat_sheet or not isinstance(beat_sheet, dict):
        return {
            "checked": False,
            "penalty": None,
            "total": 0,
            "covered": 0,
            "ratio": None,
            "issueCount": 0,
            "errorCount": 0,
            "warnCount": 0,
            "codes": [],
        }
    issues = lint_beat_sheet(text, beat_sheet)
    total = _beat_total(beat_sheet)
    codes = [i.code for i in issues]
    if not text.strip() and total:
        # 空稿：lint_beat_sheet 会直接返回 beats_empty_draft，不给 beat_missing，
        # 照着 complement 算会得出"覆盖 100%"的荒谬结论——这里显式归零。
        covered, ratio = 0, 0.0
    else:
        missing = sum(1 for code in codes if code == "beat_missing")
        covered = max(0, total - missing)
        ratio = (covered / total) if total else 1.0
    error_count = sum(1 for i in issues if i.severity == "error")
    warn_count = sum(1 for i in issues if i.severity == "warn")
    penalty = max(1.0 - ratio, min(1.0, warn_count / BEAT_WARN_SATURATION))
    return {
        "checked": True,
        "penalty": round(penalty, 4),
        "total": total,
        "covered": covered,
        "ratio": round(ratio, 4),
        "issueCount": len(issues),
        "errorCount": error_count,
        "warnCount": warn_count,
        "codes": codes,
    }


def _name_terms(char: Any) -> List[str]:
    values = [
        getattr(char, "displayName", ""),
        getattr(char, "defineName", ""),
        *(getattr(char, "aliases", None) or []),
    ]
    return [v for v in (str(x or "").strip() for x in values) if v]


def _display_name(project: VnProject, character_id: str) -> str:
    for char in getattr(project, "characters", None) or []:
        if str(getattr(char, "id", "")) == str(character_id):
            return str(getattr(char, "displayName", "") or character_id)
    return str(character_id)


def _line_patterns(term: str) -> List[re.Pattern[str]]:
    esc = re.escape(term)
    return [
        re.compile(rf"^{esc}\s*[:：]\s*(.+)$"),
        re.compile(rf"^{esc}\s+[\"“「『](.+?)[\"”」』]\s*$"),
    ]


def _lines_for(char: Any, draft: str) -> List[str]:
    """从草稿里切出某个角色的台词行。

    只认剧本里真实存在的两种写法：``名字：台词`` 与 ``名字 "台词"``（Ren'Py 风格）。
    切不出台词的角色会被跳过——**不能**拿旁白去比声线，那是另一种文本。
    """
    # 先在整篇里做一次 C 速的子串预筛：50 个角色 × 5000 行逐行正则太慢，
    # 而名字根本不在草稿里的角色连正则都不用建。
    terms = [t for t in _name_terms(char) if len(t) >= 2 and t in draft]
    if not terms:
        return []
    grouped = [_line_patterns(t) for t in terms]
    out: List[str] = []
    for raw in (draft or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        for patterns in grouped:
            hit = ""
            for pattern in patterns:
                match = pattern.match(line)
                if match:
                    hit = match.group(1).strip()
                    break
            if hit:
                out.append(hit)
                break
    return out


def _voice_term(
    project: VnProject,
    draft: str,
    profile_cache: Optional[Dict[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    """声线分项：草稿里出现的每个角色各算一次 drift，取**最差**的一个。

    为什么取最差而不是平均：一份稿子里只要有一个角色"不像本人"，这份稿子就不该被选中；
    平均会把一个跑偏的角色藏在一堆正常角色后面。
    """
    if not draft.strip():
        return {"checked": False, "penalty": None, "worst": None, "worstName": None, "rows": []}

    rows: List[Dict[str, Any]] = []
    for char in getattr(project, "characters", None) or []:
        lines = _lines_for(char, draft)
        if not lines:
            continue
        cid = str(getattr(char, "id", "") or "")
        name = str(getattr(char, "displayName", "") or cid)
        profile = profile_cache.get(cid) if profile_cache is not None else None
        if profile is None:
            profile = build_voice_profile(project, cid)
            if profile_cache is not None:
                profile_cache[cid] = profile
        if not profile.get("ready"):
            rows.append(
                {
                    "characterId": cid,
                    "name": name,
                    "ready": False,
                    "utteranceCount": len(lines),
                    "reason": "画像样本不足，跳过（宁可不算，也不给错分）",
                }
            )
            continue
        result = score_voice(profile, lines)
        if not result.get("ready"):
            rows.append(
                {
                    "characterId": cid,
                    "name": name,
                    "ready": False,
                    "utteranceCount": len(lines),
                    "reason": str(result.get("reason") or "无法评估"),
                }
            )
            continue
        rows.append(
            {
                "characterId": cid,
                "name": name,
                "ready": True,
                "utteranceCount": len(lines),
                "drift": round(float(result.get("drift") or 0.0), 4),
                "level": str(result.get("level") or ""),
                "reasons": list(result.get("reasons") or [])[:2],
            }
        )

    scored = [r for r in rows if r.get("ready")]
    if not scored:
        return {
            "checked": False,
            "penalty": None,
            "worst": None,
            "worstName": None,
            "rows": rows,
            "note": "没有可评估的角色（草稿里没有可切出的台词，或画像样本不足）",
        }
    worst = max(scored, key=lambda r: float(r["drift"]))
    return {
        "checked": True,
        "penalty": round(min(1.0, max(0.0, float(worst["drift"]))), 4),
        "worst": float(worst["drift"]),
        "worstName": worst["name"],
        "worstLevel": worst["level"],
        "rows": rows,
        "note": "取出场角色里偏离最大的一个：一个角色不像本人，整份候选就该降权",
    }


def _length_band(instruction: str) -> Tuple[int, int, str]:
    """长度区间：优先读 instruction 里的"约 N 字"/"N–M 字"，否则用默认经验区间。"""
    text = str(instruction or "")
    match = _RANGE_CHARS_RE.search(text)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            low, high = high, low
        return low, high, "instruction(区间)"
    match = _SINGLE_CHARS_RE.search(text)
    if match:
        target = int(match.group(1))
        return (
            max(1, int(target * INSTRUCTION_RATIO_LOW)),
            int(target * INSTRUCTION_RATIO_HIGH),
            "instruction(约数)",
        )
    return DEFAULT_MIN_CHARS, DEFAULT_MAX_CHARS, "default"


def _length_penalty(chars: int, low: int, high: int) -> float:
    """长度罚分：区间内 0；过短线性扣到 1（0 字时满罚）；过长比过短宽容一半。"""
    if chars <= 0:
        return 1.0
    if low <= chars <= high:
        return 0.0
    if chars < low:
        return max(0.0, 1.0 - chars / float(low))
    over = (chars - high) / float(max(1, high))
    return min(1.0, over * 0.5)


def _length_term(text: str, instruction: str) -> Dict[str, Any]:
    chars = count_chars(text)
    low, high, source = _length_band(instruction)
    ok = low <= chars <= high
    verdict = "合适" if ok else ("偏短" if chars < low else "偏长")
    return {
        "chars": chars,
        "min": low,
        "max": high,
        "ok": ok,
        "verdict": verdict,
        "source": source,
        "penalty": round(_length_penalty(chars, low, high), 4),
    }


def _weighted_score(
    penalties: Dict[str, Optional[float]],
) -> Tuple[float, Dict[str, float]]:
    """把各分项罚分加权成 0–1 总分。

    缺席的分项（例如没有 beat_sheet 时的节拍项）**不参与**，权重在剩下的项之间重新
    归一化——否则"没给节拍表"会平白变成 0.22 的免费加分。
    """
    active = {k: w for k, w in SOFT_WEIGHTS.items() if penalties.get(k) is not None}
    total_w = sum(active.values())
    if total_w <= 0:
        return 1.0, {}
    weights = {k: round(w / total_w, 4) for k, w in active.items()}
    penalty = sum(weights[k] * float(penalties[k]) for k in active)
    return max(0.0, min(1.0, 1.0 - penalty)), weights


def _build_notes(
    *,
    empty: bool,
    hard: int,
    lint_error: int,
    lint_warn: int,
    beat: Dict[str, Any],
    voice: Dict[str, Any],
    flavor_count: int,
    length: Dict[str, Any],
) -> List[str]:
    notes: List[str] = []
    if empty:
        notes.append("正文为空：按硬错误处理（空稿不该赢），总分 0")
    elif hard:
        notes.append(f"硬错误 {hard} 处：总分被压到 0（一票否决）")
    else:
        notes.append("没有 error 级问题")
    if lint_error:
        notes.append(f"体检 error {lint_error} 处")
    if lint_warn:
        notes.append(f"体检 warn {lint_warn} 处（罚分 {min(1.0, lint_warn / WARN_SATURATION):.2f}）")
    if beat.get("checked"):
        notes.append(f"节拍覆盖 {beat['covered']}/{beat['total']}（issue {beat['issueCount']} 条）")
    if voice.get("checked"):
        notes.append(f"声线偏离最差 {voice['worst']:.2f}（{voice['worstName']}）")
    elif voice.get("rows"):
        notes.append("声线未参与：出场角色画像样本不足")
    notes.append(f"AI 味/套话 {flavor_count} 处")
    notes.append(f"长度 {length['chars']} 字（{length['verdict']}，区间 {length['min']}–{length['max']}）")
    return notes


def score_candidate(
    draft: str,
    project: VnProject,
    *,
    beat_sheet: Optional[Dict[str, Any]] = None,
    instruction: str = "",
    profile_cache: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """给一份候选打分。**纯确定性、不调模型**：同一输入必得同一分数，可进 CI 做回归。

    ``instruction`` 用于长度区间判断（可选）；``profile_cache`` 是角色声线画像的缓存
    （画像只取决于项目、与候选无关，best-of-N 的 N 份之间可以复用，省下 N 倍画像构建）。
    """
    text = _clean(draft)
    audit = full_audit_draft(text)
    issues = [i for i in (audit.get("issues") or []) if isinstance(i, dict)]
    lint_error = int(audit.get("errorCount") or 0)
    lint_warn = int(audit.get("warnCount") or 0)
    empty = not text
    lint_pass = bool(audit.get("pass")) and not empty

    flavor = _flavor_issues(issues)
    beat = _beat_term(text, beat_sheet)
    voice = _voice_term(project, text, profile_cache)
    length = _length_term(text, instruction)

    hard = lint_error + int(beat.get("errorCount") or 0) + (1 if empty else 0)
    penalties: Dict[str, Optional[float]] = {
        "lintWarn": min(1.0, lint_warn / WARN_SATURATION),
        "beat": beat.get("penalty"),
        "voice": voice.get("penalty"),
        "aiFlavor": min(1.0, len(flavor) / FLAVOR_SATURATION),
        "length": length["penalty"],
    }
    score, weights = _weighted_score(penalties)
    if hard > 0:
        # 一票否决：硬错误意味着"这段不能要"，再多优点也不该翻盘。
        score = 0.0

    return {
        "score": round(score, 4),
        "hardErrorCount": hard,
        "empty": empty,
        "lintError": lint_error,
        "lintWarn": lint_warn,
        "lintPass": lint_pass,
        "lintInfoCount": int(audit.get("infoCount") or 0),
        "beatCoverage": beat,
        "voiceDrift": voice,
        "aiFlavor": {
            "count": len(flavor),
            "codes": [f["code"] for f in flavor],
            "issues": flavor,
        },
        "lengthOk": length,
        "penalties": {
            k: (None if v is None else round(float(v), 4)) for k, v in penalties.items()
        },
        "weights": weights,
        "definedWeights": dict(SOFT_WEIGHTS),
        "hardErrorWeight": W_LINT_ERROR,
        "notes": _build_notes(
            empty=empty,
            hard=hard,
            lint_error=lint_error,
            lint_warn=lint_warn,
            beat=beat,
            voice=voice,
            flavor_count=len(flavor),
            length=length,
        ),
    }


def _reason_for(row: Dict[str, Any], fallback_index: int) -> str:
    """给作者看的一句中文理由：必须点出**具体依据**，不能只说"分数更高"。"""
    evidence = row.get("evidence")
    if not isinstance(evidence, dict):
        evidence = row
    index = row.get("index") or fallback_index
    score = float(row.get("score") or 0.0)
    bits: List[str] = []

    lint_error = int(evidence.get("lintError") or 0)
    beat = evidence.get("beatCoverage") or {}
    beat_error = int(beat.get("errorCount") or 0) if isinstance(beat, dict) else 0
    if evidence.get("empty"):
        bits.append("正文为空")
    elif lint_error:
        bits.append(f"有 {lint_error} 处 error 级问题")
    elif beat_error:
        bits.append(f"节拍有 {beat_error} 处 error")
    else:
        bits.append("没有 error 级问题")

    if isinstance(beat, dict) and beat.get("checked"):
        bits.append(f"节拍覆盖 {beat.get('covered')}/{beat.get('total')}")

    voice = evidence.get("voiceDrift") or {}
    if isinstance(voice, dict) and voice.get("checked"):
        bits.append(f"声线偏离 {float(voice.get('worst') or 0.0):.2f}（{voice.get('worstName')}）")

    flavor = evidence.get("aiFlavor") or {}
    if isinstance(flavor, dict):
        bits.append(f"AI 味 {int(flavor.get('count') or 0)} 项")

    length = evidence.get("lengthOk") or {}
    if isinstance(length, dict) and length:
        bits.append(f"长度 {length.get('chars')} 字（{length.get('verdict')}）")

    return f"第 {index} 份：" + "、".join(bits) + f"，总分 {score:.2f}"


def _why_not(winner: Dict[str, Any], row: Dict[str, Any]) -> str:
    win_hard = int(winner.get("hardErrorCount") or 0)
    row_hard = int(row.get("hardErrorCount") or 0)
    win_score = float(winner.get("score") or 0.0)
    row_score = float(row.get("score") or 0.0)
    if row_hard > win_hard:
        return f"有 {row_hard} 处硬错误，被一票否决"
    if row_score < win_score - 1e-9:
        return f"总分低 {win_score - row_score:.3f}"
    return "与被选中的一份同分，按候选顺序取更早的一份"


def rank_candidates(scored: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """给候选排序并选出 winner。

    排序键是 ``(硬错误数, 总分降序, 原顺序)``：硬错误数放第一位不是多余的——总分里
    硬错误已经把分数压到 0，但"两份都是 0 分"时仍要按错误多少分高下，否则作者会看到
    一个有很多 error 的稿子跟只有一个 error 的稿子并列。
    """
    rows = [r for r in (scored or []) if isinstance(r, dict)]
    if not rows:
        return {
            "ranked": [],
            "winner": None,
            "reason": "没有可比较的候选：全部生成失败，或没有提供打分结果。",
        }

    order = sorted(
        range(len(rows)),
        key=lambda i: (
            int(rows[i].get("hardErrorCount") or 0),
            -float(rows[i].get("score") or 0.0),
            i,
        ),
    )
    ranked: List[Dict[str, Any]] = []
    for position, i in enumerate(order, start=1):
        row = dict(rows[i])
        row["rank"] = position
        row["reason"] = _reason_for(row, i + 1)
        ranked.append(row)

    winner = ranked[0]
    for row in ranked[1:]:
        row["whyNotWinner"] = _why_not(winner, row)
    return {"ranked": ranked, "winner": winner, "reason": winner["reason"]}


async def generate_best_candidates(
    config: Optional[DeepSeekConfig],
    project: VnProject,
    *,
    task: str,
    instruction: str,
    n: int = DEFAULT_CANDIDATES,
    beat_sheet: Optional[Dict[str, Any]] = None,
    base_temperature: Optional[float] = None,
    completer: Optional[Completer] = None,
    chapter_id: Optional[str] = None,
    selection: str = "",
    context_text: str = "",
) -> Dict[str, Any]:
    """采样 + 打分 + 排序：返回每份的分数与理由、winner，以及**成本提示**。

    成本：本函数会发出 N 次模型调用（``cost.modelCalls``）。打分本身不花钱（纯本地）。
    """
    sampled = await generate_candidates(
        config,
        project,
        task=task,
        instruction=instruction,
        n=n,
        beat_sheet=beat_sheet,
        base_temperature=base_temperature,
        completer=completer,
        chapter_id=chapter_id,
        selection=selection,
        context_text=context_text,
    )
    want = int(sampled.get("n") or 0)
    cost = sampled.get("cost") or _cost(want)
    if sampled.get("error") and not any(
        not c.get("error") for c in (sampled.get("candidates") or [])
    ):
        return {
            "error": sampled["error"],
            "candidates": [],
            "n": want,
            "succeeded": 0,
            "failed": int(sampled.get("failed") or 0),
            "temperatures": sampled.get("temperatures") or [],
            "cost": cost,
        }

    # 画像只取决于项目，与候选无关 —— 在这里建一次缓存，N 份候选共用。
    profile_cache: Dict[str, Dict[str, Any]] = {}
    scored: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for candidate in sampled.get("candidates") or []:
        if candidate.get("error"):
            failures.append(
                {
                    "index": candidate.get("index"),
                    "temperature": candidate.get("temperature"),
                    "error": candidate.get("error"),
                }
            )
            continue
        evidence = score_candidate(
            candidate.get("text") or "",
            project,
            beat_sheet=beat_sheet,
            instruction=instruction,
            profile_cache=profile_cache,
        )
        scored.append(
            {
                "index": candidate.get("index"),
                "temperature": candidate.get("temperature"),
                "chars": candidate.get("chars"),
                "model": candidate.get("model"),
                "text": candidate.get("text") or "",
                "score": evidence["score"],
                "hardErrorCount": evidence["hardErrorCount"],
                "evidence": evidence,
            }
        )

    if not scored:
        return {
            "error": sampled.get("error") or "全部候选生成失败，没有可打分的候选",
            "candidates": [],
            "n": want,
            "succeeded": 0,
            "failed": len(failures),
            "failures": failures,
            "temperatures": sampled.get("temperatures") or [],
            "cost": cost,
        }

    ranking = rank_candidates(scored)
    ranked = ranking["ranked"]
    return {
        "task": task,
        "n": want,
        "succeeded": len(scored),
        "failed": len(failures),
        "failures": failures,
        "baseTemperature": sampled.get("baseTemperature"),
        "temperatures": sampled.get("temperatures") or [],
        "candidates": ranked,
        "ranked": ranked,
        "winner": ranking["winner"],
        "reason": ranking["reason"],
        "cost": cost,
        "scoring": {
            "deterministic": True,
            "note": "打分全在本地做（体检 + 节拍 + 声线 + 长度），不额外调用模型，可复现",
            "weights": dict(SOFT_WEIGHTS),
            "hardErrorWeight": W_LINT_ERROR,
        },
    }
