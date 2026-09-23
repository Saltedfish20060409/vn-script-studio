"""轻小说起步工程模板（纯函数测试：不联网、不调模型、不碰数据库）。

这份测试盯的是"作者第一次打开时会看到什么"：
- 一卷三章、每章一句 synopsis + 2–4 段正文 + 章末钩子；
- 三个角色都有口吻与台词示例（口吻工坊的输入）；
- 世界设定与术语表条目挂得上触发词、连得到真实角色 / 章节；
- 节拍表骨架能被 story-metrics 真读到（它只从 harnessRuns 里读）；
- 章末钩子真的进了账本，且钩子文本就是正文里写过的那一句。
"""

from __future__ import annotations

import re
import socket

from app.core.ln_template import (
    LN_CHAPTER_IDS,
    LN_DEFAULT_TITLE,
    LN_VOLUME_ID,
    build_ln_beat_sheet,
    build_ln_glossary,
    build_ln_template_project,
    build_ln_world_entries,
)
from app.core.pipeline.ledger import foreshadow_report
from app.core.project import normalize_project
from app.core.story_metrics import EMOTION_ORDER
from app.domain.types import VnProject
from app.services.writing_stats import count_chapter_words

#: 中文正文里不该出现的半角标点（`H-107` 的连字符不在其列）
_HALF_WIDTH = (",", ".", "!", "?", ";", ":", '"')


def _paragraphs(chapter) -> list[str]:
    return [p.strip() for p in str(chapter.prose or "").split("\n") if p.strip()]


# --------------------------------------------------------------------------- 工程骨架


def test_project_is_a_normalized_volume_of_three_chapters():
    project = build_ln_template_project()
    assert isinstance(project, VnProject)
    assert project.title == LN_DEFAULT_TITLE
    assert project.logline and project.genre
    assert len(project.volumes or []) == 1
    assert (project.volumes or [])[0].id == LN_VOLUME_ID
    assert (project.volumes or [])[0].title.strip()
    assert (project.volumes or [])[0].note.strip()  # 卷备注：这一卷要写什么
    assert [c.id for c in project.chapters] == list(LN_CHAPTER_IDS)
    for chapter in project.chapters:
        assert chapter.volumeId == LN_VOLUME_ID
        assert chapter.title.strip()


def test_saving_round_trip_keeps_the_volume_link():
    """保存链路会再 normalize 一次；卷归属不能在这一步被清空（否则章节掉出第一卷）。"""
    project = build_ln_template_project()
    again = normalize_project(project)
    assert [v.id for v in again.volumes or []] == [LN_VOLUME_ID]
    assert [c.volumeId for c in again.chapters] == [LN_VOLUME_ID] * 3


def test_custom_title_and_blank_title_falls_back():
    assert build_ln_template_project("钟声与失物招领处").title == "钟声与失物招领处"
    assert build_ln_template_project("   ").title == LN_DEFAULT_TITLE


def test_two_builds_share_nothing():
    """纯函数：两次调用互不影响（模板会被反复用来开新工程）。"""
    a = build_ln_template_project()
    b = build_ln_template_project()
    assert a.id != b.id
    assert a.chapters is not b.chapters
    assert a.loreEntries is not b.loreEntries

    a.chapters[0].title = "改过的标题"
    a.loreEntries[0].title = "改过的条目"
    a.characters[0].displayName = "改过的名字"
    assert b.chapters[0].title != "改过的标题"
    assert b.loreEntries[0].title != "改过的条目"
    assert b.characters[0].displayName != "改过的名字"

    # 帮助函数每次也要返回全新对象，别把模块级字典漏出去
    sheet_a = build_ln_beat_sheet()
    sheet_a["beats"].append({"name": "手加的", "action": "不应该影响下一次调用"})
    assert len(build_ln_beat_sheet()["beats"]) == 3


# --------------------------------------------------------------------------- 正文


def test_every_chapter_has_synopsis_and_two_to_four_paragraphs():
    project = build_ln_template_project()
    for chapter in project.chapters:
        assert (chapter.synopsis or "").strip(), chapter.id
        paragraphs = _paragraphs(chapter)
        assert 2 <= len(paragraphs) <= 4, chapter.id
        for para in paragraphs:
            assert para == para.strip()
            assert len(para) >= 8, chapter.id
        # 中日文标点：正文与 synopsis 里都不该出现半角标点
        for bad in _HALF_WIDTH:
            assert bad not in str(chapter.prose), (chapter.id, bad)
            assert bad not in str(chapter.synopsis), (chapter.id, bad)


def test_manuscript_counts_as_words_for_the_stats_panel():
    """纯正文写作也必须被算进字数（否则日更热力图与每卷进度全是 0）。"""
    project = build_ln_template_project()
    per_chapter = [count_chapter_words(c) for c in project.chapters]
    assert all(n > 120 for n in per_chapter), per_chapter
    assert sum(per_chapter) > 400


def test_chapter_ends_on_a_hook():
    project = build_ln_template_project()
    for chapter in project.chapters:
        last = _paragraphs(chapter)[-1]
        assert last[-1] in "。」？！", (chapter.id, last)
        assert len(last) >= 8


# --------------------------------------------------------------------------- 角色


def test_three_characters_with_voice_and_a_sample_line():
    project = build_ln_template_project()
    assert len(project.characters) == 3
    assert len({c.id for c in project.characters}) == 3

    for char in project.characters:
        assert char.displayName.strip(), char.id
        # defineName 会被当成脚本里的变量名用，必须是合法标识符
        assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", char.defineName), char.id
        assert (char.voice or "").strip(), char.id  # 口吻：AI 写对白靠它
        assert (char.bio or "").strip(), char.id
        assert (char.relationships or "").strip(), char.id
        assert (char.color or "").startswith("#"), char.id

        samples = char.voiceCorpus or []
        assert samples, char.id
        lines = [line for sample in samples for line in sample.lines]
        assert lines, char.id
        assert all(line.text.strip() for line in lines), char.id
        assert any(line.speaker == "self" for line in lines), char.id


# --------------------------------------------------------------------------- 设定与术语


def test_world_entries_and_glossary_are_retrievable():
    project = build_ln_template_project()
    entries = list(project.loreEntries or [])
    world = [e for e in entries if "世界设定" in (e.tags or [])]
    terms = [e for e in entries if "术语" in (e.tags or [])]

    assert 2 <= len(world) <= 4, [e.title for e in world]
    assert len(terms) == 3, [e.title for e in terms]
    assert len(world) + len(terms) == len(entries)
    assert len({e.id for e in entries}) == len(entries)

    chapter_ids = {c.id for c in project.chapters}
    character_ids = {c.id for c in project.characters}
    for entry in entries:
        assert entry.title.strip() and entry.body.strip(), entry.id
        # 没有触发词就等于检索不到，这条设定写了也白写
        assert entry.keywords, entry.id
        for link in entry.links or []:
            pool = character_ids if link.toType == "character" else chapter_ids
            assert link.toId in pool, (entry.id, link.toId)

    # 至少一条是钉住的硬设定（每轮都会带上，不受检索影响）
    assert any(e.pinned for e in entries)
    # 关联写法只允许 types.py 里声明过的三种实体
    assert all(
        link.toType in ("character", "location", "chapter")
        for entry in entries
        for link in (entry.links or [])
    )
    # 帮助函数与工程里的是同一份内容（否则取数据的地方会走岔）
    assert [e["title"] for e in build_ln_world_entries()] == [e.title for e in world]
    assert [e["title"] for e in build_ln_glossary()] == [e.title for e in terms]


def test_bible_fills_the_fields_the_agent_reads():
    project = build_ln_template_project()
    bible = project.bible
    assert bible is not None
    for part in (bible.world, bible.background, bible.outline, bible.themes, bible.notes):
        assert (part or "").strip()
    # 大纲写成一行一个节拍：检索会按行取节拍
    outline_lines = [line for line in str(bible.outline).splitlines() if line.strip()]
    assert len(outline_lines) >= 3
    assert all(len(line.strip()) >= 8 for line in outline_lines)


# --------------------------------------------------------------------------- 节拍表


def test_beat_sheet_has_a_goal_and_three_beats():
    sheet = build_ln_beat_sheet()
    assert str(sheet["goal"]).strip()
    beats = sheet["beats"]
    assert len(beats) == 3
    for beat in beats:
        assert str(beat["name"]).strip()
        assert str(beat["action"]).strip()
    assert len(sheet["triggers"]) >= 3


def test_declared_emotions_are_recognizable():
    """声明的情绪必须落在 EMOTION_ORDER 的词表里：认不出就不对账（它不猜）。"""
    sheet = build_ln_beat_sheet()
    for key in ("emotionStart", "emotionEnd"):
        moods = sheet[key]
        assert moods, key
        for who, mood in moods.items():
            assert mood in EMOTION_ORDER, (key, who, mood)

    names = {c.displayName for c in build_ln_template_project().characters}
    declared = set(sheet["emotionStart"]) | set(sheet["emotionEnd"])
    assert declared <= names, declared - names


def test_beat_sheet_is_reachable_from_the_project():
    """节拍表在工程里的归宿是 harnessRuns——story-metrics 只从这里读得到它。"""
    project = build_ln_template_project()
    runs = [r for r in (project.harnessRuns or []) if isinstance(r, dict)]
    assert runs
    sheets = [r["beatSheet"] for r in runs if isinstance(r.get("beatSheet"), dict)]
    assert sheets == [build_ln_beat_sheet()]
    # 这条记录是模板预置的骨架，不是一次真实运行：必须标明
    assert runs[0].get("templateSeed") is True
    assert runs[0].get("kind") == "plan"


# --------------------------------------------------------------------------- 账本与伏笔


def test_chapter_hooks_land_in_the_ledger_and_point_at_real_chapters():
    project = build_ln_template_project()
    rows = foreshadow_report(project)
    assert len(rows) == 3

    by_chapter = {row["plantedChapter"]: row for row in rows}
    assert set(by_chapter) == set(LN_CHAPTER_IDS)

    for chapter in project.chapters:
        row = by_chapter[chapter.id]
        assert row["status"] == "open"
        assert row["hook"].strip()
        # 钩子必须是这一章正文里真写过的一句（不是另编的摘要）
        assert row["hook"] in str(chapter.prose)
        assert row["hook"] == _paragraphs(chapter)[-1]
        # 界面上写的是"埋在哪一章"，所以章名必须解析得到
        assert row["plantedChapterTitle"] == chapter.title
        assert row["ageChapters"] is not None


def test_ledger_keys_match_the_real_ledger_shape():
    project = build_ln_template_project()
    ledger = project.writingLedger or {}
    assert set(ledger) >= {"chapterFacts", "characterStates", "foreshadows", "events"}
    assert ledger["chapterFacts"] == []
    assert ledger["characterStates"] == []
    assert all("paidInChapter" in row for row in ledger["foreshadows"])


# --------------------------------------------------------------------------- 纯函数


def test_building_the_template_needs_no_network(monkeypatch):
    """把 socket 封死也建得出来：模板不联网、不调模型。"""

    def _boom(*args, **kwargs):
        raise AssertionError("模板不应该发起网络请求")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)

    project = build_ln_template_project("断网也能起步")
    assert project.title == "断网也能起步"
    assert len(project.chapters) == 3
    assert len(project.characters) == 3
