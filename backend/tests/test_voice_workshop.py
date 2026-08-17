"""Unit tests: character workshop — mind-pack synthesis & character chat (LLM mocked)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx

from app.core.ai import DeepSeekConfig
from app.core.character_voice.corpus import make_sample
from app.core.character_voice.synthesize import synthesize_voice_mind
from app.core.character_voice.workshop_chat import workshop_chat
from app.core.demo import create_demo_project


def _cfg() -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="sk-test-not-real", model="mock")


def _response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}], "model": "mock"},
    )


def _project_with_corpus(n: int = 6):
    p = create_demo_project()
    char = p.characters[0]
    corpus = []
    for i in range(n):
        corpus.append(
            make_sample(
                scenario=f"sc{i % 5}",
                scenario_label=f"场景{i % 5}",
                axis=None,
                hypothesis=None,
                lines=[{"speaker": "self", "text": f"第{i}句对白示例。"}],
                source="preference",
            )
        )
    char.voiceCorpus = corpus
    return p, char


def _mind_markdown() -> str:
    return "\n".join(
        [
            "## 视角一句话",
            "就算天塌下来，也先把手里的伞撑好。",
            "",
            "## 心智模型",
            "- 遇事先顾眼前人",
            "## 表达 DNA",
            "- 短句、白描",
            "## 决策启发式",
            "- 能省则省",
            "## 审阅时问什么",
            "- 这句像不像他？",
            "## 反模式",
            "- 说教",
            "## 诚实边界",
            "- 非真人，服从设定",
        ]
    )


def test_synthesize_extracts_voice_from_perspective_section():
    p, _ = _project_with_corpus()

    async def _run():
        with patch(
            "app.core.llm_http.chat_completions",
            new_callable=AsyncMock,
            return_value=_response(_mind_markdown()),
        ) as mocked:
            result = await synthesize_voice_mind(_cfg(), p, character_id=p.characters[0].id)
            mocked.assert_awaited_once()
            return result

    result = asyncio.run(_run())
    assert result["markdown"].startswith("## 视角一句话")
    # suggestedVoice comes from the 视角一句话 section, not the first short line
    assert result["suggestedVoice"] == "就算天塌下来，也先把手里的伞撑好。"
    assert "scriptAnchorsUsed" in result
    assert result["ready"] is True


def test_synthesize_requires_corpus():
    p = create_demo_project()
    p.characters[0].voiceCorpus = []

    async def _run():
        return await synthesize_voice_mind(_cfg(), p, character_id=p.characters[0].id)

    try:
        asyncio.run(_run())
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "语料" in str(exc)


def test_user_chat_returns_action_and_mood():
    p, _ = _project_with_corpus()
    char = p.characters[0]
    # satisfy the mind-pack requirement
    char.voiceMind = _mind_markdown()
    payload = {"reply": "这伞你拿着。", "action": "把伞塞进对方手里", "mood": "不耐烦"}

    async def _run():
        with patch(
            "app.core.llm_http.chat_completions",
            new_callable=AsyncMock,
            return_value=_response(json.dumps(payload, ensure_ascii=False)),
        ):
            return await workshop_chat(
                _cfg(), p, character_id=char.id, mode="user", message="下雨了"
            )

    result = asyncio.run(_run())
    assert result["reply"] == "这伞你拿着。"
    assert result["action"] == "把伞塞进对方手里"
    assert result["mood"] == "不耐烦"


def test_duo_chat_returns_lines_with_action_mood():
    p, _ = _project_with_corpus()
    focus = p.characters[0]
    partner = p.characters[1]
    focus.voiceMind = _mind_markdown()
    partner.voiceMind = _mind_markdown()
    payload = {
        "lines": [
            {
                "speakerId": focus.id,
                "speakerName": focus.displayName,
                "text": "你先走。",
                "action": "别过头",
                "mood": "平静",
            },
            {
                "speakerId": partner.id,
                "speakerName": partner.displayName,
                "text": "我不走。",
            },
        ]
    }

    async def _run():
        with patch(
            "app.core.llm_http.chat_completions",
            new_callable=AsyncMock,
            return_value=_response(json.dumps(payload, ensure_ascii=False)),
        ):
            return await workshop_chat(
                _cfg(),
                p,
                character_id=focus.id,
                mode="duo",
                message="站台广播响了",
                partner_id=partner.id,
            )

    result = asyncio.run(_run())
    assert result["mode"] == "duo"
    assert len(result["lines"]) == 2
    assert result["lines"][0]["action"] == "别过头"
    assert result["lines"][0]["mood"] == "平静"
    assert result["lines"][1]["action"] == ""
