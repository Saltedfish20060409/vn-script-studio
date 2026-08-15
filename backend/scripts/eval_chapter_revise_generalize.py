"""Cross-domain chapter-revise smoke eval (not 拟合少女-specific)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.config import get_settings
from app.core.ai import DeepSeekConfig
from app.core.chapter_revise import (
    _commercial_score,
    _hard_fail_snippets,
    resolve_chapter_source,
    run_chapter_revise,
)
from app.core.demo import create_demo_project
from app.domain.types import Character, SceneChapter

SYN = """
【旧校舍】
转校第一天。你站在活动室门口。

学姐：（笑）我来给你介绍一下这里。这里是厨房，那边是吃饭的地方，冰箱里有食材，饿了可以拿。私人空间就是需要尊重对吧？

你：（内心OS：她话好多……）好的。

学姐：做咖喱的时候为什么要分开炒肉和蔬菜？盐是现在撒吗？先焯水再下锅会比较好。

你：因为所谓咖喱的原理就是分层入味，简单来说需要先把肉的油脂逼出来，再下蔬菜，最后才是调味……否则味道会糊成一团，也不够香。

学姐：明白了。为了达成新生活的要求，我会把这些当成任务来完成。

系统提示：请选择您的回答
A. “这样解释最清楚。”
B. “按步骤做就不会错。”
C. “你记住就好。”

你选了A。

学姐：那扇门后面是秘密区域吗？
你：算是防止外面的人随便进来。不是要把你关在里面。你可以随时开。虽然这里不会有什么危险，但这是个好习惯。
"""


async def one(label: str, project, chapter_id: str) -> dict:
    s = get_settings()
    cfg = DeepSeekConfig(
        apiKey=s.deepseek_api_key,
        baseUrl=s.deepseek_base_url,
        model=s.deepseek_model,
    )
    res = await run_chapter_revise(cfg, project, chapter_id=chapter_id, note="回炉人味")
    source, _, _, _ = resolve_chapter_source(project, chapter_id=chapter_id)
    score = _commercial_score(
        res.revised_text, source_chars=len(source), source_text=source
    )
    user_msg_ok = (
        "降本画像" not in res.message
        and "tokens" not in res.message
        and "apartment_tour" not in res.message
        and "qa_pingpong" not in res.message
    )
    return {
        "label": label,
        "commercial_pass": score["pass"],
        "density": score.get("density_vs_source"),
        "hard": score["hard"],
        "menu_miss": score.get("menu_miss"),
        "llm_rounds": len(res.llm_calls),
        "elapsed_ms": res.elapsed_ms,
        "user_msg_clean": user_msg_ok,
        "warnings_user": res.warnings,
        "debug_has_pipeline": any(
            "降本" in x or "规则硬删" in x for x in res.debug_trace
        ),
        "revised_has_hard": _hard_fail_snippets(res.revised_text),
    }


async def main() -> None:
    p1 = create_demo_project()
    p1.title = "转校生的咖喱"
    lines = [ln for ln in SYN.replace("\r\n", "\n").split("\n") if ln.strip()]
    p1.chapters = [
        SceneChapter(
            id="syn1",
            title="活动室",
            blocks=[{"type": "raw", "code": ln} for ln in lines],
        )
    ]
    p1.characters = [
        Character(id="mc", defineName="hero", displayName="你", voice="闷", bio="转校生"),
        Character(
            id="senpai",
            defineName="senpai",
            displayName="学姐",
            voice="热络",
            bio="烹饪社",
        ),
    ]
    p2 = create_demo_project()
    r1 = await one("synthetic_school", p1, "syn1")
    r2 = await one("demo_rainy_station", p2, p2.chapters[0].id)
    out = {
        "cases": [r1, r2],
        "all_pass": all(c["commercial_pass"] for c in [r1, r2]),
        "all_msg_clean": all(c["user_msg_clean"] for c in [r1, r2]),
    }
    out_path = ROOT / ".cache_agent_generalize.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
