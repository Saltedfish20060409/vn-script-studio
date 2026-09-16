"""本地化的 AI 代翻：提示词构造、响应解析、合并（纯逻辑，不碰网络/DB）。

定位很重要：**AI 负责打草稿，人负责校对**。所以：
- 译文写入时状态标记为 `ai`（界面显示「AI 译·待校对」），与人工填写的 `translated` 区分；
- 默认**只翻还没翻的句子**，不覆盖人工译文；
- 术语表会整份喂给模型，并要求"必须使用给定译名"，保证人名/专有名词一致；
- 一次只处理有限的句子（按条数与字符数双重预算），失败不影响已有译文。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.core.localization import source_hash

# 一次请求最多带多少句 / 多少字符（控制 token 与超时）
#
# 50 / 4000 是实测出来的，不是拍的：对线上最长的一部（14016 句、平均 27 字/句）
# 用生产模型 glm-4-flash-250414 跑过 25/50/100 三档 ——
#   25 句 ≈ 639 字 → 1.9k token / 20s
#   50 句 ≈ 1196 字 → 3.5k token / 42s
#   100 句 ≈ 2671 字 → 7.4k token / 87s，且输出逼近 max_tokens=4000 的上限
# 100 句的收益不大而截断风险明显，所以取 50：请求数减半，输出仍留 2 倍余量，
# 单次耗时（~42s）也远低于前端 180s 的超时。
MAX_ENTRIES_PER_CALL = 50
MAX_CHARS_PER_CALL = 4000

SYSTEM_PROMPT = (
    "你是资深的视觉小说本地化译者。把中文游戏文本翻译成目标语言，要求：\n"
    "1. 口语自然、符合角色语感，不要逐字直译，也不要把中文语序原样搬过去；\n"
    "2. 保持原有标点风格与换行；台词里不要额外添加解释或旁白；\n"
    "3. 术语表里给出的译名必须原样使用；\n"
    "4. 只输出 JSON，不要任何解释、不要 markdown 代码块。\n"
    '格式：{"译文":[{"key":"条目标识","text":"译文"}]}，key 必须与输入完全一致。'
)


def select_batch(
    entries: List[Dict[str, Any]],
    *,
    only_untranslated: bool = True,
    locale: str = "",
    max_entries: int = MAX_ENTRIES_PER_CALL,
    max_chars: int = MAX_CHARS_PER_CALL,
) -> List[Dict[str, Any]]:
    """挑出这次要翻的条目（按剧本顺序，双重预算）。"""
    picked: List[Dict[str, Any]] = []
    used = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        source = str(e.get("source") or "").strip()
        if not source:
            continue
        if only_untranslated and str((e.get("targets") or {}).get(locale) or "").strip():
            continue
        if len(picked) >= max_entries or used + len(source) > max_chars:
            break
        picked.append(e)
        used += len(source)
    return picked


def build_user_prompt(
    batch: List[Dict[str, Any]],
    *,
    locale: str,
    locale_name: str,
    glossary: Optional[List[Dict[str, Any]]] = None,
) -> str:
    terms = []
    for g in glossary or []:
        if not isinstance(g, dict):
            continue
        term = str(g.get("term") or "").strip()
        target = str((g.get("targets") or {}).get(locale) or "").strip()
        if term and target:
            terms.append(f"- {term} → {target}")
    parts = [f"目标语言：{locale_name or locale}（代码 {locale}）"]
    if terms:
        parts.append("术语表（必须使用这些译名）：\n" + "\n".join(terms))
    payload = [
        {"key": str(e.get("key") or ""), "text": str(e.get("source") or "")}
        for e in batch
    ]
    parts.append(
        "请翻译下面这些条目，逐条给出译文（JSON）：\n"
        + json.dumps({"条目": payload}, ensure_ascii=False, indent=1)
    )
    return "\n\n".join(parts)


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

# 逐行兜底扫描。为什么需要它：实测 glm-4-flash 有两种"看着没问题但会整批丢"的输出——
#   A. 同一个 "译文" 键出现两次（`{"译文":[前16条],"译文":[后9条]}`）：JSON 允许重复键，
#      json.loads 只保留**最后一个**，于是 25 条里静默丢掉 16 条；
#   B. 译文里出现没转义的引号（`"text":"He said "stop""`）：整个 JSON 解析失败，一条不剩。
# 两种情况下正则都能把合格的行捞回来（键必须命中允许列表、译文必须是非空字符串，
# 所以捞回来的东西不会比严格解析"更脏"）。
_ROW_SCAN_RE = re.compile(
    r'(?:[{,]\s*)"key"\s*:\s*"(?P<key>(?:\\.|[^"\\])*)"'
    r'\s*,\s*"(?:text|translation)"\s*:\s*"(?P<text>.*?)"\s*[}\]]',
    re.DOTALL,
)

_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "b": "\b",
    "f": "\f",
    '"': '"',
    "\\": "\\",
    "/": "/",
    "'": "'",  # JSON 里非法，但模型很爱写 \' —— 不当成错误，当成单引号
}


def _unescape(value: str) -> str:
    """按 JSON 的转义规则还原字符串；对 `\\'` 这类非法转义保持宽容。"""
    if "\\" not in value:
        return value
    out: List[str] = []
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = value[i + 1]
        if nxt == "u" and i + 6 <= n:
            try:
                out.append(chr(int(value[i + 2 : i + 6], 16)))
                i += 6
                continue
            except ValueError:
                pass
        out.append(_ESCAPES.get(nxt, nxt))
        i += 2
    return "".join(out)


def _scan_rows(text: str, allowed: set) -> Dict[str, str]:
    """从原始输出里逐行捞 {key: 译文}（放宽 JSON 严格性，但不放宽取值范围）。"""
    out: Dict[str, str] = {}
    for m in _ROW_SCAN_RE.finditer(text or ""):
        key = _unescape(m.group("key")).strip()
        target = _unescape(m.group("text")).strip()
        if key in allowed and target and key not in out:
            out[key] = target
    return out



def _extract_json(text: str) -> Optional[Any]:
    """从模型输出里抠出 JSON（容忍代码块、前后解释文字）。"""
    raw = (text or "").strip()
    if not raw:
        return None
    fenced = _CODE_FENCE_RE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 退而求其次：取第一个 { 到最后一个 } 之间
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def parse_translation_response(text: str, allowed_keys: List[str]) -> Dict[str, str]:
    """解析模型输出为 {key: 译文}。

    只接受在允许列表里的 key（防止模型编造/串行），非字符串或空白译文直接丢弃。

    先走严格 JSON，再用逐行扫描兜底，**取命中更多的那份**：严格解析在
    "重复键"和"没转义的引号"两种输出上会整批或大半丢掉（见 _ROW_SCAN_RE 的注释），
    而扫描结果同样只来自允许列表，因此"取更多"不会引入更差的数据。
    """
    allowed = set(allowed_keys)
    strict = _parse_strict(text, allowed)
    scanned = _scan_rows(text, allowed)
    return scanned if len(scanned) > len(strict) else strict


def _parse_strict(text: str, allowed: set) -> Dict[str, str]:
    """按标准 JSON 结构解析（键必须完全对得上时才可用）。"""
    data = _extract_json(text)
    if data is None:
        return {}
    rows: List[Any] = []
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                rows.extend(value)
        if not rows and all(isinstance(v, str) for v in data.values()):
            # 形如 {"key": "译文"} 的扁平结构
            rows = [{"key": k, "text": v} for k, v in data.items()]
    elif isinstance(data, list):
        rows = data
    out: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        # 只收字符串：模型偶尔会吐数字/布尔/嵌套结构，str() 一兜就会把 "66"、
        # "True"、"['a']" 这种垃圾当成译文写进剧本（还会跟着导出到 .rpy）。
        raw_target = row.get("text")
        if not (isinstance(raw_target, str) and raw_target.strip()):
            alt = row.get("translation")
            if isinstance(alt, str) and alt.strip():
                raw_target = alt
        if not isinstance(raw_target, str):
            continue
        target = raw_target.strip()
        if key in allowed and target:
            out[key] = target
    return out


def apply_translations(
    entries: List[Dict[str, Any]],
    *,
    locale: str,
    mapping: Dict[str, str],
    overwrite: bool = False,
    status: str = "ai",
) -> Dict[str, Any]:
    """把译文合并进条目；返回新的条目列表与统计（不改动入参）。"""
    applied = 0
    skipped = 0
    unknown = 0
    known_keys = set()
    out: List[Dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        row = dict(e)
        key = str(row.get("key") or "")
        known_keys.add(key)
        target = (mapping or {}).get(key)
        row["targets"] = dict(row.get("targets") or {})
        row["status"] = dict(row.get("status") or {})
        existing = str(row["targets"].get(locale) or "").strip()
        if target:
            if existing and not overwrite:
                skipped += 1
            else:
                row["targets"][locale] = target
                row["status"][locale] = status
                applied += 1
        out.append(row)
    unknown = len([k for k in (mapping or {}) if k not in known_keys])
    return {"entries": out, "applied": applied, "skipped": skipped, "unknown": unknown}


def entry_source_hash(entry: Dict[str, Any]) -> str:
    return source_hash(str(entry.get("source") or ""))
