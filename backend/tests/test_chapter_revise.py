from app.core.chapter_revise import format_diagnosis_md, resolve_chapter_source
from app.core.demo import create_demo_project


def test_format_diagnosis_md_basic():
    md = format_diagnosis_md(
        {
            "verdict": "执行层偏说明书",
            "keep": [{"what": "起名", "why": "有温度"}],
            "cut": [{"what": "导览", "why": "百科课"}],
            "rewrite": [
                {
                    "what": "起名问答",
                    "how": "加毛边",
                    "before": "明白了",
                    "after": "……我也说不清",
                }
            ],
            "structure": ["接人", "起名", "晚饭"],
            "antiPatternsHit": ["qa_pingpong", "inner_os"],
        }
    )
    assert "章节回炉" in md
    assert "起名" in md
    assert "导览" in md
    assert "改前" in md
    assert "接人" in md
    assert "问答乒乓" in md


def test_fake_choice_and_rough_patch():
    from app.core.chapter_revise import (
        _ensure_rough_choice,
        _hard_fail_snippets,
        _has_fake_choice,
    )

    menu = """
系统提示：请选择您的回答
A. “算是告别实验室，开始新生活的记号吧。”
B. “一直叫编号显得生分。有个名字会方便些。”
C. “你可以自己尝试感受一下。”
"""
    assert _has_fake_choice(menu)
    assert "fake_choice" in _hard_fail_snippets(menu)
    patched, changed = _ensure_rough_choice(menu)
    assert changed
    assert not _has_fake_choice(patched)
    assert "说不清" in patched


def test_process_faq_hard_fail_is_genre_agnostic():
    from app.core.chapter_revise import _find_menu_insert_pos, _hard_fail_snippets

    faq = "为什么要分开？什么时候放？简单来说就是需要先了解原理。"
    hits = _hard_fail_snippets(faq)
    assert "process_faq" in hits
    assert "cooking_faq" not in hits

    # Generic process FAQ (not cooking-branded)
    demo = "盐是现在撒吗？先焯水再下锅。"
    assert "process_faq" in _hard_fail_snippets(demo)

    draft = ("旁白。\n\n" * 20) + "她问你叫什么名字。\n\n然后你们安静了一会儿。\n\n" + (
        "旁白。\n\n" * 10
    )
    pos = _find_menu_insert_pos(draft)
    assert pos > 40
    # Must not depend on a specific character name
    assert "雪菜" not in draft


def test_soft_tour_and_orphan_task_hard_fail():
    from app.core.chapter_revise import _deterministic_excise, _hard_fail_snippets

    soft_tour = "雪菜，熟悉一下这个空间吧。那边是吃饭的地方，冰箱里有食材，饿了可以拿。"
    assert "apartment_tour" in _hard_fail_snippets(soft_tour)

    orphan = '你被她一本正经的总结逗得有些好笑：“……也不用当成任务来完成。”'
    assert "task_summary_ack" in _hard_fail_snippets(orphan)

    cleaned, removed = _deterministic_excise(soft_tour + "\n\n" + orphan + "\n\n" + "她跟了过来。")
    assert "apartment_tour" in removed or "task_summary_ack" in removed
    assert "熟悉一下这个空间" not in cleaned
    assert "当成任务来完成" not in cleaned
    assert "她跟了过来" in cleaned


def test_needs_smooth_and_soft_critic_gate():
    from app.core.chapter_revise import _needs_smooth, _soft_critic_needed

    before = "A" * 500
    after = "A" * 200  # large drop but not jumpy
    assert _needs_smooth(before, after) is False

    jumpy = "也不用当成任务来完成。\n\n" + ("旁白。" * 40)
    assert _needs_smooth("X" * 600, jumpy) is True

    # Commercial pass → skip critic even with soft smell notes possible
    clean = "你看了她一眼。\n\n雪菜没有追问。\n\n晚饭有点烫。"
    need, _ = _soft_critic_needed(clean, source_chars=200)
    assert need is False


def test_menu_reseed_and_qa_compress():
    from app.core.chapter_revise import (
        _apply_diagnosis_patches,
        _build_user_notes,
        _commercial_score,
        _compress_qa_pingpong,
        _has_choice_menu,
        _reseed_menus_from_source,
        format_diagnosis_md,
    )

    source = """
你看向她。

系统提示：请选择您的回答
A. “算是告别实验室，开始新生活的记号吧。”
B. “一直叫编号显得生分。有个名字会方便些。”
C. “你可以自己尝试感受一下。”

她点了点头。
"""
    draft = "你看向她。\n\n雪菜轻轻眨眼。\n\n她点了点头。"
    assert _has_choice_menu(source)
    assert not _has_choice_menu(draft)
    score0 = _commercial_score(draft, source_chars=len(source), source_text=source)
    assert score0["menu_miss"] is True
    assert score0["pass"] is False

    seeded, changed = _reseed_menus_from_source(draft, source)
    assert changed
    assert _has_choice_menu(seeded)
    assert "说不清" in seeded
    score1 = _commercial_score(seeded, source_chars=len(source), source_text=source)
    assert score1["menu_miss"] is False

    qa = (
        "雪菜：这是什么？\n"
        "你：因为所谓味增的原理就是发酵，简单来说需要先……（很长的说明书）" + ("啊" * 40) + "\n"
        "明白了。那就这样。"
    )
    compressed, tags = _compress_qa_pingpong(qa)
    assert tags
    assert "明白了" not in compressed or "ack_loop" in tags

    text, n = _apply_diagnosis_patches(
        "带你熟悉一下这里。她跟过来。",
        {"rewrite": [{"before": "带你熟悉一下这里。", "after": "你领她走过客厅。"}]},
    )
    assert n == 1
    assert "熟悉一下" not in text
    assert "领她走过客厅" in text

    notes = _build_user_notes(
        score={"too_dense": False, "density_vs_source": 0.86, "menu_miss": False},
        final_hard=[],
        final_smells=["qa_pingpong"],
        source_title="第一章",
    )
    blob = "；".join(notes)
    assert "尚未写入" in blob
    assert "问答乒乓" in blob
    assert "apartment_tour" not in blob
    assert "tokens" not in blob
    assert "降本" not in blob
    assert "缩写" in blob or "对照" in blob

    md = format_diagnosis_md(
        {"verdict": "偏说明书", "antiPatternsHit": ["qa_pingpong", "inner_os"]}
    )
    assert "问答乒乓" in md
    assert "内心OS标签" in md
    assert "qa_pingpong" not in md


def test_resolve_chapter_source_from_demo():
    p = create_demo_project()
    text, cid, title, warnings = resolve_chapter_source(p, chapter_id=p.chapters[0].id)
    assert cid == p.chapters[0].id
    assert isinstance(text, str)
    assert title
    assert isinstance(warnings, list)


def test_hard_fail_patterns_are_demo_free():
    """The revision protocol must not hardcode demo-story tokens."""
    import inspect

    from app.core import chapter_revise as cr

    src = inspect.getsource(cr)
    for token in ("味增", "大泡泡", "雪菜", "雨夜车站"):
        assert token not in src, f"demo token {token!r} still hardcoded in chapter_revise"
