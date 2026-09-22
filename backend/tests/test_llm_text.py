"""模型输出「格式自愈」的测试。

真实来源：对照测试里同一句任务跑两次，一次干净、一次模型把整段当成转义字符串吐出来，
界面/正文里就出现了 40 处字面 `\\n`、`\\"` 和多余的 `renpy` 头。
这里的用例全部取自那次实际输出。
"""

from __future__ import annotations

from app.core.llm_text import (
    looks_escaped,
    normalize_model_text,
    strip_code_fence,
    unescape_model_text,
)

# 实测撞到的坏输出（Python 字面量里 \\n 表示"反斜杠 + n"这两个字符）
BROKEN = (
    'renpy\\n周屿 \\"末班车还有四分钟。\\"\\n\\n他没看表，看的是她。\\n\\n'
    '林夏 \\"嗯。\\"\\n\\n她把伞往他那边偏了半寸，又像是没动过。\\n'
)


def test_detects_the_real_broken_output():
    assert looks_escaped(BROKEN) is True
    assert BROKEN.count("\n") == 0  # 一个真换行都没有


def test_unescapes_newlines_and_quotes():
    out = unescape_model_text(BROKEN)
    assert "\\n" not in out
    assert '\\"' not in out
    assert out.startswith("renpy\n周屿")
    assert "他没看表，看的是她。" in out


def test_normalize_strips_language_tag_and_escapes_in_one_pass():
    out = normalize_model_text(BROKEN)
    assert out.startswith("周屿"), out[:20]
    assert "\\n" not in out
    assert "\\\"" not in out
    # 换行被真正还原成换行
    assert "末班车还有四分钟。\"" in out
    assert "\n\n他没看表" in out


def test_strips_markdown_fence():
    fenced = '```renpy\n周屿 "末班车还有四分钟。"\n\n她没说话。\n```'
    out = normalize_model_text(fenced)
    assert out.startswith("周屿")
    assert "```" not in out
    assert "renpy\n" not in out


def test_strips_fence_without_language():
    out = normalize_model_text("```\n旁白：雨还在下。\n```")
    assert out == "旁白：雨还在下。"


# ---------------------------------------------------------------------------
# 保守性：正常文本一个字都不能改
# ---------------------------------------------------------------------------


def test_normal_text_is_untouched():
    good = '周屿 "末班车还有四分钟。"\n\n他没看表，看的是她。\n\n林夏 "嗯。"'
    assert looks_escaped(good) is False
    assert normalize_model_text(good) == good


def test_single_line_prose_untouched():
    assert normalize_model_text("就把这句留着。") == "就把这句留着。"


def test_text_with_one_literal_backslash_n_is_left_alone():
    # 只有一处「反斜杠 n」，不足以判定整段被转义（可能是作者真在讲 \n）
    text = "代码里写 \\n 表示换行。"
    assert looks_escaped(text) is False
    assert normalize_model_text(text) == text


def test_code_block_that_is_intentionally_kept():
    # 说明性代码块（有正文在前后）不该被剥成空
    text = "这样写：\n\n```python\nprint(1)\n```\n\n就行了。"
    out = normalize_model_text(text)
    assert "print(1)" in out
    assert "这样写" in out and "就行了" in out


def test_escaped_but_valid_single_newline_pair():
    # 两处以上字面 \n 且无真换行 → 认定为被转义（短回复也会中招）
    text = "先写这句。\\n然后再写这句。\\n最后收尾。"
    assert looks_escaped(text) is True
    assert normalize_model_text(text) == "先写这句。\n然后再写这句。\n最后收尾。"


def test_unparseable_escapes_fall_back_to_manual_replace():
    # 裸引号让 json 解不动 → 走兜底替换，仍要把 \n 还原
    text = '她说\\n"你冷吗？"\\n然后就没了。'
    out = normalize_model_text(text)
    assert "\\n" not in out
    assert "你冷吗？" in out
    assert out.count("\n") == 2


def test_empty_input_safe():
    assert normalize_model_text("") == ""
    assert looks_escaped("") is False
    assert strip_code_fence("") == ""


# ---------------------------------------------------------------------------
# 真的走一遍 agent 管线（不然只测了工具函数，接线错了也发现不了）
# ---------------------------------------------------------------------------


def test_agent_message_is_normalized():
    import json as _json

    from app.core.agent import _parse_agent_json

    raw = _json.dumps(
        {"message": BROKEN, "actions": []}, ensure_ascii=False
    )
    message, actions = _parse_agent_json(raw)
    assert message.startswith("周屿"), message[:30]
    assert "\\n" not in message
    assert "\n\n他没看表" in message
    assert actions == []


def test_agent_script_action_text_is_normalized():
    from app.core.agent import _normalize_agent_actions

    actions = _normalize_agent_actions(
        [
            {
                "op": "append_script",
                "text": '```renpy\\n旁白：雨还在下。\\n\\n林夏 \\"嗯。\\"\\n```',
            }
        ]
    )
    assert len(actions) == 1
    text = actions[0]["text"]
    assert "```" not in text
    assert "\\n" not in text
    assert text.startswith("旁白：雨还在下。")


def test_agent_plain_text_fallback_is_normalized():
    # 模型没吐 JSON，而是直接回了一段带围栏的正文
    from app.core.agent import _parse_agent_json

    message, _ = _parse_agent_json('```renpy\\n旁白：雨还在下。\\n```')
    assert "```" not in message
    assert "旁白：雨还在下。" in message
