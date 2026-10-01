"""定点落实：作者要的是「只改点到的几处」，不是整章重写。

线上取证（2026-10，《拟合少女》）：「按建议改 / 其他地方不动」若落到
`replace_script` 或整章回炉，模型只能重打全文，逐字保留率可掉到约 5%。

本模块把「这是定点改」收成**一处判据**，供：
- `select_craft_mode`（关工艺，别怂恿顺手润色）
- `task_hint`（完成标准写成可检验的）
- agent 循环 / `apply_agent_actions`（硬拒 `replace_script`）

口径与前端 `agentIntent.ts` 的 `targetedReviseAsk` 对齐；两边各认一遍，
避免只修前端时后端仍灌全套工艺。
"""
from __future__ import annotations

import re

# 说了整章推翻 → 不是定点改（整章通道优先）
_FULL_REWRITE_RE = re.compile(
    r"(回炉|整章\s*(重写|改写)|全章\s*(重写|改写)|(重写|改写)\s*(一版|一遍|这一?章|当前章|整章|全章))"
)

_HARD_STOP_RE = re.compile(
    r"(先别改|先不要改|别改了|不要改了|不用改|不需要改|先别动笔|只要意见|只给意见)"
)

# 范围限制：「其他地方不动」/「只改…」
_LIMITED_SCOPE_RE = re.compile(
    r"(其他|其它|其余|别处|别的|剩下|剩余)[^。！？!?\n]{0,6}"
    r"(地方|部分|段落|章节|内容|情节)?[^。！？!?\n]{0,4}"
    r"(不动|不变|不改|不碰|别动|不要动|保持|照旧|保留|维持)"
    r"|(只|仅)[^。！？!?\n]{0,4}(改|动|修|调|润)"
    r"|(需要|要|该|必须|得)(修改|改|调整|润色)(的)(地方|部分|段落|句子|处)"
)

_CHANGES_TO_WRITE_RE = re.compile(
    r"(修改|改动|改好|改完|补丁)[^。！？!?\n]{0,6}(写入|写进|存进|放进|落到|落进|录进|应用)"
)

_TARGETED_COUNT_RE = re.compile(
    r"(几|两|三|四|五|六|七|八|九|十|[0-9]+)\s*个?\s*(处|句|行|条|点|地方)"
    r"|第\s*[0-9一二三四五六七八九十]+\s*个?\s*(处|句|行|条|点|地方)"
)

_REVISE_VERB_RE = re.compile(r"(改|修|润|重写|改写|回炉)")

# 「按建议改 / 落实意见」——不必再说「其他不动」也算定点落实
_APPLY_ADVICE_RE = re.compile(
    r"(按|照)(这些?|上述|上面|刚才|你的|以上)?(修改)?(建议|意见)"
    r"[^。！？!?\n]{0,10}(改|修|落实|写入|应用|执行)"
    r"|(落实|应用|执行)(这些?|上述|上面|你的|以上)?(修改)?(建议|意见)"
    r"|(把|将)(这些?|上述|上面|你的|以上)?(修改)?(建议|意见)"
    r"[^。！？!?\n]{0,10}(落实|改掉?|写入|应用|执行)"
    r"|(修改意见|这些建议|以上建议|上述建议|你的建议|你的意见)"
    r"[^。！？!?\n]{0,16}(同意|认可|采纳)[^。！？!?\n]{0,16}(改|修|落实)"
)

SURGICAL_REWRITE_HINT = (
    "本轮是**定点落实**（按建议 / 只改点到的几处）：\n"
    "- **唯一成功条件**：用 `patch_script`，每条 find 逐字照抄原文，只改建议点到的地方；"
    "未点名的句子一个字都不要动。\n"
    "- **禁止** `replace_script`（整章替换）——即使用了也会被服务端拒绝；"
    "「按建议改 / 落实意见 / 改完写入」都不算整章重写授权。\n"
    "- 不要顺手润色、不要按工艺清单「优化」未提及的句子；本轮工艺已关闭。\n"
    "- message 只列改了哪几处（对应建议序号即可），勿输出全文。"
)

_REPLACE_REJECT_NOTE = (
    "本轮是定点落实：`replace_script`（整章替换）已被拒绝。"
    "请改用 `patch_script`，find 逐字照抄原文，只改建议点到的几处；"
    "未点名的句子一字不动。不要再输出整章正文。"
)


def is_surgical_revise(message: str | None) -> bool:
    """作者要的是定点改（只动点到的几处），而不是整章回炉。"""
    text = (message or "").strip()
    if not text:
        return False
    if _HARD_STOP_RE.search(text):
        return False
    if _FULL_REWRITE_RE.search(text):
        return False
    if _APPLY_ADVICE_RE.search(text):
        return True
    if _CHANGES_TO_WRITE_RE.search(text):
        return True
    if _TARGETED_COUNT_RE.search(text) and _REVISE_VERB_RE.search(text):
        return True
    return bool(_LIMITED_SCOPE_RE.search(text) and _REVISE_VERB_RE.search(text))


def replace_script_reject_note() -> str:
    return _REPLACE_REJECT_NOTE
