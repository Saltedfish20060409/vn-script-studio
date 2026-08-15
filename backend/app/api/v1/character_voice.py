"""Character voice corpus API — generate / accept / reject / synthesize / extract / export."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.ai import DeepSeekConfig
from app.core.character_voice import (
    build_nuwa_export_markdown,
    corpus_stats,
    extract_dialogue_candidates,
    find_character,
    generate_interview_round,
    generate_long_scene,
    generate_voice_variants,
    list_axis_tags,
    list_scenarios,
    parse_mind_import,
    patch_character,
    sample_count,
    synthesize_voice_mind,
    workshop_chat,
)
from app.core.character_voice.corpus import append_prefer_note, make_sample
from app.core.project import touch_project
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.projects import (
    get_owned_project,
    project_to_dict,
    row_to_vn,
    server_llm_credentials,
    sync_row_from_vn,
)

router = APIRouter(tags=["character-voice"])

_VALID_SOURCES = {
    "preference",
    "import",
    "script_extract",
    "scene",
    "interview",
    "manual",
    "chat",
}


def _cfg(settings: Settings) -> DeepSeekConfig:
    creds = server_llm_credentials(settings)
    if not creds["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置",
        )
    return DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )


def _char_or_404(vn, character_id: str):
    try:
        return find_character(vn, character_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class GenerateIn(BaseModel):
    scenario_id: str = ""
    scenario_prompt: str = ""
    scenario_label: str = ""
    extra_constraints: str = ""
    kind: str = "preference"  # preference | scene | interview
    turns: int = 10
    question: str = ""
    axis_tags: List[str] = Field(default_factory=list)

class AcceptIn(BaseModel):
    scenario_id: str = ""
    scenario_label: str = ""
    scenario_prompt: str = ""
    axis: Optional[str] = None
    hypothesis: Optional[str] = None
    lines: List[Dict[str, str]] = Field(default_factory=list)
    user_note: Optional[str] = None
    preference_note: str = ""
    rejected_summary: Optional[str] = None
    source: str = "preference"


class RejectIn(BaseModel):
    note: str = ""
    hypotheses: List[str] = Field(default_factory=list)


class SynthesizeIn(BaseModel):
    force: bool = False
    apply_voice_summary: bool = True


class ExtractAcceptIn(BaseModel):
    indices: List[int] = Field(default_factory=list)
    samples: Optional[List[Dict[str, Any]]] = None


class ImportMindIn(BaseModel):
    markdown: str
    replace_corpus: bool = False


class WorkshopChatIn(BaseModel):
    mode: str = "user"  # user | duo
    message: str = ""
    partner_id: Optional[str] = None
    history: List[Dict[str, str]] = Field(default_factory=list)


def _stats_payload(char) -> Dict[str, Any]:
    st = corpus_stats(char)
    return {
        **st,
        "voiceCorpus": [s.model_dump(mode="json") for s in (char.voiceCorpus or [])],
        "voiceMind": char.voiceMind,
        "voiceRejectNotes": char.voiceRejectNotes or [],
        "voicePreferNotes": char.voicePreferNotes or [],
    }


@router.get("/voice/scenarios")
async def get_voice_scenarios():
    return {"scenarios": list_scenarios()}


@router.get("/voice/axis-tags")
async def get_voice_axis_tags():
    return {"tags": list_axis_tags()}


@router.get("/projects/{project_id}/characters/{character_id}/voice")
async def get_character_voice_state(
    project_id: str,
    character_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    char = _char_or_404(vn, character_id)
    return {
        "characterId": char.id,
        "displayName": char.displayName,
        "voice": char.voice,
        "bio": char.bio,
        **_stats_payload(char),
        "scenarios": list_scenarios(),
        "axisTags": list_axis_tags(),
    }


@router.post("/projects/{project_id}/characters/{character_id}/voice/generate")
async def generate_character_voice_samples(
    project_id: str,
    character_id: str,
    body: GenerateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    _char_or_404(vn, character_id)
    cfg = _cfg(settings)
    kind = (body.kind or "preference").strip()
    try:
        if kind == "scene":
            return await generate_long_scene(
                cfg,
                vn,
                character_id=character_id,
                scenario_id=body.scenario_id,
                scenario_prompt=body.scenario_prompt,
                scenario_label=body.scenario_label,
                extra_constraints=body.extra_constraints,
                turns=body.turns,
            )
        if kind == "interview":
            return await generate_interview_round(
                cfg,
                vn,
                character_id=character_id,
                question=body.question,
                extra_constraints=body.extra_constraints,
                axis_tags=body.axis_tags,
            )
        return await generate_voice_variants(
            cfg,
            vn,
            character_id=character_id,
            scenario_id=body.scenario_id,
            scenario_prompt=body.scenario_prompt,
            scenario_label=body.scenario_label,
            extra_constraints=body.extra_constraints,
            axis_tags=body.axis_tags,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/characters/{character_id}/voice/accept")
async def accept_character_voice_sample(
    project_id: str,
    character_id: str,
    body: AcceptIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    char = _char_or_404(vn, character_id)
    if not body.lines:
        raise HTTPException(status_code=400, detail="lines 不能为空")
    if any("请重新生成" in str(ln.get("text") or "") for ln in body.lines if isinstance(ln, dict)):
        raise HTTPException(status_code=400, detail="该变体未生成完整（占位内容），不能入库；请重新生成")
    src = body.source if body.source in _VALID_SOURCES else "preference"
    prefer = (body.preference_note or body.user_note or "").strip()
    sample = make_sample(
        scenario=body.scenario_id,
        scenario_label=body.scenario_label or body.scenario_id,
        axis=body.axis,
        hypothesis=body.hypothesis,
        lines=body.lines,
        source=src,
        user_note=prefer or None,
        rejected_summary=body.rejected_summary,
        scenario_prompt=body.scenario_prompt or "",
    )
    corpus = list(char.voiceCorpus or [])
    corpus.append(sample)
    updates: Dict[str, Any] = {"voiceCorpus": corpus}
    if prefer:
        updates["voicePreferNotes"] = append_prefer_note(char, prefer)
    vn = patch_character(vn, character_id, **updates)
    vn = touch_project(vn)
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    out = row_to_vn(row)
    c = find_character(out, character_id)
    st = corpus_stats(c)
    return {
        "sample": sample.model_dump(mode="json"),
        **{k: st[k] for k in ("sampleCount", "scenarioCoverage", "volumeChars", "sceneCount", "interviewCount", "readyForMind")},
        "voicePreferNotes": c.voicePreferNotes or [],
        "project": project_to_dict(out),
    }


@router.post("/projects/{project_id}/characters/{character_id}/voice/reject")
async def reject_character_voice_round(
    project_id: str,
    character_id: str,
    body: RejectIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    char = _char_or_404(vn, character_id)
    notes = list(char.voiceRejectNotes or [])
    bit = (body.note or "").strip()
    if not bit and body.hypotheses:
        bit = "不选：" + " / ".join(h.strip() for h in body.hypotheses if h.strip())[:200]
    if bit:
        notes.append(bit)
        notes = notes[-20:]
    vn = patch_character(vn, character_id, voiceRejectNotes=notes)
    vn = touch_project(vn)
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    out = row_to_vn(row)
    return {
        "voiceRejectNotes": find_character(out, character_id).voiceRejectNotes or [],
        "project": project_to_dict(out),
    }


@router.delete("/projects/{project_id}/characters/{character_id}/voice/samples/{sample_id}")
async def delete_character_voice_sample(
    project_id: str,
    character_id: str,
    sample_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    char = _char_or_404(vn, character_id)
    corpus = [s for s in (char.voiceCorpus or []) if s.id != sample_id]
    if len(corpus) == len(char.voiceCorpus or []):
        raise HTTPException(status_code=404, detail="样本不存在")
    vn = patch_character(vn, character_id, voiceCorpus=corpus)
    vn = touch_project(vn)
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    out = row_to_vn(row)
    c = find_character(out, character_id)
    return {
        "sampleCount": sample_count(c),
        "project": project_to_dict(out),
    }


@router.post("/projects/{project_id}/characters/{character_id}/voice/synthesize")
async def synthesize_character_voice_mind(
    project_id: str,
    character_id: str,
    body: SynthesizeIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    _char_or_404(vn, character_id)
    cfg = _cfg(settings)
    try:
        result = await synthesize_voice_mind(
            cfg, vn, character_id=character_id, force=body.force
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    updates: Dict[str, Any] = {"voiceMind": result["markdown"]}
    if body.apply_voice_summary and result.get("suggestedVoice"):
        char = find_character(vn, character_id)
        if not (char.voice or "").strip():
            updates["voice"] = result["suggestedVoice"]
    vn = patch_character(vn, character_id, **updates)
    vn = touch_project(vn)
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    out = row_to_vn(row)
    return {
        **result,
        "project": project_to_dict(out),
    }


@router.post("/projects/{project_id}/characters/{character_id}/voice/extract")
async def extract_character_voice_from_script(
    project_id: str,
    character_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    _char_or_404(vn, character_id)
    return extract_dialogue_candidates(vn, character_id=character_id)


@router.post("/projects/{project_id}/characters/{character_id}/voice/extract/accept")
async def accept_extracted_voice_samples(
    project_id: str,
    character_id: str,
    body: ExtractAcceptIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    char = _char_or_404(vn, character_id)
    extracted = extract_dialogue_candidates(vn, character_id=character_id)
    candidates = extracted["candidates"]
    to_add: List[Dict[str, Any]] = []
    if body.samples:
        to_add = body.samples
    else:
        for i in body.indices:
            if 0 <= i < len(candidates):
                to_add.append(candidates[i])
    if not to_add:
        raise HTTPException(status_code=400, detail="未选择任何对白")

    corpus = list(char.voiceCorpus or [])
    added = []
    for row_c in to_add:
        sample = make_sample(
            scenario=str(row_c.get("scenario") or "script"),
            scenario_label=str(row_c.get("scenarioLabel") or "剧本抽取"),
            axis=None,
            hypothesis=None,
            lines=row_c.get("lines") or [],
            source="script_extract",
        )
        if not sample.lines:
            continue
        corpus.append(sample)
        added.append(sample.model_dump(mode="json"))

    vn = patch_character(vn, character_id, voiceCorpus=corpus)
    vn = touch_project(vn)
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    out = row_to_vn(row)
    c = find_character(out, character_id)
    st = corpus_stats(c)
    return {
        "added": added,
        **{k: st[k] for k in ("sampleCount", "scenarioCoverage", "volumeChars", "readyForMind")},
        "project": project_to_dict(out),
    }


@router.post("/projects/{project_id}/characters/{character_id}/workshop/chat")
async def workshop_character_chat(
    project_id: str,
    character_id: str,
    body: WorkshopChatIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    _char_or_404(vn, character_id)
    cfg = _cfg(settings)
    try:
        return await workshop_chat(
            cfg,
            vn,
            character_id=character_id,
            mode=(body.mode or "user").strip() or "user",
            message=body.message,
            partner_id=body.partner_id,
            history=body.history,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/characters/{character_id}/voice/export")
async def export_character_voice_pack(
    project_id: str,
    character_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    _char_or_404(vn, character_id)
    try:
        return build_nuwa_export_markdown(vn, character_id=character_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/characters/{character_id}/voice/export.md",
    response_class=PlainTextResponse,
)
async def export_character_voice_pack_md(
    project_id: str,
    character_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    _char_or_404(vn, character_id)
    pack = build_nuwa_export_markdown(vn, character_id=character_id)
    return PlainTextResponse(
        pack["markdown"],
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{pack["filename"]}"',
        },
    )


@router.post("/projects/{project_id}/characters/{character_id}/voice/import-mind")
async def import_character_voice_mind(
    project_id: str,
    character_id: str,
    body: ImportMindIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    char = _char_or_404(vn, character_id)
    try:
        parsed = parse_mind_import(body.markdown, fallback_name=char.displayName)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updates: Dict[str, Any] = {"voiceMind": parsed["markdown"]}
    if body.replace_corpus:
        updates["voiceCorpus"] = []
    vn = patch_character(vn, character_id, **updates)
    vn = touch_project(vn)
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    out = row_to_vn(row)
    return {
        "imported": {"id": parsed.get("id"), "name": parsed.get("name"), "kind": parsed.get("kind")},
        "voiceMind": find_character(out, character_id).voiceMind,
        "project": project_to_dict(out),
    }
