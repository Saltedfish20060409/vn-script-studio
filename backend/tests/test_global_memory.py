"""卷级 / 全局记忆层的测试。

这里的断言对应四件对作者可见的事：
1. **不丢章**：没有卷时按固定跨度分档，每一章都要落进某一档（分卷作品里没挂卷的章节
   要进"未分卷"档，而不是凭空消失）；
2. **重要性可核对**：出场多的排前，但扛着章末钩子的关键角色要能被抬起来——公式与算式
   都写在返回值里，作者能自己验算，而不是只能信这个排序；
3. **未回收伏笔进得来、已回收的不混进来**；
4. **预算不够时不静默截断**：全局总述与未回收伏笔必须留着，省了哪几卷要写在注入块里。
"""

from __future__ import annotations

from app.core.chapter_digest import make_chapter_digest
from app.core.global_memory import (
    HOOK_SUBJECT_WEIGHT,
    MAX_KEY_EVENTS,
    build_global_memory,
    format_global_memory_for_agent,
)
from app.core.project import normalize_project

# ------------------------------------------------------------------ 夹具工具


def _d(char_id: str, text: str) -> dict:
    return {"type": "dialogue", "characterId": char_id, "text": text}


def _n(text: str) -> dict:
    return {"type": "narration", "text": text}


def _ch(
    cid: str,
    blocks: list,
    *,
    title: str | None = None,
    volume_id: str | None = None,
    prose: str | None = None,
) -> dict:
    chapter: dict = {"id": cid, "title": title or cid, "blocks": blocks}
    if volume_id:
        chapter["volumeId"] = volume_id
    if prose is not None:
        chapter["prose"] = prose
    return chapter


def _project(
    chapters: list,
    *,
    volumes: list | None = None,
    characters: list | None = None,
    ledger: dict | None = None,
):
    raw: dict = {
        "id": "p1",
        "title": "记忆测试",
        "characters": characters
        if characters is not None
        else [
            {"id": "lin", "defineName": "lin", "displayName": "林夏"},
            {"id": "zhou", "defineName": "zhou", "displayName": "周屿"},
            {"id": "chen", "defineName": "chen", "displayName": "陈默"},
        ],
        "chapters": chapters,
        "volumes": volumes or [],
    }
    if ledger is not None:
        raw["writingLedger"] = ledger
    return normalize_project(raw)


def _lin_chapter(cid: str, text: str = "嗯。", **kwargs) -> dict:
    return _ch(cid, [_d("lin", text)], **kwargs)


# ------------------------------------------------------------------ 分档与聚合


def test_span_bands_cover_every_chapter_when_there_are_no_volumes():
    chapters = [_lin_chapter(f"c{i}", title=f"第{i}章") for i in range(1, 26)]
    memory = build_global_memory(_project(chapters))

    assert memory["groupedBy"] == "span"
    assert memory["span"] == 10
    assert [(v["chapterFrom"], v["chapterTo"], v["chapterCount"]) for v in memory["volumes"]] == [
        (1, 10, 10),
        (11, 20, 10),
        (21, 25, 5),
    ]
    seen = [cid for volume in memory["volumes"] for cid in volume["chapterIds"]]
    assert seen == [f"c{i}" for i in range(1, 26)]
    assert len(seen) == len(set(seen)) == memory["chapterCount"] == 25
    assert all(volume["synthetic"] is True for volume in memory["volumes"])


def test_volumes_group_chapters_by_volume_id_and_keep_unassigned_ones():
    chapters = [
        _lin_chapter("c1", volume_id="v1"),
        _lin_chapter("c2", volume_id="v1"),
        _lin_chapter("c3", volume_id="v2"),
        _lin_chapter("c4"),
    ]
    memory = build_global_memory(
        _project(
            chapters,
            volumes=[
                {"id": "v1", "title": "第一卷 春"},
                {"id": "v2", "title": "第二卷 夏", "note": "这一卷收掉车站线"},
            ],
        )
    )

    assert memory["groupedBy"] == "volume"
    assert [v["title"] for v in memory["volumes"]] == ["第一卷 春", "第二卷 夏", "未分卷章节"]
    first, second, loose = memory["volumes"]
    assert (first["chapterFrom"], first["chapterTo"], first["chapterCount"]) == (1, 2, 2)
    assert first["volumeId"] == "v1"
    assert first["synthetic"] is False
    assert second["note"] == "这一卷收掉车站线"
    assert loose["chapterIds"] == ["c4"]
    assert loose["volumeId"] is None
    seen = [cid for volume in memory["volumes"] for cid in volume["chapterIds"]]
    assert sorted(seen) == ["c1", "c2", "c3", "c4"]


def test_dangling_volume_reference_lands_in_the_unassigned_band():
    """指向已删除卷的章节会被 normalize_volumes 清空归属——记忆层不能因此丢掉它。"""
    chapters = [_lin_chapter("c1", volume_id="v1"), _lin_chapter("c2", volume_id="v-gone")]
    memory = build_global_memory(
        _project(chapters, volumes=[{"id": "v1", "title": "第一卷"}])
    )
    titles = [v["title"] for v in memory["volumes"]]
    assert "未分卷章节" in titles
    seen = [cid for volume in memory["volumes"] for cid in volume["chapterIds"]]
    assert seen == ["c1", "c2"]


def test_volume_word_count_uses_prose_first():
    chapters = [
        _ch("c1", [], prose="雨落在站台上。" * 20),
        _ch("c2", [_d("lin", "嗯。")]),
    ]
    memory = build_global_memory(_project(chapters))
    assert memory["wordCount"] >= 120  # prose 全文都要计入，而不是只看 blocks
    assert memory["volumes"][0]["wordCount"] == memory["wordCount"]
    assert memory["volumes"][0]["empty"] is False


# ------------------------------------------------------------------ 重要性排序


def test_more_appearances_rank_higher_than_a_single_appearance():
    chapters = [
        _ch("c1", [_d("lin", "嗯。"), _d("zhou", "走吧。")], title="第1章"),
        _ch("c2", [_d("lin", "知道了。")], title="第2章"),
        _ch("c3", [_d("lin", "算了。")], title="第3章"),
    ]
    memory = build_global_memory(_project(chapters))
    characters = memory["volumes"][0]["characters"]

    assert characters[0]["name"] == "林夏"
    assert characters[0]["appearedChapters"] == 3
    assert characters[1]["name"] == "周屿"
    assert characters[1]["appearedChapters"] == 1
    assert characters[0]["formula"] == f"出场 3 章 + 章末钩子 3 次 × {HOOK_SUBJECT_WEIGHT} = 7.5"
    assert memory["hookSubjectWeight"] == HOOK_SUBJECT_WEIGHT


def test_carrying_the_chapter_close_hook_can_outweigh_one_extra_appearance():
    """陈默出场 3 章但从不承担章末钩子；周屿只出场 2 章却两次扛住章末钩子。

    设计意图：出场章数是主项，但"章末钩子主体"要能把关键角色抬起来（1.5 倍的权重
    让"两章出场 ≈ 一次钩子"）。这条测试锁住的正是这个取舍，而不是某个具体数字。
    """
    chapters = [
        # 陈默的章：5 行以上，closeHook 只取最后 4 行 → 陈默不在章末钩子里
        _ch(
            "c1",
            [_d("chen", "雨还在下。"), _n("灯灭了一盏。"), _n("伞骨响了一声。"),
             _n("水沿着檐口连成线。"), _n("站牌上的字被雨泡花了。")],
        ),
        _ch(
            "c2",
            [_d("chen", "车不会来了。"), _n("灯又灭了一盏。"), _n("远处没有声响。"),
             _n("水面浮着一层光。"), _n("夜更深了一层。")],
        ),
        _ch(
            "c3",
            [_d("chen", "回去吧。"), _n("风把小票吹走了。"), _n("广告牌闪了两下。"),
             _n("雨声盖住了脚步。"), _n("出口的卷帘门落到一半。")],
        ),
        # 周屿的章：两行，closeHook 含他的名字
        _ch("c4", [_n("雨还在下。"), _d("zhou", "我等你。")]),
        _ch("c5", [_n("钟又响了。"), _d("zhou", "别走。")]),
    ]
    memory = build_global_memory(_project(chapters))
    characters = memory["volumes"][0]["characters"]

    assert characters[0]["name"] == "周屿"
    assert characters[0]["appearedChapters"] == 2
    assert characters[0]["hookChapters"] == 2
    assert characters[0]["score"] == 2 + HOOK_SUBJECT_WEIGHT * 2
    assert characters[1]["name"] == "陈默"
    assert characters[1]["appearedChapters"] == 3
    assert characters[1]["hookChapters"] == 0


def test_hook_subject_detection_matches_aliases():
    chapters = [_ch("c1", [_n("雨还在下。"), _d("lin", "嗯。")])]
    memory = build_global_memory(
        _project(
            chapters,
            characters=[
                {"id": "lin", "defineName": "lin", "displayName": "林夏", "aliases": ["小夏"]},
            ],
        )
    )
    lin = memory["volumes"][0]["characters"][0]
    assert lin["name"] == "林夏"
    assert lin["hookChapters"] == 1


# ------------------------------------------------------------------ 关键事件


def test_key_events_are_capped_sorted_and_keep_their_source_fields():
    chapters = [_lin_chapter(f"c{i}", f"第{i}句话说完了。", title=f"第{i}章") for i in range(1, 9)]
    memory = build_global_memory(_project(chapters))
    events = memory["volumes"][0]["keyEvents"]

    assert len(events) == MAX_KEY_EVENTS
    assert [event["index"] for event in events] == sorted(event["index"] for event in events)
    for event in events:
        assert {"chapterId", "index", "title", "beatSummary", "openHook", "closeHook"} <= set(event)
        assert event["title"].startswith("第")
    assert "林夏" in events[0]["closeHook"]  # 钩子取自章摘要，不是编出来的


def test_chapters_without_content_are_not_listed_as_key_events():
    chapters = [_ch("c1", []), _ch("c2", [])]
    memory = build_global_memory(_project(chapters))
    assert memory["wordCount"] == 0
    assert memory["volumes"][0]["keyEvents"] == []
    assert memory["volumes"][0]["empty"] is True
    # 章摘要对空章会返回"（空章）"占位串，绝不能当成事件写进记忆层
    digest = make_chapter_digest(_project(chapters).chapters[0], [])
    assert digest.beatSummary == "（空章）"
    assert "（空章）" not in memory["overall"]["text"]


# ------------------------------------------------------------------ 伏笔


def test_open_foreshadows_reach_the_volume_and_the_overall_summary():
    chapters = [_lin_chapter("c1"), _lin_chapter("c2"), _lin_chapter("c3")]
    memory = build_global_memory(
        _project(
            chapters,
            ledger={
                "foreshadows": [
                    {"id": "f1", "hook": "车站的钟", "status": "open", "plantedChapter": "c2"},
                    {
                        "id": "f2",
                        "hook": "那封旧信",
                        "status": "paid",
                        "plantedChapter": "c1",
                        "paidInChapter": "c3",
                    },
                ]
            },
        )
    )

    hooks = memory["volumes"][0]["openForeshadows"]
    assert [hook["id"] for hook in hooks] == ["f1"]
    assert hooks[0]["hook"] == "车站的钟"
    assert hooks[0]["ageChapters"] == 1
    assert memory["overall"]["openHookCount"] == 1
    assert "车站的钟" in memory["overall"]["text"]
    assert "旧信" not in memory["overall"]["text"]


def test_foreshadows_are_grouped_into_the_volume_that_planted_them():
    chapters = [_lin_chapter(f"c{i}") for i in range(1, 13)]
    volumes = [
        {"id": "v1", "title": "第一卷"},
        {"id": "v2", "title": "第二卷"},
    ]
    for chapter in chapters[:10]:
        chapter["volumeId"] = "v1"
    for chapter in chapters[10:]:
        chapter["volumeId"] = "v2"
    memory = build_global_memory(
        _project(
            chapters,
            volumes=volumes,
            ledger={
                "foreshadows": [
                    {"id": "f1", "hook": "第一卷的钩子", "status": "open", "plantedChapter": "c3"},
                    {"id": "f2", "hook": "第二卷的钩子", "status": "open", "plantedChapter": "c11"},
                ]
            },
        )
    )
    first, second = memory["volumes"]
    assert [hook["hook"] for hook in first["openForeshadows"]] == ["第一卷的钩子"]
    assert [hook["hook"] for hook in second["openForeshadows"]] == ["第二卷的钩子"]
    assert memory["overall"]["openHookCount"] == 2


# ------------------------------------------------------------------ 注入块


def _long_project():
    chapters = []
    for i in range(1, 41):
        chapter = _ch(
            f"c{i}",
            [_d("lin", f"第{i}次了。"), _d("zhou", "我知道。"), _n(f"雨落在第{i}个夜里。")],
            title=f"第{i}章",
        )
        chapter["volumeId"] = f"v{(i - 1) // 10 + 1}"
        chapters.append(chapter)
    return _project(
        chapters,
        volumes=[{"id": f"v{k}", "title": f"第{k}卷"} for k in range(1, 5)],
        ledger={
            "foreshadows": [
                {"id": "f1", "hook": "车站的钟", "status": "open", "plantedChapter": "c2"},
            ]
        },
    )


def test_format_over_budget_keeps_the_overall_summary_and_the_hooks():
    memory = build_global_memory(_long_project())
    text = format_global_memory_for_agent(memory, max_chars=600)

    assert "全局总述" in text
    assert "未回收伏笔" in text
    assert "车站的钟" in text  # 钩子内容真的带出来了，不是只有一个标题
    assert "###" not in text  # 分卷明细被整段省略
    assert "关键事件" not in text
    assert "省略了" in text  # 省了哪一部分要如实写出来
    assert "第1卷" in text
    assert len(text) <= 600


def test_format_includes_volume_details_when_the_budget_allows():
    memory = build_global_memory(_long_project())
    text = format_global_memory_for_agent(memory, max_chars=6000)

    assert "关键事件" in text
    assert "出场角色" in text
    assert "### 第1卷" in text
    assert "省略了" not in text
    assert len(text) <= 6000


def test_format_honours_the_budget_lower_bound():
    """预算被传得极小也要保住两样最不该丢的：全局总述与未回收伏笔。"""
    memory = build_global_memory(_long_project())
    text = format_global_memory_for_agent(memory, max_chars=120)

    assert "全局总述" in text
    assert "未回收伏笔" in text
    assert len(text) <= 400  # 预算下限


# ------------------------------------------------------------------ 数据不足


def test_empty_project_is_safe():
    memory = build_global_memory(normalize_project({"id": "p1", "title": "空"}))

    assert memory["chapterCount"] == 1  # normalize_project 会补一个默认章
    assert memory["wordCount"] == 0
    assert memory["volumes"][0]["characters"] == []
    assert memory["volumes"][0]["keyEvents"] == []
    assert memory["volumes"][0]["openForeshadows"] == []
    assert memory["overall"]["topCharacters"] == []
    assert memory["overall"]["progress"] is None
    assert "还没有" in memory["overall"]["text"] or "空" in memory["overall"]["text"]

    text = format_global_memory_for_agent(memory)
    assert isinstance(text, str) and text
    assert "全局总述" in text


def test_project_without_characters_is_safe():
    chapters = [_ch("c1", [_n("雨落在站台上。")])]
    memory = build_global_memory(_project(chapters, characters=[]))
    assert memory["volumes"][0]["characters"] == []
    assert "还没有对白出场记录" in memory["overall"]["text"]
    assert "关键事件" in format_global_memory_for_agent(memory, max_chars=2000)


def test_overall_summary_is_template_built_from_existing_data_only():
    """总述必须由已有数据拼出来，不能出现项目里不存在的人名或情节。"""
    chapters = [
        _ch("c1", [_d("lin", "嗯。"), _d("zhou", "走吧。")], title="雨夜"),
        _ch("c2", [_d("lin", "知道了。")], title="旧信"),
    ]
    memory = build_global_memory(_project(chapters))
    text = memory["overall"]["text"]

    assert "林夏" in text
    assert "第 2 章《旧信》" in text
    assert "陈默" not in text  # 没出场的角色不该出现在总述里
    assert memory["overall"]["progress"]["chapterId"] == "c2"
    assert memory["overall"]["topCharacters"][0]["name"] == "林夏"


# ---------------------------------------------------------------- 时间衰减
# 这一节对应"谁**现在**还重要"：不加衰减时重要性是静态累加，
# 第 3 章退场的角色到第 40 章分数还是原样，于是这一层答不准这个问题。


def test_recency_factor_shape():
    """半衰：隔 0 章=1；隔一个半衰期≈0.625；永远不低于下限。"""
    from app.core.global_memory import RECENCY_FLOOR, RECENCY_HALF_LIFE, recency_factor

    assert recency_factor(0) == 1.0
    assert recency_factor(-3) == 1.0, "负的间隔不该出现，但要安全"
    half = recency_factor(int(RECENCY_HALF_LIFE))
    assert abs(half - (RECENCY_FLOOR + (1 - RECENCY_FLOOR) * 0.5)) < 1e-9
    # 单调不增
    vals = [recency_factor(n) for n in range(0, 60)]
    assert vals == sorted(vals, reverse=True)
    # 有下限：再久也不抹掉
    assert recency_factor(10**6) == RECENCY_FLOOR


def test_stale_character_falls_below_an_equally_present_character():
    """两人出场章数相同，但一个刚退场、一个还在——后者应当排在前面。"""
    chapters = [
        _ch("c1", [_d("chen", "我在。")]),
        _ch("c2", [_d("chen", "我还在。")]),
        _ch("c3", [_n("雨落在站台上。")]),
        _ch("c4", [_n("灯灭了一盏。")]),
        _ch("c5", [_n("站牌被雨泡花。")]),
        _ch("c6", [_d("lin", "嗯。")]),
        _ch("c7", [_d("lin", "知道了。")]),
    ]
    memory = build_global_memory(_project(chapters))
    characters = memory["volumes"][0]["characters"]
    names = [c["name"] for c in characters]
    assert names[0] == "林夏", names
    assert names[1] == "陈默", names

    chen = next(c for c in characters if c["name"] == "陈默")
    lin = next(c for c in characters if c["name"] == "林夏")
    # 出场章数一样，差别只来自衰减
    assert chen["appearedChapters"] == lin["appearedChapters"] == 2
    assert chen["chaptersSinceLast"] > 0
    assert lin["chaptersSinceLast"] == 0
    assert lin["recency"] == 1.0
    assert chen["recency"] < 1.0
    assert chen["score"] < lin["score"]


def test_score_is_base_times_recency_and_formula_explains_it():
    chapters = [
        _ch("c1", [_d("chen", "我在。")]),
        _ch("c2", [_n("雨落在站台上。")]),
        _ch("c3", [_n("灯灭了一盏。")]),
        _ch("c4", [_n("站牌被雨泡花。")]),
    ]
    memory = build_global_memory(_project(chapters))
    chen = memory["volumes"][0]["characters"][0]
    # 他只有一句台词，而章末钩子取"该章最后 4 行"→ 他同时是那一章的钩子主体，
    # 所以 base = 出场 1 章 + 钩子 1 次 × 权重
    assert chen["hookChapters"] == 1
    assert chen["baseScore"] == round(1 + HOOK_SUBJECT_WEIGHT, 2)
    assert chen["chaptersSinceLast"] == 3
    assert chen["score"] == round(chen["baseScore"] * chen["recency"], 2)
    # 算式中出现衰减项，作者能核对"为什么分数变了"
    assert "距上次出场 3 章" in chen["formula"]
    assert "衰减" in chen["formula"]


def test_formula_omits_decay_when_there_is_none():
    """没有衰减时算式与加衰减之前逐字相同：别让作者看一堆 ×1.00。"""
    chapters = [_ch("c1", [_d("lin", "嗯。")]), _ch("c2", [_d("lin", "知道了。")])]
    memory = build_global_memory(_project(chapters))
    lin = memory["volumes"][0]["characters"][0]
    assert lin["recency"] == 1.0
    assert "衰减" not in lin["formula"]
    # 期望值按返回值推导，不硬编码钩子次数（钩子规则一变这里就会假红/假绿）
    assert lin["formula"] == (
        f"出场 2 章 + 章末钩子 {lin['hookChapters']} 次 × {HOOK_SUBJECT_WEIGHT}"
        f" = {lin['baseScore']}"
    )


def test_stale_character_is_still_listed_not_erased():
    """衰减的是分量，不是存在：退场角色必须还在名单里（他可能回来）。"""
    chapters = [_ch(f"c{i}", [_n("雨落在站台上。")]) for i in range(1, 11)]
    chapters[0] = _ch("c1", [_d("chen", "我在。")])
    memory = build_global_memory(_project(chapters))
    names = [c["name"] for c in memory["volumes"][0]["characters"]]
    assert "陈默" in names
    chen = next(c for c in memory["volumes"][0]["characters"] if c["name"] == "陈默")
    assert chen["score"] > 0


def test_decay_is_relative_to_the_band_end_not_the_book_end():
    """分档时"多久没出场"要相对**本档末尾**算，不能拿全书最后一章去压早期的卷。"""
    chapters = [
        _ch("c1", [_d("lin", "嗯。")], volume_id="v1"),
        _ch("c2", [_n("雨落在站台上。")], volume_id="v1"),
        _ch("c3", [_n("灯灭了一盏。")], volume_id="v1"),
        _ch("c4", [_n("站牌被雨泡花。")], volume_id="v2"),
        _ch("c5", [_n("水面浮着一层光。")], volume_id="v2"),
    ]
    project = _project(
        chapters,
        volumes=[{"id": "v1", "title": "第一卷"}, {"id": "v2", "title": "第二卷"}],
    )
    memory = build_global_memory(project)
    first = next(v for v in memory["volumes"] if v["title"] == "第一卷")
    lin = next(c for c in first["characters"] if c["name"] == "林夏")
    # 林夏在 v1 的第 1 章出场，v1 共 3 章 → 距本档末尾 2 章，而不是距全书末尾 4 章
    assert lin["chaptersSinceLast"] == 2
