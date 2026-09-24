"""长上下文政策：预算放宽到"能装就装"，但**不许静默失忆**。

作者的原话是判据："大多数用户想要的是达到最佳写作效果，如果写的差再耗费 token
重写也是浪费 token。但是长上下文可能导致的『失忆』问题也确实要解决。"

于是这里断言的是两条互相牵制的性质：

1. **能装就装**（旧预算 12000 字符是"省 token"年代的产物）：
   - 默认预算已放大，且按所选模型的窗口再夹一次（预设里有 32k 窗口的本地模型）；
   - 焦点章正文不再被写死的 5000 字符切掉——"接着写"最需要的就是本章正文；
   - 长程/全局记忆（抗失忆的主要手段）的单块上限同步放宽。
2. **不许静默**：任何截断/丢弃都必须留痕——
   - 正文截断的标记里写清省了多少字、以及用哪个工具能取回；
   - 超预算时**整块让位**（而不是把上下文从中间切成两半），并把省去的块写进
     提示词末尾的「篇幅说明」与 API 的 `included`；
   - 关键块（人设/关系/地点/bible/时间线/当前章/硬规则）永不因预算被丢。

另有一条**跨模块不变量**：上下文上限与 `llm_budget.PREFILL_MAX_BONUS` 必须成对，
否则"上下文放大"会重新引入用户报障过的假「后端没启动」（read timeout 覆盖
"预填充 + 生成"，预填充耗时随提示词线性增长）。
"""

from __future__ import annotations

from app.core import llm_budget
from app.core.agent_context import (
    _BUDGET_DROP_ORDER,
    _BUDGET_DROP_ORDER_LAST,
    _SECTION_ORDER,
    DEFAULT_CONTEXT_MAX_CHARS,
    MAX_CONTEXT_MAX_CHARS,
    MIN_CONTEXT_MAX_CHARS,
    _default_context_max_chars,
    build_agent_context,
    chapter_plain,
    context_budget_for_model,
)
from app.core.agent_tools import run_agent_tool
from app.core.project import normalize_project

# ---- 夹具 -------------------------------------------------------------------


def _project(*, focus_chars: int = 200, extra_chapters: int = 1):
    chapters = [
        {"id": "ch1", "title": "第一章", "prose": "雨停了。" * max(1, focus_chars // 4)},
    ]
    for i in range(extra_chapters):
        chapters.append(
            {"id": f"ch{i + 2}", "title": f"第{i + 2}章", "synopsis": f"第{i + 2}章的梗概"}
        )
    return normalize_project(
        {
            "id": "p-budget",
            "title": "预算",
            "bible": {"world": "沿海小镇，一年有两百天在下雨。"},
            "characters": [
                {"id": "c1", "displayName": "雨宫澪", "defineName": "mio", "voice": "短句"}
            ],
            "locations": [{"id": "l1", "name": "失物招领处"}],
            "loreEntries": [
                {"id": "e1", "title": "钟声", "body": "钟声一天只会响两次。", "keywords": ["钟声"]}
            ],
            "chapters": chapters,
        }
    )


def _context(project, **kw):
    return build_agent_context(
        project,
        chapterId="ch1",
        userMessage="接着写钟声那一段",
        task=kw.pop("task", "continue"),
        **kw,
    )


# ---- 1. 能装就装 ------------------------------------------------------------


def test_default_budget_is_larger_than_the_old_12000():
    """政策本身要可核对：默认预算是旧值（12000）的数倍。"""
    assert DEFAULT_CONTEXT_MAX_CHARS >= 40000
    assert _default_context_max_chars() >= 40000
    assert MIN_CONTEXT_MAX_CHARS < DEFAULT_CONTEXT_MAX_CHARS <= MAX_CONTEXT_MAX_CHARS


def test_configured_budget_is_clamped_to_supported_range(monkeypatch):
    """配错的值不能把预算变成 0 或天文数字（后者会撑爆窗口、超时也不够）。"""
    import app.config as config

    class _S:
        def __init__(self, v):
            self.agent_context_max_chars = v

    for raw, expected in (
        (0, DEFAULT_CONTEXT_MAX_CHARS),  # 未配置 → 用默认值
        (500, MIN_CONTEXT_MAX_CHARS),  # 太小 → 抬到下限
        (10_000_000, MAX_CONTEXT_MAX_CHARS),  # 太大 → 夹到上限
        (60000, 60000),  # 区间内 → 原样
    ):
        monkeypatch.setattr(config, "get_settings", lambda v=raw: _S(v))
        assert _default_context_max_chars() == expected, raw


def test_small_window_model_clamps_the_budget_but_unknown_model_does_not():
    """32k 窗口的本地模型不能被 48k 字符的预算撑爆；未知模型保持原行为。"""
    assert context_budget_for_model("qwen3:8b") < DEFAULT_CONTEXT_MAX_CHARS
    assert context_budget_for_model("deepseek-flash") == DEFAULT_CONTEXT_MAX_CHARS
    assert context_budget_for_model("some-custom-model") == DEFAULT_CONTEXT_MAX_CHARS


def test_focus_chapter_is_no_longer_clipped_to_five_thousand():
    """回归：一章两万字时，续写必须看得到**整章**（旧代码只给末尾 5000 字符）。"""
    long_body = "雨停了。" * 5000  # 20000 字
    ctx = _context(_project(focus_chars=20000))
    assert long_body[:40] in ctx.text, "当前章正文被截了"
    assert "未展开" not in ctx.text
    assert not any("当前章截断" in item for item in ctx.included), ctx.included


def test_truncated_focus_chapter_reports_how_much_is_missing():
    """真的装不下时：标记里写清省了多少字 + 用哪个工具取回。"""
    ctx = _context(_project(focus_chars=120000))  # 远超焦点章预算
    assert "未展开" in ctx.text
    assert "get_chapter" in ctx.text, "截断标记必须告诉模型/作者怎么取回"
    assert any("当前章截断" in item for item in ctx.included), ctx.included


def test_memory_layers_keep_their_raised_clip():
    """长程/全局记忆是抗失忆的主手段，单块上限同步放宽（旧值 3200/2400）。"""
    long_memory = "【长程记忆】" + "浆" * 7000
    global_memory = "【全局记忆】" + "球" * 5000
    ctx = _context(_project(), longChapterMemory=long_memory, globalMemory=global_memory)
    assert "浆" * 7000 in ctx.text, "长程记忆被截断回旧上限"
    assert "球" * 5000 in ctx.text, "全局记忆被截断回旧上限"


# ---- 2. 不许静默 ------------------------------------------------------------


def test_over_budget_drops_whole_sections_instead_of_slicing_the_middle():
    """超预算时按块让位，并如实说明；不再"从中间砍一刀"。"""
    # 填充字符要挑不会出现在提示词别处的（「参」会撞上「内部参考」里的那个字）
    docs = "囧" * 40000
    ctx = _context(_project(), referenceDocs=docs, maxChars=6000)
    assert "囧" not in ctx.text, "参考资料没让位"
    assert "上下文中段压缩" not in ctx.text, "仍在使用首尾切一刀的旧策略"
    assert any("篇幅省去:referenceDocs" in item for item in ctx.included), ctx.included
    # 「压缩」字样保留：前端/既有测试用它提示作者"这次被处理过"
    assert any("压缩" in item for item in ctx.included), ctx.included
    assert ctx.charsUsed <= 6000 + 200


def test_over_budget_notice_is_written_into_the_prompt_itself():
    """模型自己也要知道"哪块这次没带"，否则会把缺失当成"作者没写"。"""
    ctx = _context(_project(), referenceDocs="囧" * 40000, maxChars=6000)
    assert "篇幅说明" in ctx.text
    assert "已整块省去" in ctx.text
    # 取回方式要写出来（工具名必须在提示词里，模型才知道能取）
    assert "get_chapter" in ctx.text or "search_script" in ctx.text


def test_high_stakes_blocks_survive_a_tiny_budget():
    """人设/设定/当前章/硬规则永不为"量大但不决定怎么写"的块让位。"""
    ctx = _context(_project(focus_chars=3000), referenceDocs="囧" * 60000, maxChars=6000)
    for must in ("## Characters", "## Locations", "## 当前章节", "本次硬规则", "输出契约"):
        assert must in ctx.text, f"{must} 被挤掉了"


def test_drop_order_never_touches_protected_sections():
    """结构性断言：丢弃表与"关键块"集合不相交（比逐个行为测试更难被绕过）。"""
    droppable = set(_BUDGET_DROP_ORDER) | set(_BUDGET_DROP_ORDER_LAST)
    assert droppable <= set(_SECTION_ORDER), "丢弃表里出现了不存在的块"
    protected = {
        "meta",
        "rules",
        "characters",
        "relations",
        "locations",
        "bible",
        "timeline",
        "style",
        "focus",
        "selection",
    }
    assert not (droppable & protected), f"关键块进了丢弃表：{sorted(droppable & protected)}"
    # 两级顺序也不能重叠（否则第二级永远轮不到）
    assert not (set(_BUDGET_DROP_ORDER) & set(_BUDGET_DROP_ORDER_LAST))


def test_long_context_notice_only_appears_when_the_prompt_is_actually_long():
    small = _context(_project())
    assert "长上下文提醒" not in small.text, "短上下文里这句话是噪音"

    long_memory = "【长程记忆】" + "浆" * 20000
    big = _context(_project(focus_chars=20000), longChapterMemory=long_memory)
    assert "长上下文提醒" in big.text
    assert "本次硬规则" in big.text[-1200:], "硬规则仍要在末尾"
    assert any("长上下文提醒" in item for item in big.included)


# ---- 截断标记：给统计用的显式布尔量（不必解析中文串） ------------------------


def test_truncated_flag_is_false_for_a_small_context():
    ctx = _context(_project())
    assert ctx.truncated is False
    assert not any("截断" in item for item in ctx.included)


def test_truncated_flag_is_true_when_the_focus_chapter_is_cut():
    ctx = _context(_project(focus_chars=120000))
    assert ctx.truncated is True
    assert any("当前章截断" in item for item in ctx.included)


def test_truncated_flag_is_true_when_sections_are_dropped_by_budget():
    ctx = _context(_project(), referenceDocs="囧" * 40000, maxChars=6000)
    assert ctx.truncated is True
    assert any("篇幅省去" in item for item in ctx.included)


# ---- 3. 跨模块不变量：预算与超时必须成对 ------------------------------------


def test_context_ceiling_is_covered_by_the_prefill_allowance():
    """上限对应的预填充耗时不得超过 `PREFILL_MAX_BONUS`。

    这条是"上下文预算"和"超时预算"之间的**单一不变量**：谁单方面放宽上下文上限，
    谁就得同时放宽预填充加时（前端阶梯表也读那个数）。
    """
    allowance = llm_budget.prefill_allowance(MAX_CONTEXT_MAX_CHARS)
    assert allowance > 0, "上限大到不该再有预填充开销，说明两个数字已经脱钩"
    assert allowance <= llm_budget.PREFILL_MAX_BONUS + 1e-9
    # 默认预算也必须真的产生加时（否则等于没接上）
    assert llm_budget.effective_timeout(
        llm_budget.CHAT, prompt_chars=DEFAULT_CONTEXT_MAX_CHARS
    ) > llm_budget.CHAT


def test_prefill_allowance_is_monotonic_and_capped():
    assert llm_budget.prefill_allowance(0) == 0
    assert llm_budget.prefill_allowance(llm_budget.PREFILL_FREE_CHARS) == 0
    small = llm_budget.prefill_allowance(20_000)
    big = llm_budget.prefill_allowance(48_000)
    assert 0 < small < big
    assert llm_budget.prefill_allowance(10_000_000) == llm_budget.PREFILL_MAX_BONUS
    # 未知长度 / 非法值不改变旧行为
    assert llm_budget.prefill_allowance(None) == 0
    assert llm_budget.prefill_allowance("abc") == 0  # type: ignore[arg-type]


# ---- 4. 工具取回：检索必须真的取得到正文 ------------------------------------


def test_get_chapter_reads_prose_not_only_blocks():
    """回归：旧实现只读 `blocks`，纯正文工程里工具返回空——"取回"等于没取回。"""
    project = _project(focus_chars=2000)
    ok, text = run_agent_tool("get_chapter", {"chapterRef": "ch1"}, project=project)
    assert ok is True
    assert "雨停了。" in text
    assert "未找到" not in text


def test_get_chapter_default_limit_fits_a_normal_chapter():
    """默认上限必须够读一整章（旧默认 4000 字符会把它砍成半截）。"""
    body = "雨停了。" * 2250  # 9000 字
    project = normalize_project(
        {
            "id": "p-tool",
            "title": "工具",
            "chapters": [{"id": "ch1", "title": "第一章", "prose": body}],
        }
    )
    ok, text = run_agent_tool("get_chapter", {"chapterRef": "ch1"}, project=project)
    assert ok is True
    assert len(text) > 9000, f"默认上限把整章砍了：{len(text)}"
    assert text.count("雨停了。") == 2250


def test_search_script_sees_prose():
    project = _project(focus_chars=400)
    ok, text = run_agent_tool("search_script", {"query": "雨停了"}, project=project)
    assert ok is True
    assert "雨停了" in text


def test_chapter_plain_prefers_prose_and_falls_back_to_blocks():
    prose = normalize_project(
        {
            "id": "p1",
            "title": "t",
            "chapters": [
                {
                    "id": "c1",
                    "title": "第一章",
                    "prose": "正文优先。",
                    "blocks": [{"type": "narration", "text": "块里的旁白"}],
                }
            ],
        }
    ).chapters[0]
    assert chapter_plain(prose) == "正文优先。"

    blocks_only = normalize_project(
        {
            "id": "p2",
            "title": "t",
            "chapters": [
                {
                    "id": "c1",
                    "title": "第一章",
                    "blocks": [{"type": "narration", "text": "块里的旁白"}],
                }
            ],
        }
    ).chapters[0]
    assert "块里的旁白" in chapter_plain(blocks_only)
