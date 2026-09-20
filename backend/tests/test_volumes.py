"""卷结构与字数统计（纯函数，不碰数据库）。

两条都是实打实的用户可见行为：
1. 分卷后 `chapter.volumeId` 指向已删除的卷 → 必须清空，不能留悬空归属；
2. 「写了多少字」必须算**正文（prose）**——否则纯用正文写作的人（网文/轻小说的主流用法）
   统计恒为 0，日更热力图、章节回炉对比全都跟着失真。
"""

from __future__ import annotations

from app.core.project import normalize_project, normalize_volumes
from app.domain.types import SceneChapter, VnProject
from app.services.writing_stats import (
    chapter_metrics,
    count_chapter_words,
    volume_metrics,
)


def _chapter(ch_id: str, title: str, *, prose: str = "", volume_id: str | None = None):
    ch = SceneChapter(id=ch_id, title=title, prose=prose)
    if volume_id:
        ch.volumeId = volume_id
    return ch


def _project(chapters, volumes=None) -> VnProject:
    return normalize_project(
        {
            "id": "p1",
            "title": "测试",
            "chapters": [c.model_dump() for c in chapters],
            "volumes": volumes or [],
        }
    )


# ---------------------------------------------------------------------------
# 卷的规范化
# ---------------------------------------------------------------------------


def test_volumes_pass_through_and_chapters_keep_their_volume():
    volumes, chapters = normalize_volumes(
        [{"id": "v1", "title": "第一卷 春"}],
        [{"id": "ch1", "title": "第一章", "volumeId": "v1"}],
    )
    assert volumes == [{"id": "v1", "title": "第一卷 春"}]
    assert chapters[0]["volumeId"] == "v1"


def test_dangling_volume_reference_is_cleared():
    """删掉卷之后，章节不能还指着一个不存在的卷（否则界面上没有它的归属）。"""
    volumes, chapters = normalize_volumes(
        [{"id": "v1", "title": "第一卷"}],
        [
            {"id": "ch1", "title": "第一章", "volumeId": "v1"},
            {"id": "ch2", "title": "第二章", "volumeId": "v-deleted"},
        ],
    )
    assert [v["id"] for v in volumes] == ["v1"]
    assert chapters[0]["volumeId"] == "v1"
    assert "volumeId" not in chapters[1]


def test_volume_without_id_gets_one_and_empty_volume_is_dropped():
    volumes, _ = normalize_volumes([{"title": "无名卷"}, {"id": "", "title": ""}, "垃圾数据"], [])
    assert len(volumes) == 1
    assert volumes[0]["title"] == "无名卷"
    assert volumes[0]["id"]


def test_project_without_volumes_behaves_exactly_as_before():
    """老工程（没有 volumes 字段）必须完全不受影响：空卷列表 = 平铺章节。"""
    p = _project([_chapter("ch1", "第一章", prose="你好")])
    assert p.volumes == []
    assert getattr(p.chapters[0], "volumeId", None) in (None, "")


# ---------------------------------------------------------------------------
# 字数：正文优先
# ---------------------------------------------------------------------------


def test_prose_is_counted():
    ch = _chapter("ch1", "第一章", prose="雨落在站台上。他抬起手。")
    assert count_chapter_words(ch) == len("雨落在站台上他抬起手")


def test_blocks_counted_when_there_is_no_prose():
    ch = SceneChapter(
        id="ch1",
        title="第一章",
        blocks=[
            {"type": "label", "id": "start", "name": "start"},
            {"type": "narration", "text": "雨落在站台上。"},
            {"type": "dialogue", "characterId": "c1", "text": "走吧。"},
        ],
    )
    assert count_chapter_words(ch) == len("雨落在站台上走吧")


def test_prose_wins_over_generated_blocks_no_double_counting():
    """prose + 由它生成的 blocks：只算 prose，否则同一段内容被数两遍。"""
    ch = SceneChapter(
        id="ch1",
        title="第一章",
        prose="雨落在站台上。",
        blocks=[{"type": "narration", "text": "雨落在站台上。"}],
    )
    assert count_chapter_words(ch) == len("雨落在站台上")


def test_blank_prose_falls_back_to_blocks():
    ch = SceneChapter(
        id="ch1",
        title="第一章",
        prose="   \n  ",
        blocks=[{"type": "narration", "text": "还是用脚本。"}],
    )
    assert count_chapter_words(ch) == len("还是用脚本")


# ---------------------------------------------------------------------------
# 每卷进度
# ---------------------------------------------------------------------------


def test_volume_metrics_aggregate_chapters_and_words():
    p = _project(
        [
            _chapter("ch1", "第一章", prose="一二三", volume_id="v1"),
            _chapter("ch2", "第二章", prose="四五六七", volume_id="v1"),
            _chapter("ch3", "第三章", prose="八", volume_id="v2"),
            _chapter("ch4", "第四章", prose="九"),
        ],
        [{"id": "v1", "title": "第一卷"}, {"id": "v2", "title": "第二卷"}],
    )
    rows = volume_metrics(p)
    assert [r["title"] for r in rows] == ["第一卷", "第二卷", "未分卷"]
    assert rows[0]["chapters"] == 2 and rows[0]["words"] == 7
    assert rows[0]["avgChapterWords"] == 4  # 7/2 四舍五入
    assert rows[1]["chapters"] == 1 and rows[1]["words"] == 1
    # 没归卷的章节单独一档，方便界面提示"还有 N 章没分卷"
    assert rows[2]["id"] == "" and rows[2]["chapters"] == 1 and rows[2]["words"] == 1


def test_volume_metrics_empty_when_no_volumes():
    p = _project([_chapter("ch1", "第一章", prose="一二三")])
    assert volume_metrics(p) == []


def test_volume_metrics_counts_match_chapter_metrics():
    """两处数字必须一致（面板与卷头各算一遍就会对不上）。"""
    p = _project(
        [
            _chapter("ch1", "第一章", prose="一二三", volume_id="v1"),
            _chapter("ch2", "第二章", prose="四五六"),
        ],
        [{"id": "v1", "title": "第一卷"}],
    )
    chapters = {c["id"]: c["words"] for c in chapter_metrics(p)}
    total_by_volume = sum(r["words"] for r in volume_metrics(p))
    assert total_by_volume == sum(chapters.values())


def test_chapter_metrics_reports_volume_id():
    p = _project([_chapter("ch1", "第一章", prose="一二三", volume_id="v1")],
                 [{"id": "v1", "title": "第一卷"}])
    assert chapter_metrics(p)[0]["volumeId"] == "v1"
