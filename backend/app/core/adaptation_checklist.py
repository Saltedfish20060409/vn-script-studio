"""小说 → 视觉小说的**改编检查表**（离线、零模型调用、只报结构上可核对的）。

## 依据（2026-09 核对，见 `docs/references.md` 的「视觉小说 / 轻小说实务（参考层）」）

- 《文字冒险游戏设计中的沉浸式体验研究与实践》（学位论文）：VN 的沉浸感来自
  "玩家操作故事 + 对白与演出推进"——成段叙述在 VN 里会变成**一屏文字**。
- 《剧情交互式游戏的叙事研究》：剧情交互式游戏的叙事结构（分支与收束）与纯文本不同，
  改编时要先问"这一段由谁推进、玩家能不能插手"。
- 《视觉小说叙事逻辑的根源与变迁》（新闻传播 2022(15)）：**kinetic（无选项）也是合法形态**
  ——所以本模块**不把"没有选项"当问题**，只报事实。
- 『ノベルゲームのシナリオ作成技法』：AVG 剧本实务——场景切分、演出与选项位置。
- 『キャラクター小説の作り方』（大塚英志）：角色先于情节——改编成 VN 时，
  每个出场角色都要有**可演的说话方式**，否则演出撑不住。

## 这里**不**做的事

- 不评"这段写得好不好"、不预测"改编成游戏会不会好玩"（需要真人，见 Art or Artifice?）。
- 不把"没有分支""没有分场标记"直接当缺陷：先如实报事实与数量，再说"改编时要注意什么"。
- 不动正文：这是一张**检查表**，给作者照着改。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from app.core.agent_context import chapter_plain
from app.domain.types import VnProject

#: 成段叙述的阈值（字符）：超过它的段落，在 VN 里就是"一屏文字"。
TEXT_WALL_CHARS = 300
#: 对白占比低于这个值的章，在 VN 里会显得"一直在读旁白"。
LOW_DIALOGUE_RATIO = 0.20
#: 逐项证据里最多列几个样本（界面上够看，也不至于刷屏）。
MAX_SAMPLES = 8


def _paragraphs(text: str) -> List[str]:
    return [p.strip() for p in (text or "").split("\n") if p.strip()]


def _is_dialogue_line(line: str) -> bool:
    """对白行：以中文引号/直角引号开头（与 `novel_craft` 的口径一致，但不做严格分类）。"""
    stripped = (line or "").lstrip()
    return stripped.startswith(("「", "『", "“", "『", '"'))


def _bible_blob(project: VnProject) -> str:
    bible = project.bible
    if bible is None:
        return ""
    data = bible.model_dump(mode="json") if hasattr(bible, "model_dump") else dict(bible)
    return "\n".join(
        str(data.get(k) or "") for k in ("world", "background", "outline", "themes", "notes")
    )


def _character_material(project: VnProject, texts: Sequence[str]) -> Dict[str, Any]:
    """出场角色里有几个"可演"（有声线/语料/思维卡）。

    判据只用**有没有素材**，不评素材好坏：改编成 VN 时每个出场角色都要有可演的说话方式，
    否则演出撑不住（『キャラクター小説の作り方』：角色先于情节）。

    **已知局限**：匹配出场只按"≥2 字的显示名/defineName 在正文里出现过"。
    单字名（例如「澪」）太容易在普通用词里撞上，所以不参与匹配——
    这类角色会被漏掉，宁漏不误报（`notes` 里也写了这一条）。
    """
    joined = "\n".join(texts)
    appearing: List[Dict[str, Any]] = []
    for c in project.characters or []:
        names = [str(getattr(c, "displayName", "") or ""), str(getattr(c, "defineName", "") or "")]
        names = [n for n in names if len(n) >= 2]
        if not names or not any(n in joined for n in names):
            continue
        appearing.append(
            {
                "id": str(getattr(c, "id", "") or ""),
                "name": str(getattr(c, "displayName", "") or getattr(c, "defineName", "") or ""),
                "hasVoice": bool(str(getattr(c, "voice", "") or "").strip()),
                "corpusCount": len(list(getattr(c, "voiceCorpus", None) or [])),
                "hasMind": bool(str(getattr(c, "voiceMind", "") or "").strip()),
            }
        )
    thin = [
        row
        for row in appearing
        if not row["hasVoice"] and not row["hasMind"] and row["corpusCount"] == 0
    ]
    return {"appearing": appearing, "thin": thin}


def _flow_reading(project: VnProject) -> Dict[str, Any]:
    """分支与结局的事实读数（不判断该不该有分支）。"""
    try:
        from app.core.branch_analysis import analyze_branches

        data = analyze_branches(project)
        labels = (data.get("coverage") or {}).get("labels") or {}
        endings = data.get("endings") or {}
        return {
            "menus": int(((data.get("coverage") or {}).get("choices") or {}).get("total") or 0),
            "labels": int(labels.get("total") or 0),
            "endingsDeclared": len(list(project.endings or [])),
            "endingsReached": int(endings.get("reached") or 0),
            "computed": True,
        }
    except Exception:  # noqa: BLE001 - 读数算不出来时如实标注，不影响其它项
        return {"menus": 0, "labels": 0, "endingsDeclared": len(list(project.endings or [])),
                "endingsReached": 0, "computed": False}


def build_adaptation_checklist(project: VnProject) -> Dict[str, Any]:
    """跑一遍改编检查表，返回 `items`（每条带 why/action/evidence）与覆盖率说明。

    每条 `item` 的形状与其它建议一致：`code / severity / title / why / action / where / evidence`，
    方便前端与 `branch_recommendations` 用同一套渲染。
    """
    chapters = list(project.chapters or [])
    texts: List[str] = []
    per_chapter: List[Dict[str, Any]] = []
    text_walls: List[Dict[str, Any]] = []
    low_dialogue: List[Dict[str, Any]] = []
    no_scene_marker: List[str] = []
    no_choice: List[str] = []
    scene_blocks_total = 0

    for idx, ch in enumerate(chapters, start=1):
        text = chapter_plain(ch, project.characters)
        texts.append(text)
        paragraphs = _paragraphs(text)
        d_chars = sum(len(p) for p in paragraphs if _is_dialogue_line(p))
        n_chars = sum(len(p) for p in paragraphs if not _is_dialogue_line(p))
        ratio = round(d_chars / (d_chars + n_chars), 3) if (d_chars + n_chars) else None

        blocks = list(getattr(ch, "blocks", None) or [])
        scene_blocks = [b for b in blocks if isinstance(b, dict) and b.get("type") == "scene"]
        menus = [b for b in blocks if isinstance(b, dict) and b.get("type") == "menu"]
        scene_blocks_total += len(scene_blocks)
        if not scene_blocks:
            no_scene_marker.append(str(getattr(ch, "title", "") or getattr(ch, "id", "")))
        if not menus:
            no_choice.append(str(getattr(ch, "title", "") or getattr(ch, "id", "")))

        for p_idx, para in enumerate(paragraphs, start=1):
            if len(para) >= TEXT_WALL_CHARS and not _is_dialogue_line(para):
                if len(text_walls) < MAX_SAMPLES:
                    text_walls.append(
                        {
                            "chapterId": str(getattr(ch, "id", "") or ""),
                            "chapterTitle": str(getattr(ch, "title", "") or ""),
                            "chapterOrdinal": idx,
                            "paragraph": p_idx,
                            "chars": len(para),
                            "preview": para[:40],
                        }
                    )
        if ratio is not None and ratio < LOW_DIALOGUE_RATIO and (d_chars + n_chars) >= 200:
            low_dialogue.append(
                {
                    "chapterId": str(getattr(ch, "id", "") or ""),
                    "chapterTitle": str(getattr(ch, "title", "") or ""),
                    "chapterOrdinal": idx,
                    "dialogueRatio": ratio,
                }
            )
        per_chapter.append(
            {
                "chapterId": str(getattr(ch, "id", "") or ""),
                "chapterTitle": str(getattr(ch, "title", "") or ""),
                "chapterOrdinal": idx,
                "chars": len(text),
                "dialogueRatio": ratio,
                "sceneBlocks": len(scene_blocks),
                "menus": len(menus),
            }
        )

    flow = _flow_reading(project)
    material = _character_material(project, texts)

    items: List[Dict[str, Any]] = []
    if text_walls:
        items.append(
            {
                "code": "text_wall",
                "severity": "warn",
                "title": f"有 {len(text_walls)} 段是「一屏文字」（单段 ≥ {TEXT_WALL_CHARS} 字且没有对白）",
                "why": "VN 的一屏就是一屏：这种段落原样搬进游戏，玩家只能一直点「下一页」。"
                "（《文字冒险游戏设计中的沉浸式体验研究与实践》：沉浸感来自「操作故事 + 对白与演出推进」）",
                "action": "改编时把这段拆开：能变成对白的改成对白、能交给场景与演出的写成分场，"
                "剩下的内心独白再单独标成独白段。",
                "where": f"{text_walls[0]['chapterTitle']} 第 {text_walls[0]['paragraph']} 段",
                "evidence": {"count": len(text_walls), "samples": text_walls},
            }
        )
    if low_dialogue:
        items.append(
            {
                "code": "low_dialogue_chapter",
                "severity": "info",
                "title": f"有 {len(low_dialogue)} 章的对白占比低于 {round(LOW_DIALOGUE_RATIO * 100)}%",
                "why": "VN 主要靠对白与演出推进；对白稀薄的章节改编后容易「读起来像小说、玩起来没事干」。",
                "action": "改编时先给这些章找「谁在说话」：把关键信息改由角色说出来，"
                "或者用分场 + 演出（立绘、场景切换、内心独白）承担。",
                "where": low_dialogue[0]["chapterTitle"],
                "evidence": {"chapters": low_dialogue},
            }
        )
    if no_scene_marker:
        items.append(
            {
                "code": "no_scene_markers",
                "severity": "info",
                "title": f"有 {len(no_scene_marker)} 章没有分场标记（全书分场块 {scene_blocks_total} 个）",
                "why": "VN 是「一场一场」演下去的：一屏一屏的边界就是场。"
                "纯正文的章节在改编时要先切场，否则演出没有落点（『ノベルゲームのシナリオ作成技法』的场景切分）。",
                "action": "在「编辑器」里用分场标记把这几章切开（哪里换地点/换时间/换在场的人，就是一场）。",
                "where": no_scene_marker[0],
                "evidence": {"chapters": no_scene_marker[:MAX_SAMPLES], "count": len(no_scene_marker)},
            }
        )
    # 选项：**不把"没有选项"当问题**（kinetic 是合法形态），只在有分支时提示分布
    if flow["menus"] > 0:
        items.append(
            {
                "code": "branch_distribution",
                "severity": "info",
                "title": f"全书 {flow['menus']} 个选项菜单、{flow['labels']} 个 label、"
                f"{flow['endingsDeclared']} 个登记的结局（可达 {flow['endingsReached']}）",
                "why": "改编成 VN 时，「玩家能插手的地方」就是这些菜单与结局落点——"
                "它们决定了游戏化的手感，而不只是文本长度。",
                "action": "确认每个菜单都在剧情转折点上（而不是「问一句就回到原处」），"
                "并确认每个登记的结局都能真的走到（「结构分析」里有「声明 vs 可达」的对账）。",
                "where": "",
                "evidence": dict(flow),
            }
        )
    elif chapters:
        items.append(
            {
                "code": "kinetic_book",
                "severity": "info",
                "title": "这本书目前没有任何选项（kinetic 形态）",
                "why": "**这不是问题**：视觉小说的谱系里，无选项的 kinetic 作品是合法形态"
                "（《视觉小说叙事逻辑的根源与变迁》）。这里只如实说明改编后的形态是「一路读到底」。",
                "action": "如果本来就想做 kinetic，可以直接导出 .rpy 做演出；"
                "若想要分支，挑一个转折点加菜单即可（「分析 → 分支建议」会给位置）。",
                "where": "",
                "evidence": dict(flow),
            }
        )
    if material["thin"]:
        names = "、".join(row["name"] for row in material["thin"][:MAX_SAMPLES])
        items.append(
            {
                "code": "character_material_thin",
                "severity": "info",
                "title": f"出场角色里有 {len(material['thin'])} 个没有任何声线素材（{names}）",
                "why": "改编成 VN 时每个出场角色都要「演得出来」：没有声线/语料/思维卡，"
                "演出只能靠通用腔调（『キャラクター小説の作り方』：角色先于情节）。",
                "action": "给这几个角色补一句声线描述或几段例句（「角色工坊」里可以采样），"
                "Agent 与声线核对都会用上。",
                "where": material["thin"][0]["name"],
                "evidence": {"characters": material["thin"], "appearing": len(material["appearing"])},
            }
        )

    counts: Dict[str, int] = {"warn": 0, "info": 0}
    for item in items:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1

    return {
        "items": items,
        "counts": {**counts, "total": len(items)},
        "perChapter": per_chapter,
        "characters": material,
        "flow": flow,
        "coverage": {
            "chaptersTotal": len(chapters),
            "chaptersWithText": sum(1 for row in per_chapter if row["chars"] > 0),
            "sceneBlocks": scene_blocks_total,
            "note": "只统计有正文的章节；脚本块工程按块里的文字算（与写作统计同一口径）。",
        },
        "notes": [
            "这是一张**改编检查表**：只报结构上可核对的事实（段落长度、对白占比、分场、"
            "选项与结局、角色素材），不评「写得好不好」，也不预测「好不好玩」。",
            "**没有选项不是缺陷**：kinetic（无选项的视觉小说）是合法形态，这一项只说明形态。",
            "角色素材那一项只匹配「≥2 字的显示名/defineName 在正文里出现过」的角色："
            "单字名容易在普通用词里误撞，宁漏不误报（这类角色会被漏掉）。",
            "依据：《文字冒险游戏设计中的沉浸式体验研究与实践》《剧情交互式游戏的叙事研究》"
            "《视觉小说叙事逻辑的根源与变迁》、『ノベルゲームのシナリオ作成技法』、"
            "『キャラクター小説の作り方』——见 docs/references.md。",
        ],
    }


def checklist_action_items(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """只取"要动手"的项（warn），给"下一步做什么"这类界面用。"""
    return [i for i in (result.get("items") or []) if i.get("severity") == "warn"]


def dominant_issue(result: Optional[Dict[str, Any]]) -> Optional[str]:
    """一句话概括：有 warn 就报第一条 warn 的标题，否则 None。"""
    if not result:
        return None
    items = checklist_action_items(result)
    return str(items[0]["title"]) if items else None
