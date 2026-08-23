"""narrative_lint 边界集回归测试。

来源：`app eval` 边界用例（《深入理解 AI Agent》第7章"生产失败案例
沉淀为新回归用例"）——确保审稿对已知问题类型不再漏检。
"""

from __future__ import annotations

from app.core.harness.ai_flavor import lint_ai_flavor
from app.core.narrative_lint import (
    lint_has_blockers,
    lint_narrative_draft,
)


def _codes(text: str) -> list[str]:
    return [i.code for i in lint_narrative_draft(text)]


def _flavor_codes(text: str) -> list[str]:
    return [i.code for i in lint_ai_flavor(text)]


def test_multi_question_is_error():
    """同一角色本拍主动追问多次 → 一票否决级 error。"""
    text = (
        "周屿：「她在哪？」\n"
        "林夏：「我不知道。」\n"
        "周屿：「她到底在哪？」\n"
        "林夏：「说了不知道。」\n"
        "周屿：「那你总该知道她去哪了吧？」"
    )
    codes = _codes(text)
    assert "multi_question" in codes
    assert lint_has_blockers(lint_narrative_draft(text))


def test_qa_pingpong_is_error():
    """问→答→再问乒乓 → error。"""
    text = (
        "林夏：「你叫什么？」\n"
        "周屿：「周屿。」\n"
        "林夏：「为什么在这？」\n"
        "周屿：「等人。」\n"
        "林夏：「等谁？」\n"
        "周屿：「一个朋友。」"
    )
    codes = _codes(text)
    assert "qa_pingpong" in codes
    assert lint_has_blockers(lint_narrative_draft(text))


def test_exposition_dump_is_error():
    """刚认识的人讲解世界观/履历 → error。"""
    text = (
        "周屿：「这个组织成立于十年前，我是第七代负责人。"
        "我们的世界观建立在三个法则之上……」"
    )
    codes = _codes(text)
    assert "exposition" in codes
    assert lint_has_blockers(lint_narrative_draft(text))


def test_talk_heavy_warns_on_long_stranger_beat():
    """陌生人戏对白轮次偏多 → warn（非阻塞）。"""
    lines = []
    for i in range(9):
        lines.append(f"林夏：「第{i}句。」")
    text = "\n".join(lines)
    codes = _codes(text)
    assert "talk_heavy" in codes
    assert not lint_has_blockers(lint_narrative_draft(text))


def test_clean_dialogue_passes():
    """正常短对话：无 error 无 warn。"""
    text = (
        "林夏：「你在等人。」\n"
        "周屿：「嗯。末班车走了。」\n"
        "林夏：「那我陪你等一会儿。」"
    )
    issues = lint_narrative_draft(text)
    assert not lint_has_blockers(issues)
    assert not [i for i in issues if i.severity == "warn"]


def test_not_but_correction_is_error():
    """纠偏句式「不是A，是B」×2 → ai_not_but error。"""
    text = (
        "她的眼眶不是红了，是下雨淋的。"
        "他不是在生气，只是站得有点僵。"
        "这不是犹豫，是还没想好怎么开口。"
    )
    codes = _flavor_codes(text)
    assert "ai_not_but" in codes
    # 纠偏句是 error 级（ai_flavor 单独判），narrative 无阻塞
    err = [i for i in lint_ai_flavor(text) if i.severity == "error"]
    assert any(i.code == "ai_not_but" for i in err)


def test_telegram_dialogue_is_error():
    """分工电报腔对白 → ai_telegram_dialogue error。"""
    text = (
        "林夏：你主查。我主护。你探路。我断后。你开门。我望风。"
    )
    codes = _flavor_codes(text)
    assert "ai_telegram_dialogue" in codes
    err = [i for i in lint_ai_flavor(text) if i.severity == "error"]
    assert any(i.code == "ai_telegram_dialogue" for i in err)


def test_ai_cliche_warns():
    """同一套话重复 → ai_cliche warn。"""
    text = (
        "她微微一笑，雨停了。\n"
        "他微微一笑，递过伞。\n"
        "林夏微微一笑，什么都没说。"
    )
    codes = _flavor_codes(text)
    assert "ai_cliche" in codes


def test_otaku_shell_warns():
    """伪二次元标签入文 → otaku_shell warn。"""
    text = "她是个傲娇属性，好感度正在上升。"
    codes = _flavor_codes(text)
    assert "otaku_shell" in codes


def test_fragment_stack_warns():
    """极短段堆叠 → ai_fragment_stack warn。"""
    text = (
        "风。\n\n"
        "雨。\n\n"
        "灯。\n\n"
        "伞。\n\n"
        "影。\n\n"
        "然后他开口了。"
    )
    codes = _flavor_codes(text)
    assert "ai_fragment_stack" in codes


def test_guess_hedge_warns():
    """猜测腔（仿佛/似乎/莫名）单段≥2 → ai_guess_hedge warn。"""
    text = (
        "她仿佛在等什么人，又似乎并不着急。"
        "那种莫名的紧张，好像连她自己也说不上来为什么。"
    )
    codes = _flavor_codes(text)
    assert "ai_guess_hedge" in codes


def test_adverb_pile_warns():
    """软副词堆砌（缓缓/轻轻/微微）单段≥2 → ai_adverb_pile warn。"""
    text = (
        "他缓缓抬起头，轻轻放下伞，微微点了点头，"
        "静静地看着雨幕，默默收起了所有想说的话。"
    )
    codes = _flavor_codes(text)
    assert "ai_adverb_pile" in codes


def test_said_tag_warns():
    """「副词+说/道」标签单段≥2 → ai_said_tag warn。"""
    text = (
        "他冷冷地说：「你在等谁？」\n"
        "林夏低声说：「不关你事。」\n"
        "周屿苦笑说：「那我还是等吧。」"
    )
    codes = _flavor_codes(text)
    assert "ai_said_tag" in codes


def test_emotion_cliche_warns():
    """情绪陈词 → ai_emotion_cliche warn。"""
    text = "他心中一动，一股暖流涌了上来，有种说不清道不明的感觉。"
    codes = _flavor_codes(text)
    assert "ai_emotion_cliche" in codes


def test_single_hedge_or_adverb_not_flagged():
    """单处猜测词/软副词（正常表达）不误报。"""
    text = (
        "雨还在下，她轻轻抖了抖伞上的水。"
        "那个人好像真的走了。"
    )
    codes = _flavor_codes(text)
    assert "ai_guess_hedge" not in codes
    assert "ai_adverb_pile" not in codes


def test_terse_telegram_without_zhu_is_error():
    """无「主」字的电报短句（你查雨。我查人。…）≥6 → ai_telegram_dialogue error。"""
    text = (
        "林夏：你查雨。我查人。\n"
        "周屿：你问灯。我问影。\n"
        "林夏：你记名。我记脸。\n"
        "周屿：你锁门。我开窗。"
    )
    codes = _flavor_codes(text)
    assert "ai_telegram_dialogue" in codes
    err = [i for i in lint_ai_flavor(text) if i.severity == "error"]
    assert any(i.code == "ai_telegram_dialogue" for i in err)


def test_short_terse_dialogue_not_flagged():
    """少量短句对话（你说吧。我听着。）不误报为电报腔。"""
    text = "林夏：「你说吧。」周屿：「我听着。」林夏：「那你可别笑。」"
    codes = _flavor_codes(text)
    assert "ai_telegram_dialogue" not in codes


def test_adverb_spread_across_paragraphs_is_error():
    """软副词分散在各段、整篇 ≥6 处 → ai_adverb_pile error。"""
    text = (
        "伞骨轻轻磕在她肩上。\n\n"
        "林夏微微侧过头，没有回答。\n\n"
        "她缓缓从外套口袋里摸出一张照片。\n\n"
        "周屿的呼吸轻轻滞了一瞬。\n\n"
        "他沉默了一会儿，才缓缓开口。\n\n"
        "两个人静静站在同一把伞下。"
    )
    codes = _flavor_codes(text)
    assert "ai_adverb_pile" in codes
    err = [i for i in lint_ai_flavor(text) if i.severity == "error"]
    assert any(i.code == "ai_adverb_pile" for i in err)


def test_omniscient_spoil_is_error():
    """旁白标签直接揭示隐藏信息（凶手/尸体/计划）→ ai_omniscient_spoil error。"""
    text = (
        "旁白：周屿知道末班车永远不会来了。他口袋里揣着一份计划，"
        "那是他瞒着林夏的真相——他见过那具尸体，凶手是谁他早就知道。"
    )
    codes = _flavor_codes(text)
    assert "ai_omniscient_spoil" in codes
    err = [i for i in lint_ai_flavor(text) if i.severity == "error"]
    assert any(i.code == "ai_omniscient_spoil" for i in err)


def test_omniscient_marker_without_label_not_flagged():
    """无旁白/内心OS 标签时，即使出现秘密词也不误报（可能是角色已知信息）。"""
    text = "周屿把那份计划放回口袋，没有告诉任何人他昨晚见过谁。"
    codes = _flavor_codes(text)
    assert "ai_omniscient_spoil" not in codes
