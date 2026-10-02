"""风格迁移（style_transfer）写路径契约（ADR 0001 P2.5 / P5 产品化）。

P4 只暴露 continue / rewrite；本文件先钉**提示词契约**，供 P2.5 基线夹具与
后续 P5 `write_op=style_transfer` 共用，避免前后端各写一套。

优先级（与导师/透镜一致）：style_guide（StyleSkill）> mentor > lens > 本轮风格指令。

验收（P5，**非**余弦相似度门禁）：
- 盲测：读迁移前后各一段，能指出句式节奏 / 用词温度 / 对白口吻差异；情节事实不变
- 契约层：prompt 明确要求「可识别的差异幅度」+ 禁止情节漂移
- 不做「输出与原文相似度 < X」数值闸；波动大时以盲测 + 情节保留为准
"""

from __future__ import annotations

STYLE_TRANSFER_CONTRACT = """【风格迁移契约】
你正在做**风格迁移**，不是另起炉灶重写剧情。

必须保留：
- 情节事实、因果顺序、已出场信息、专有名词与角色关系
- 用户选区（若有）的信息量；缺省则迁移「当前章末尾之后将接续的那一拍」的既有草稿语气

必须改变：
- 句式节奏、用词温度、对白口吻，使之贴近用户给出的目标风格
- 相对原文须有**可识别的差异幅度**（盲测能说出哪里变了），不是同义微改
- 若同时注入了作家透镜 / StyleSkill：以 StyleSkill 硬约束为底线，透镜为色彩，用户本轮风格说明为微调

禁止：
- 借风格迁移加戏、删关键转折、换结局
- 输出解释、对照表、JSON；只输出迁移后的正文
"""


def style_transfer_prompt_block(*, user_style_note: str = "") -> str:
    note = (user_style_note or "").strip()
    extra = f"\n本轮目标风格：{note}\n" if note else "\n本轮目标风格：见用户指令。\n"
    return STYLE_TRANSFER_CONTRACT + extra


#: 产品验收口径（给 ADR / 手测清单引用；非运行时数值闸）
STYLE_TRANSFER_ACCEPTANCE = (
    "盲测可识别句式/口吻差异 + 情节事实不变；"
    "不做相似度阈值门禁；契约要求可识别差异幅度"
)
