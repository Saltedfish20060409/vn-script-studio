"""标记批改：只改作者**标出来的那一处**，不做整章重写。

与 `chapter_revise`（整章回炉：诊断 → 全章重写）的分工：
标记批改是**局部、精准、可控**的——作者选中一段、标一句要求（也可以不写），
这里只把那一处改到符合要求，其余一字不动。所以提示词的核心是**约束范围**：
只输出这一段、保持与上下文衔接、不准顺手改别的地方。

同时注入项目已有的「文风记忆」（`styleMemory.guide`，由作者自己的文本提炼），
让改出来的东西贴作者自己的腔调，而不是模型的默认腔调。

失败一律降级为 error 字符串，不抛异常、不污染工程数据。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.core.ai import DeepSeekConfig
from app.core.llm_http import chat_completions, content_from_response

# 上下文与正文长度上限：控制成本，也避免"要改的这段"被稀释
_QUOTE_CAP = 1500
_CONTEXT_CAP = 220
_INSTRUCTION_CAP = 300
_STYLE_CAP = 600
# 改写结果长度上限：正常改写不该远超原文
_REPLACEMENT_RATIO = 3.0
_REPLACEMENT_MIN_SLACK = 200

_REWRITE_SYSTEM = """你是中文文学编辑。作者**只标出了一处**要改的地方，你只改这一处，其余一字不动。

铁律：
1. **只输出改写后的这一段文字本身**。不要解释、不要分析、不要前后对比、不要加引号或「改后：」这类标签、不要输出多行版本。
2. **保持与上下文衔接**：人称、时态、语气、专有名词（人名/地名/术语）必须与【上文】【下文】一致，不得新增或删改专名。
3. **不改变信息与情节**：可以调整措辞、节奏、句长、具体程度；不得新增事实、不得删掉关键信息。
4. **长度接近原文**（原则上不超过原文的 1.5 倍）。宁可精准，不要铺陈。
5. 作者给了要求就严格照要求改；没给要求时，默认目标是：**更具体、更少陈词滥调、与上下文语气更统一**。

只输出正文那一段。"""

_ADVICE_SYSTEM = """你是中文文学编辑。作者标出了一处**他觉得有问题**的地方，但此刻**不要改写正文**。

请给出简短判断与建议：
1. 先用一句话说清"这里的问题是什么"（例如：信息空转 / 形容词堆砌 / 视角越界 / 与上文人称不一致 / 重复）。
2. 再给 1–2 条**具体可执行**的改法（说改什么、往哪个方向改，不要直接写出改写稿）。
3. 总长不超过 160 字，不要客套、不要分点编号以外的格式、不要输出 JSON。

只输出建议本身。"""


@dataclass
class MarkReviseResult:
    replacement: str = ""
    advice: str = ""
    error: Optional[str] = None
    model: str = ""


def _clip(text: str, cap: int) -> str:
    value = (text or "").strip()
    return value[:cap]


def build_mark_messages(
    *,
    quote: str,
    prefix: str = "",
    suffix: str = "",
    instruction: str = "",
    intent: str = "rewrite",
    style_guide: str = "",
) -> List[Dict[str, str]]:
    """拼提示词。纯函数，便于测试（与真实调用分开）。"""
    system = _ADVICE_SYSTEM if intent == "advice" else _REWRITE_SYSTEM
    parts: List[str] = []
    if style_guide.strip():
        parts.append(f"【作者自己的文风（尽量贴合）】\n{_clip(style_guide, _STYLE_CAP)}")
    if prefix.strip():
        parts.append(f"【上文】\n…{_clip(prefix, _CONTEXT_CAP)}")
    parts.append(f"【要改的这一段】\n{_clip(quote, _QUOTE_CAP)}")
    if suffix.strip():
        parts.append(f"【下文】\n{_clip(suffix, _CONTEXT_CAP)}…")
    ask = _clip(instruction, _INSTRUCTION_CAP)
    parts.append(f"【作者的要求】\n{ask or '（没写具体要求，按默认目标：更具体、更少陈词滥调、语气与上下文统一）'}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_LABEL_RE = re.compile(r"^\s*(?:改后|改写后|修改后|建议)\s*[:：]\s*")


def clean_model_text(raw: str) -> str:
    """清掉模型爱加的包装：代码围栏、「改后：」标签、整段引号。"""
    text = (raw or "").strip()
    text = _FENCE_RE.sub("", text).strip()
    text = _LABEL_RE.sub("", text).strip()
    # 整段被引号/书名号包住时脱掉一层（只在首尾成对时）
    pairs = [("“", "”"), ("「", "」"), ('"', '"'), ("『", "』")]
    for left, right in pairs:
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            text = text[1:-1].strip()
    return text


async def revise_marked_text(
    config: Optional[DeepSeekConfig],
    *,
    quote: str,
    prefix: str = "",
    suffix: str = "",
    instruction: str = "",
    intent: str = "rewrite",
    style_guide: str = "",
) -> MarkReviseResult:
    """把标出来的这一处交给模型处理（改写或只给建议）。"""
    if config is None or not config.apiKey or "your-key" in config.apiKey:
        return MarkReviseResult(error="未配置模型密钥：请在「设置 → 模型」填入自己的 Key，或使用站内免费档。")
    if not quote.strip():
        return MarkReviseResult(error="标记内容为空")
    try:
        res = await chat_completions(
            config,
            messages=build_mark_messages(
                quote=quote,
                prefix=prefix,
                suffix=suffix,
                instruction=instruction,
                intent=intent,
                style_guide=style_guide,
            ),
            # 局部改写要贴原意，温度别高；建议类任务更保守
            temperature=0.4 if intent == "advice" else 0.55,
            timeout=120,
        )
        content, used_model = content_from_response(res)
        text = clean_model_text(content)
        if not text:
            return MarkReviseResult(error="模型没有返回内容，请重试或换一个模型")
        limit = int(len(quote) * _REPLACEMENT_RATIO) + _REPLACEMENT_MIN_SLACK
        text = text[:limit]
        result = MarkReviseResult(model=used_model or (config.model or ""))
        if intent == "advice":
            result.advice = text
        else:
            result.replacement = text
        return result
    except Exception as exc:  # noqa: BLE001 — 单处改写失败不该影响其它标记
        return MarkReviseResult(error=f"处理失败：{exc}")
