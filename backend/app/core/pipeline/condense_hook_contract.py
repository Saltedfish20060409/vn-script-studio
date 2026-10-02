"""condense 钩子保留：确定性检查器（不调模型）。

P2.5 W05 观察项：缩写压掉「雨里有人叫了她的旧名字」→ 回归用 must_retain 硬锚。
LLM 手测 / 评测 pipeline 可复用 `missing_retained_phrases`。
"""

from __future__ import annotations

from typing import Iterable, Sequence


def missing_retained_phrases(
    before: str,
    after: str,
    phrases: Sequence[str],
) -> list[str]:
    """返回「缩写前有、缩写后丢失」的短语；空列表 = 通过。"""
    missing: list[str] = []
    for phrase in phrases:
        p = (phrase or "").strip()
        if not p:
            continue
        if p in before and p not in after:
            missing.append(p)
    return missing


def assert_condense_keeps_hooks(
    before: str,
    after: str,
    phrases: Iterable[str],
) -> None:
    lost = missing_retained_phrases(before, after, list(phrases))
    if lost:
        raise AssertionError(f"condense 丢失未回收钩子短语: {lost}")
