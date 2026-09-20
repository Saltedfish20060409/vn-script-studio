"""按任务分档的采样参数。

为什么单独放一处：原来温度散在 agent_loop、mark_revise、style_memory 等各处，值本身也没写清
"为什么是这个数"。结果就是**同一个模型、同一个任务，走不同入口时手感不一样**——
作者会觉得"这工具不如网页端稳"，其实只是参数不一致。

分档依据（都是"这个任务要什么"）：
- **连续创作**要变化 → 温度偏高；
- **改稿/润色**要贴原意 → 中等；
- **一致性检查/结构化输出**要稳要准 → 偏低；
- 工艺卡关掉时稍微放开一点（没有工艺约束，靠模型自己发挥）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

# 兜底：不认识的写作任务按"连续创作"处理
DEFAULT_WRITING_TEMPERATURE = 0.78

# 任务 → 基础温度
TASK_TEMPERATURE: Dict[str, float] = {
    "continue": 0.78,  # 续写：要有新东西，但又不能跑偏
    "scene": 0.78,  # 场景扩写，同续写
    "rewrite": 0.60,  # 改写：贴原意优先
    "polish": 0.55,  # 润色：只动语言层
    "voice": 0.50,  # 声线/口吻调整：稳一点
    "consistency": 0.40,  # 一致性检查：要准，不要创意
    "outline": 0.70,  # 大纲/节拍：需要发散
    "chat": 0.70,  # 讨论：不必太随机
}

# 工艺卡档位对温度的修正
CRAFT_ADJUST: Dict[str, float] = {
    "full": 0.0,
    "auto": 0.0,
    "lite": -0.06,
    "off": +0.04,
}

# 固定任务的档位（非 agent 循环）
MARK_REVISE_TEMPERATURE = 0.55  # 标记批改：局部改写
MARK_ADVICE_TEMPERATURE = 0.40  # 只给建议：更保守
STYLE_MEMORY_TEMPERATURE = 0.30  # 从作者文本提炼文风：要稳
STRUCTURED_TEMPERATURE = 0.20  # 结构化/JSON 输出
RECAP_TEMPERATURE = 0.40  # 前情提要：要准，不要发挥

_MIN_TEMPERATURE = 0.2
_MAX_TEMPERATURE = 1.0


@dataclass(frozen=True)
class Sampling:
    temperature: float
    max_tokens: Optional[int] = None


def clamp_temperature(value: float) -> float:
    return max(_MIN_TEMPERATURE, min(_MAX_TEMPERATURE, value))


def task_temperature(task: str, craft_mode: str = "auto") -> float:
    """某个写作任务这一轮该用什么温度。"""
    base = TASK_TEMPERATURE.get((task or "").strip(), DEFAULT_WRITING_TEMPERATURE)
    adjust = CRAFT_ADJUST.get((craft_mode or "auto").strip(), 0.0)
    return round(clamp_temperature(base + adjust), 4)


def sampling_for(task: str, craft_mode: str = "auto") -> Sampling:
    return Sampling(temperature=task_temperature(task, craft_mode))
