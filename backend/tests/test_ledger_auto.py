"""写作账本「保存时自动入库」的行为测试（纯本地，不需要数据库）。

背景：线上实测显示，要用户主动下命令的能力（账本、回炉、流水线）几乎没人用，
而"保存时自动刷新"的章节摘要 159/159 全覆盖。所以账本也改成保存自动跑，
这里把它的四条硬要求钉住：自动、增量、幂等、删章会清理。
"""

from __future__ import annotations

from app.core.chapter_digest import chapter_content_hash
from app.core.demo import create_demo_project
from app.core.pipeline.ledger import (
    auto_digest_ledger,
    format_ledger_for_agent,
    get_ledger,
)


def _project():
    return create_demo_project()


def test_auto_digest_fills_ledger_for_every_chapter():
    p = auto_digest_ledger(_project())
    ledger = get_ledger(p)

    assert len(ledger["chapterFacts"]) == len(p.chapters)
    assert {f["chapterId"] for f in ledger["chapterFacts"]} == {c.id for c in p.chapters}
    # 每章都记了内容指纹，供下次增量比对
    assert all(f.get("sourceHash") for f in ledger["chapterFacts"])
    assert ledger["events"]
    assert ledger["updatedAt"]


def test_auto_digest_is_incremental_and_idempotent():
    p = auto_digest_ledger(_project())
    first = get_ledger(p)
    first_hashes = {f["chapterId"]: f["sourceHash"] for f in first["chapterFacts"]}
    events_after_first = len(first["events"])
    states_after_first = len(first["characterStates"])

    # 内容没变 → 直接跳过（甚至不做无谓的 model_copy）
    again = auto_digest_ledger(p)
    assert again is p

    # 改一章 → 只有这一章重算，事件数不会增长（幂等）
    target = p.chapters[0]
    changed = p.model_copy(deep=True)
    changed.chapters[0].blocks = list(changed.chapters[0].blocks) + [
        {"type": "dialogue", "characterId": changed.characters[0].id, "text": "新增一句台词。"}
    ]
    out = auto_digest_ledger(changed)
    ledger = get_ledger(out)

    assert len(ledger["chapterFacts"]) == len(p.chapters)
    assert len(ledger["events"]) == events_after_first
    assert len(ledger["characterStates"]) <= states_after_first + 1
    new_hashes = {f["chapterId"]: f["sourceHash"] for f in ledger["chapterFacts"]}
    assert new_hashes[target.id] != first_hashes[target.id]
    for chapter_id, h in first_hashes.items():
        if chapter_id != target.id:
            assert new_hashes[chapter_id] == h  # 其它章指纹未变


def test_auto_digest_prunes_anchors_of_deleted_chapter():
    p = auto_digest_ledger(_project())
    assert len(p.chapters) >= 2
    gone = p.chapters[0].id

    trimmed = p.model_copy(deep=True)
    trimmed.chapters = [c for c in trimmed.chapters if c.id != gone]
    out = auto_digest_ledger(trimmed)
    ledger = get_ledger(out)

    assert all(f["chapterId"] != gone for f in ledger["chapterFacts"])
    assert all(s.get("chapterId") != gone for s in ledger["characterStates"])
    assert all(e.get("chapterId") != gone for e in ledger["events"])
    assert all(f.get("plantedChapter") != gone for f in ledger["foreshadows"])


def test_auto_digest_respects_per_save_budget():
    p = _project()
    assert len(p.chapters) >= 2

    first_pass = auto_digest_ledger(p, max_chapters=1)
    assert len(get_ledger(first_pass)["chapterFacts"]) == 1

    # 下一次保存继续补齐，不会丢掉"待入库"的章节
    second_pass = auto_digest_ledger(first_pass, max_chapters=1)
    assert len(get_ledger(second_pass)["chapterFacts"]) == 2
    third_pass = auto_digest_ledger(second_pass)
    assert len(get_ledger(third_pass)["chapterFacts"]) == len(p.chapters)


def test_auto_digest_never_breaks_the_save_path():
    """记账失败必须静默放过——保存不能因为附带能力挂掉。"""

    import app.core.pipeline.ledger as ledger_mod

    original = ledger_mod.digest_chapter_into_ledger

    def boom(*_a, **_kw):
        raise RuntimeError("digest exploded")

    ledger_mod.digest_chapter_into_ledger = boom
    try:
        p = _project()
        out = auto_digest_ledger(p)
        assert out is p  # 原样返回，没有抛异常
    finally:
        ledger_mod.digest_chapter_into_ledger = original


def test_auto_digested_ledger_lands_in_the_agent_anchor_block():
    """自动攒起来的账本要真的进 Agent 的硬锚块（否则等于白记）。"""
    p = auto_digest_ledger(_project())
    block = format_ledger_for_agent(get_ledger(p))

    assert "写作账本" in block
    assert p.chapters[0].title in block
    assert "章节事实摘要" in block


def test_content_hash_changes_only_when_chapter_changes():
    p = _project()
    h0 = chapter_content_hash(p.chapters[0])
    same = p.model_copy(deep=True)
    assert chapter_content_hash(same.chapters[0]) == h0
    same.chapters[0].title = "改了标题"
    assert chapter_content_hash(same.chapters[0]) != h0


def test_content_hash_is_stable_across_db_key_reordering():
    """jsonb 不保留键顺序：指纹不能因为键顺序变化而变化。

    实测过的坑：项目 blob 存在 jsonb 列，读回来时 block 的键被重排，
    于是同一章在"内存对象"和"库里读回的对象"之间算出了不同指纹，
    导致每次保存都把全部章节当成"内容变了"重算一遍。
    """
    p = _project()
    ch = p.chapters[0]
    h0 = chapter_content_hash(ch)

    # 同一个 block，键顺序颠倒（模拟 jsonb 重排后的样子）
    reordered = ch.model_copy(deep=True)
    reordered.blocks = [
        {k: b[k] for k in reversed(list(b.keys()))} for b in ch.blocks
    ]
    assert chapter_content_hash(reordered) == h0

    # 内容真的改了，指纹必须变
    changed = ch.model_copy(deep=True)
    changed.blocks = list(changed.blocks) + [
        {"type": "dialogue", "characterId": "char1", "text": "新台词。"}
    ]
    assert chapter_content_hash(changed) != h0
