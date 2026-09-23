"""声线指纹量具的测试。

这里的断言分两类，都非常关键：
1. **不能误报**：作者自己写的另一半台词，必须判为正常（否则量具一上线就在喊狼来了）。
2. **必须抓到**：把"寡言克制"的角色突然写成长篇大论，必须判为 drift。

另外测口癖挖掘的判别度：不能用"出现得多"当口癖——主角天然说得最多，
真正该看的是"占比比别人高"。
"""

from __future__ import annotations

from app.core.project import normalize_project
from app.core.voice_fingerprint import (
    FEATURE_WEIGHTS,
    analyze_voices,
    build_voice_profile,
    extract_features,
    gram_counts,
    mine_signature_phrases,
    profile_distance,
    score_voice,
)

# ------------------------------------------------------------------ 夹具工具


def _d(char_id: str, text: str) -> dict:
    return {"type": "dialogue", "characterId": char_id, "text": text}


def _ch(cid: str, blocks: list) -> dict:
    return {"id": cid, "title": cid, "blocks": blocks}


def _project(chapters: list, characters: list | None = None):
    return normalize_project(
        {
            "id": "p1",
            "title": "声线测试",
            "characters": characters
            or [
                {"id": "lin", "defineName": "lin", "displayName": "林夏"},
                {"id": "zhou", "defineName": "zhou", "displayName": "周屿"},
            ],
            "chapters": chapters,
        }
    )


#: 寡言克制：短句、几乎没有语气助词与逗号。
LACONIC = [
    "嗯。",
    "不要。",
    "走。",
    "知道。",
    "是吗。",
    "好。",
    "不。",
    "随便。",
    "算了。",
    "行。",
    "不用。",
    "没事。",
    "等。",
    "看。",
    "别。",
    "嗯。",
    "可以。",
    "不必。",
]

#: 话密：长句、逗号多、语气助词多。
VERBOSE = [
    "我今天在车站等了三个小时呢，结果什么也没等到，真是的。",
    "你要是不来的话，我就一直等下去哦，反正我也没什么别的地方可以去嘛。",
    "说起来啊，那天的雨其实挺大的，我站在檐下看了很久，心里有点乱。",
    "你别误会，我不是怪你，我只是觉得，有些事情还是说清楚比较好嘛。",
    "后来我想了很久，觉得大概是我太着急了，你也需要时间的。",
    "所以啊，我今天特意早点来，想着总能碰上你，结果还是没碰上呢。",
    "算了算了，不说这些了，你吃饭了吗，要不要一起去吃点东西呀。",
    "我最近总是做梦，梦见那趟末班车，梦见站台上没有一个人呢。",
    "你别笑我，我知道这听起来很傻，可是我真的这么想过的。",
    "总之呢，你什么时候有空，我们就什么时候再说，我都可以的呀。",
]


# ------------------------------------------------------------------ 特征层


def test_features_separate_curt_from_flowing():
    curt = extract_features("嗯。")
    flowing = extract_features("我今天在车站等了三个小时呢，结果什么也没等到，真是的。")
    assert curt["utteranceLen"] < 4
    assert flowing["utteranceLen"] > 20
    assert flowing["commas"] >= 1
    assert flowing["softParticle"] == 1.0
    assert curt["softParticle"] == 0.0


def test_repeated_punctuation_is_collapsed_in_length():
    """`……` 与 `。` 是同一个标点习惯，不该因为字符数被判成"话说得长"。"""
    assert extract_features("……")["utteranceLen"] == 1.0
    assert extract_features("！！！")["utteranceLen"] == 1.0
    assert extract_features("嗯。")["hasEllipsis"] == 0.0
    assert extract_features("嗯……")["hasEllipsis"] == 1.0


def test_question_detection_covers_cjk_and_ascii():
    assert extract_features("你走吗")["isQuestion"] == 1.0
    assert extract_features("你走？")["isQuestion"] == 1.0
    assert extract_features("你走?")["isQuestion"] == 1.0
    assert extract_features("你走。")["isQuestion"] == 0.0


def test_feature_vector_covers_every_weighted_key():
    vec = extract_features("随便吧。")
    assert set(FEATURE_WEIGHTS).issubset(vec.keys())


# ------------------------------------------------------------------ 画像与校准


def test_insufficient_sample_is_refused_not_guessed():
    project = _project([_ch("ch1", [_d("lin", "嗯。"), _d("lin", "走。"), _d("lin", "好。")])])
    profile = build_voice_profile(project, "lin")
    assert profile["ready"] is False
    assert score_voice(profile, ["嗯。"])["ready"] is False
    assert "样本不足" in score_voice(profile, ["嗯。"])["reason"]


def test_calibration_thresholds_are_monotonic():
    blocks = [_d("lin", t) for t in LACONIC]
    profile = build_voice_profile(_project([_ch("ch1", blocks)]), "lin")
    cal = profile["calibration"]
    assert profile["ready"] is True
    assert cal["calibrated"] is True
    assert cal["p50"] <= cal["p90"] <= cal["p975"]


def test_author_own_held_out_lines_are_not_flagged():
    """最重要的一条：作者自己写的另一半台词，不能被判成跑偏。"""
    half = len(LACONIC) // 2
    train = _project([_ch("ch1", [_d("lin", t) for t in LACONIC[:half]])])
    profile = build_voice_profile(train, "lin")
    result = score_voice(profile, LACONIC[half:])
    assert result["ready"] is True
    assert result["level"] == "ok", result["reasons"]


def test_laconic_character_written_verbose_is_flagged_as_drift():
    blocks = [_d("lin", t) for t in LACONIC] + [_d("zhou", t) for t in VERBOSE]
    project = _project([_ch("ch1", blocks)])
    profile = build_voice_profile(project, "lin")
    long_line = "我今天在车站等了三个小时呢，结果什么也没等到，真是的，你要是不来的话我就一直等下去哦。"
    result = score_voice(profile, [long_line, long_line, long_line])
    assert result["level"] == "drift", result
    assert result["drift"] > result["driftThreshold"]
    assert any("长度" in r or "句长" in r for r in result["reasons"])
    assert result["flaggedLines"]


def test_verbose_character_written_curt_is_also_flagged():
    """反向也要成立，否则这量具只是在惩罚"话说得多"。"""
    blocks = [_d("lin", t) for t in LACONIC] + [_d("zhou", t) for t in VERBOSE]
    profile = build_voice_profile(_project([_ch("ch1", blocks)]), "zhou")
    result = score_voice(profile, ["嗯。", "走。", "不。"])
    assert result["level"] in ("watch", "drift"), result


# ------------------------------------------------------------------ 口癖挖掘


def test_catchphrase_is_mined_for_the_character_who_owns_it():
    a = [_d("lin", f"真是的。第{i}次了。") for i in range(12)]
    b = [_d("zhou", f"我知道了。第{i}次。") for i in range(12)]
    project = _project([_ch("ch1", a + b)])
    profile = build_voice_profile(project, "lin")
    phrases = [p["phrase"] for p in profile["signaturePhrases"]]
    assert any("真是的" in p for p in phrases), phrases


def test_common_phrase_is_not_a_catchphrase_even_for_the_main_speaker():
    """主角天然说得最多；判别度必须按"占比"算，不能按"绝对次数"算。"""
    a = [_d("lin", f"的时候我想了想{i}。") for i in range(40)]
    others = []
    for name in ("zhou", "chen", "xu"):
        others.extend([_d(name, f"的时候我看了看{i}。") for i in range(4)])
    project = _project(
        [
            _ch("ch1", a + others),
        ],
        characters=[
            {"id": "lin", "defineName": "lin", "displayName": "林夏"},
            {"id": "zhou", "defineName": "zhou", "displayName": "周屿"},
            {"id": "chen", "defineName": "chen", "displayName": "陈默"},
            {"id": "xu", "defineName": "xu", "displayName": "徐白"},
        ],
    )
    profile = build_voice_profile(project, "lin")
    phrases = [p["phrase"] for p in profile["signaturePhrases"]]
    assert not any("的时候" in p for p in phrases), phrases


def test_character_name_is_not_mined_as_its_own_catchphrase():
    a = [_d("lin", f"林夏。第{i}次。") for i in range(12)]
    b = [_d("zhou", f"知道了。第{i}次。") for i in range(12)]
    project = _project([_ch("ch1", a + b)])
    profile = build_voice_profile(project, "lin")
    phrases = [p["phrase"] for p in profile["signaturePhrases"]]
    assert not any("林夏" in p for p in phrases), phrases


def test_gram_counts_are_sentence_scoped():
    """跨句拼 gram 会造出"我。你"这种不存在的组合，必须逐句取。"""
    counts, slots = gram_counts(["我。你。"])
    assert "我你" not in counts
    assert slots == 0  # 清洗后每句只剩 1 字，构不成 2-gram


def test_mine_signature_phrases_respects_min_count():
    counts = {"真是的": 1}
    assert mine_signature_phrases(counts, 100, [({}, 100)], min_count=3) == []


# ------------------------------------------------------------------ 角色间距离


def test_identical_styles_are_flagged_as_confusable():
    a = [_d("lin", t) for t in LACONIC]
    b = [_d("zhou", t) for t in LACONIC]
    c = [_d("chen", t) for t in VERBOSE]
    project = _project(
        [_ch("ch1", a + b + c)],
        characters=[
            {"id": "lin", "defineName": "lin", "displayName": "林夏"},
            {"id": "zhou", "defineName": "zhou", "displayName": "周屿"},
            {"id": "chen", "defineName": "chen", "displayName": "陈默"},
        ],
    )
    report = analyze_voices(project)
    pairs = {(p["a"], p["b"]) for p in report["confusablePairs"]}
    assert ("林夏", "周屿") in pairs or ("周屿", "林夏") in pairs
    lin = next(c for c in report["characters"] if c["displayName"] == "林夏")
    chen = next(c for c in report["characters"] if c["displayName"] == "陈默")
    assert profile_distance(
        build_voice_profile(project, "lin"), build_voice_profile(project, "chen")
    ) > 0.15, (lin, chen)


# ------------------------------------------------------------------ 项目级分析


def test_drift_chapter_is_reported():
    """第 2 章把寡言角色写成长篇大论 → 该章必须出现在 driftChapters 里。"""
    ch1 = [_d("lin", t) for t in LACONIC]
    ch2 = [
        _d("lin", "我今天在车站等了三个小时呢，结果什么也没等到，真是的。"),
        _d("lin", "你要是不来的话，我就一直等下去哦，反正我也没什么地方可以去嘛。"),
        _d("lin", "说起来啊，那天的雨其实挺大的，我站在檐下看了很久，心里有点乱。"),
        _d("lin", "总之呢，你什么时候有空，我们就什么时候再说，我都可以的呀。"),
    ]
    report = analyze_voices(_project([_ch("ch1", ch1), _ch("ch2", ch2)]))
    lin = next(c for c in report["characters"] if c["characterId"] == "lin")
    assert "ch2" in lin["driftChapters"], lin
    assert lin["chapters"][0]["chapterId"] == "ch2"


def test_short_chapters_are_skipped_not_scored():
    """一章只说一两句时不评估该章：样本太小，分数没有意义。"""
    ch1 = [_d("lin", t) for t in LACONIC]
    ch2 = [_d("lin", "嗯。")]
    report = analyze_voices(_project([_ch("ch1", ch1), _ch("ch2", ch2)]))
    lin = next(c for c in report["characters"] if c["characterId"] == "lin")
    assert all(row["chapterId"] != "ch2" for row in lin["chapters"])


def test_dialogue_inside_branch_bodies_is_counted():
    """写在菜单选项正文里的台词也是台词，统计里不能凭空消失。"""
    blocks = [
        {"type": "label", "id": "start", "name": "start"},
        {
            "type": "menu",
            "id": "m1",
            "choices": [
                {"text": "留下", "blocks": [_d("lin", "嗯。")]},
                {"text": "离开", "blocks": [_d("lin", "走。")]},
            ],
        },
    ]
    profile = build_voice_profile(_project([_ch("ch1", blocks)]), "lin")
    assert profile["utteranceCount"] == 2


def test_analyze_voices_on_empty_project_is_safe():
    project = normalize_project({"id": "p1", "title": "空"})
    report = analyze_voices(project)
    assert report["characters"] == []
    assert report["closestPairs"] == []
