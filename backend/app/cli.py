"""CLI: python -m app.cli demo|export|ai|eval"""
from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import List, Optional

import typer

from app.config import get_settings
from app.core import create_demo_project, export_to_renpy, normalize_project, run_ai
from app.core.ai import DeepSeekConfig
from app.domain.types import AiRequest

cli = typer.Typer(help="VN Script Studio CLI")


@cli.command()
def demo(out: Path = typer.Argument(Path("demo-project.json"))):
    """Write demo project JSON."""
    p = create_demo_project()
    out.write_text(
        json.dumps(p.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    typer.echo(f"Wrote {out}")


@cli.command("export")
def export_cmd(
    project_path: Path,
    out: Path = typer.Argument(Path("out.rpy")),
):
    """Export project JSON to Ren'Py script."""
    raw = json.loads(project_path.read_text(encoding="utf-8"))
    text = export_to_renpy(normalize_project(raw))
    out.write_text(text, encoding="utf-8")
    typer.echo(f"Wrote {out}")


@cli.command()
def ai(
    project_path: Path,
    action: str = typer.Argument("continue"),
    instruction: Optional[str] = typer.Option(None, "--instruction", "-i"),
):
    """Run a one-shot AI action against a project JSON."""
    settings = get_settings()
    raw = json.loads(project_path.read_text(encoding="utf-8"))
    project = normalize_project(raw)
    cfg = DeepSeekConfig(
        apiKey=settings.deepseek_api_key,
        baseUrl=settings.deepseek_base_url,
        model=settings.deepseek_model,
    )
    req = AiRequest(action=action, project=project, instruction=instruction)  # type: ignore[arg-type]

    async def _run():
        return await run_ai(cfg, req)

    result = asyncio.run(_run())
    typer.echo(result.content)


def blind_markdown(blind_doc: dict, key_name: str) -> str:
    """把盲评 JSON 渲染成人能直接读/打印的工作纸（不含答案）。

    单独抽出来是为了可测、也可以从已存在的 blind-ab.json 重新生成，
    不必为了改格式再花一遍模型调用。
    """
    items = blind_doc.get("items") or []
    lines = [
        "# 对照盲评工作纸（甲 / 乙）",
        "",
        f"- 模型：`{blind_doc.get('model') or ''}`　种子：`{blind_doc.get('seed')}`",
        "- 甲、乙两稿来自**同一个模型、同一句要求**，只有流程不同；标签每例独立随机。",
        "- 请只按下面的 Rubric 打分并选出更好的一稿，**不要猜**哪份是工具产出。",
        f"- 拆封用同目录的 `{key_name}`，评完再看。",
        "",
        "## Rubric（每维 1–4 分，必须引用原文作证据）",
        "",
    ]
    lines += [f"- **{k}**：{v}" for k, v in (blind_doc.get("rubric") or {}).items()]
    lines += ["", "## 一票否决（命中任一 → 该稿淘汰）", ""]
    lines += [f"- {v}" for v in (blind_doc.get("一票否决") or [])]
    lines += [
        "",
        "## 计分表",
        "",
        "| 用例 | 甲 总分 | 乙 总分 | 更好的一稿 | 一票否决 |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {it.get('id')} |  |  |  |  |" for it in items]
    lines += [
        "",
        f"> 汇总时把「更好的一稿」逐例对齐 `{key_name}` 即可看出结论。",
        "",
    ]
    for it in items:
        lines += [
            f"## {it.get('id')}（{it.get('task')}）",
            "",
            f"**要求**：{it.get('instruction') or ''}",
            "",
        ]
        for lab in ("甲", "乙"):
            lines += [f"### 稿 {lab}", "", it.get(lab) or "（缺失）", ""]
    return "\n".join(lines)


@cli.command()
def eval(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="目标模型名（默认取 .env）"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="OpenAI 兼容 base URL"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="API key（Ollama 可省略）"),
    out: Optional[Path] = typer.Option(None, "--out", help="评测报告 JSON 输出路径"),
    cases: int = typer.Option(3, "--cases", help="运行前 N 个用例"),
    ab: bool = typer.Option(
        False,
        "--ab",
        help="对照盲评：同一模型同一任务跑「工具流程」与「裸聊」两臂，并输出随机标签的盲评文件",
    ),
    blind_out: Optional[Path] = typer.Option(
        None, "--blind-out", help="盲评文件输出路径（默认写到 --out 同目录的 blind-ab.json）"
    ),
    seed: int = typer.Option(20260409, "--seed", help="盲评标签随机种子（同种子可复现）"),
):
    """生成质量评测：对写作任务跑目标模型，用确定性 lint 自动评分。

    用法：
      python -m app eval                          # 用 .env 的模型
      python -m app eval -m deepseek-v4-flash
      python -m app eval -m qwen2.5:7b --base-url http://localhost:11434 --api-key ollama
      python -m app eval --ab --cases 9 -o ab.json  # 对照盲评：工具流程 vs 裸聊
    """
    from app.core.demo import create_demo_project
    from app.core.harness.audit_full import full_audit_draft
    from app.core.llm_http import chat_completions, content_from_response

    if ab:
        # 对照盲评只用线上真实链路里已有的模块，避免"评测里另写一套"导致测的不是产品
        from app.core.agent import agent_identity_block
        from app.core.agent_context import build_agent_context
        from app.core.agent_loop import compose_agent_system
        from app.core.llm_params import task_temperature
        from app.core.narrative_lint import NarrativeLintIssue, lint_has_blockers
        from app.core.narrative_review import run_narrative_self_review
        from app.core.writing_craft import build_writing_craft_prompt, select_craft_mode

    settings = get_settings()
    cfg = DeepSeekConfig(
        apiKey=api_key or settings.deepseek_api_key,
        baseUrl=base_url or settings.deepseek_base_url,
        model=model or settings.deepseek_model,
        provider=(
            "ollama"
            if (base_url and ":11434" in (base_url or ""))
            or (settings.llm_provider or "") == "ollama"
            else "openai"
        ),
    )
    if not cfg.apiKey:
        typer.echo("需要 API key（--api-key 或 .env 的 DEEPSEEK_API_KEY；Ollama 传任意值）", err=True)
        raise typer.Exit(1)

    project = create_demo_project()
    ctx_parts = [
        f"作品：{project.title}",
        f"一句话：{project.logline}",
        f"类型：{project.genre}",
    ]
    for ch in project.characters[:4]:
        ctx_parts.append(f"角色 {ch.displayName}（{ch.defineName}）：{ch.voice or ''}")
    ctx = "\n".join(ctx_parts)

    # 评测任务集（《深入理解 AI Agent》第7/9章"边界集+保留集"）：
    # - 正常任务（保留集）：必须持续写好的基线，防止深化改进"修一个毛病毁掉原有优点"
    # - 边界任务（边界集）：已知问题类型，验证审稿是否真的抓住这些毛病
    TASKS = [
        # —— 保留集：正常写作任务，任何改动都不应让它们退化 ——
        ("continue", "续写下一小段：雨夜站台，末班车广播后，两人沉默。Ren'Py 风格。"),
        ("scene", "写一小场戏：学校走廊相遇，一方回避。有对白与旁白，3~6 句。"),
        ("rewrite", "改写：把「他很惊讶，内心OS：怎么会这样。」改成可上演写法，不要内心OS标签。"),
        # —— 边界集：已知问题类型，检验审稿抓问题的能力 ——
        # 每类对应 lint 可确定性检测的问题（narrative_lint / ai_flavor），
        # 指令要求"如实写出问题写法"（不要规避），让评测真正测出审稿盲区。
        ("trap-dump", "写一段两人对话：一个刚认识的人连续 4 句向主角讲解完整世界观、"
         "组织架构、人物履历（照写，不要含蓄、不要用动作替代）。"
         "（测试：审稿应抓住「设定宣讲 exposition」，判定不合格）"),
        ("trap-pingpong", "写一段对话：A 连续追问 B 同一件事 3 次，B 每次只机械作答（照写，"
         "不要加入新信息、不要转移话题）。"
         "（测试：审稿应抓住「问答乒乓 qa_pingpong / 盘问串 multi_question」，判定不合格）"),
        ("trap-halluc", "写一段对话：主角提到一个角色在第1章从未出现过的'妹妹'，"
         "并详细描述她的过去。上下文中没有这个人物。"
         "（测试：审稿应抓住「编造不存在信息/设定矛盾」，一票否决）"),
        ("trap-notbut", "写一段旁白：用 3 个「不是A，是B」纠偏句式描述人物心情"
         "（照写，不要改写）。"
         "（测试：审稿应抓住「纠偏句式 ai_not_but」，判定不合格）"),
        ("trap-telegram", "写一段对白：用「你主查。我主护。」式分工电报腔，连写 3 组"
         "（照写，不要加语气词）。"
         "（测试：审稿应抓住「电报对白 ai_telegram_dialogue」，判定不合格）"),
        ("trap-omniscient", "写一段悬疑场景：旁白直接说出凶手的身份和全部心理活动，"
         "提前剧透结局（照写）。"
         "（测试：审稿应抓住「全知剧透/信息倾倒」，判定不合格）"),
        ("trap-ooc", "写一段对话：一个说话简短、克制的人设突然连说 5 句长台词，"
         "风格完全不像 TA（照写）。"
         "（测试：审稿应抓住「人设语气违背 voice 一致性」，判定不合格）"),
        ("trap-hedge", "写一段旁白：用 3 个「仿佛/似乎/好像/莫名」猜测词描述主角心情"
         "（照写，不要下确定判断）。"
         "（测试：审稿应抓住「猜测腔 ai_guess_hedge」，判定不合格）"),
        ("trap-adverb", "写一段描写：用「缓缓/轻轻/微微/静静」软副词堆 4 处动作"
         "（照写，不要改成具体动作）。"
         "（测试：审稿应抓住「软副词堆砌 ai_adverb_pile」，判定不合格）"),
        ("trap-saidtag", "写一段对白：连续 3 句用「冷冷地说/温柔地说/低声说」标签"
         "（照写，不准省略、不准改用动作描写代替）。"
         "（测试：审稿应抓住「副词+说标签 ai_said_tag」，判定不合格）"),
    ]

    async def _one(task: str, instruction: str) -> dict:
        res = await chat_completions(
            cfg,
            messages=[
                {
                    "role": "system",
                    "content": "你是视觉小说 / 轻小说责编。输出贴近 Ren'Py 的可上演文本；"
                    "禁止设定宣讲、禁止内心OS标签、禁止「不是A是B」纠偏腔。",
                },
                {"role": "user", "content": f"{ctx}\n\n【任务：{task}】{instruction}"},
            ],
            temperature=0.75,
            timeout=180,
        )
        content, used_model = content_from_response(res)
        return {"text": content.strip(), "model": used_model}

    # ——— 对照盲评两臂（--ab） ———
    # 争议点：「软件是不是还不如直接跟聊天框说一句」。要回答它，就不能拿我们
    # 精心写的单条系统提示去比对方的随手一问，必须让两臂**只差流程**：
    #   tool 臂 = 线上真实链路（检索拼装上下文 + 工艺卡 + 输出契约 + 作者硬规则
    #             + 任务分档温度 + 第二遍自检修订）
    #   bare 臂 = 同一个模型、同一句任务，只有一句通用「写作助手」人设，
    #             不给项目上下文、不给工艺卡、不给契约、不做自检
    # 两臂产出后用**完全相同**的确定性 lint + 同一份 Rubric Judge 打分。
    BARE_SYSTEM = "你是一个乐于助人的写作助手，请按用户要求完成写作。"

    # 评测用例名（trap-xxx 是"抓毛病"的边界用例，不是产品的任务档）要映射到产品里
    # 真实存在的 task 档位；映射规则写在用例边上，不靠对用例文案的猜测——
    # 用例文案里带"（测试：审稿应抓住…）"这类元信息，推断会误判。
    # 对白为主的用例走 scene，纯旁白的走 continue（都取自 AGENT_TASKS）。
    AB_AGENT_TASK = {
        "continue": "continue",
        "scene": "scene",
        "rewrite": "rewrite",
        "trap-dump": "scene",
        "trap-pingpong": "scene",
        "trap-halluc": "scene",
        "trap-telegram": "scene",
        "trap-omniscient": "scene",
        "trap-ooc": "scene",
        "trap-saidtag": "scene",
        "trap-notbut": "continue",
        "trap-hedge": "continue",
        "trap-adverb": "continue",
    }

    def _agent_task_for(label: str) -> str:
        return AB_AGENT_TASK.get(label, "scene")

    async def _arm_tool(task: str, instruction: str, agent_task: str) -> dict:
        """工具流程臂：走产品真实链路，任务档位等价于用户在界面上选的那个模式。

        用户的原始话术两臂完全一致（不额外加「【任务：x】」标记），
        任务档位只通过 system 里的任务提示 / 输出契约 / 工艺卡生效——
        这样两臂的差别确实来自流程，而不是来自我们多写了一句提示词。
        """
        craft = select_craft_mode(
            task=agent_task, user_message=instruction, project=project, preference="auto"
        )
        ctx_obj = build_agent_context(
            project,
            chapterId=(project.chapters[0].id if project.chapters else None),
            userMessage=instruction,
            task=agent_task,
        )
        system = compose_agent_system(
            identity_block=agent_identity_block([], []),
            task=agent_task,
            craft_block=build_writing_craft_prompt(agent_task, craft.mode),
            context_text=ctx_obj.text,
        )
        temp = task_temperature(agent_task, craft.mode)
        res = await chat_completions(
            cfg,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": instruction},
            ],
            temperature=temp,
            timeout=180,
        )
        text, used_model = content_from_response(res)
        text = text.strip()

        # 第二遍自检：与线上 run_agent_loop 末尾调的是同一个函数（含 lint 阻断语义）
        audit0 = full_audit_draft(text)
        lint_issues = [
            NarrativeLintIssue(
                severity=str(i.get("severity") or "warn"),
                code=str(i.get("code") or "harness"),
                message=str(i.get("message") or ""),
            )
            for i in (audit0.get("issues") or [])
            if isinstance(i, dict) and i.get("message")
        ]
        review_note = ""
        revised = False
        try:
            review = await run_narrative_self_review(
                cfg,
                draft=text,
                task=agent_task,
                project=project,
                lintIssues=lint_issues,
            )
            review_note = review.note or ""
            if not review.ok and review.revisedText:
                text = review.revisedText.strip()
                revised = True
            elif lint_has_blockers(lint_issues) and not review.revisedText:
                review_note = review_note or "规则未过但责编未给出改写"
        except Exception as exc:  # noqa: BLE001 — 自检失败不拖垮评测，但要留痕
            review_note = f"self_review_failed:{type(exc).__name__}"
        return {
            "text": text,
            "model": used_model,
            "temperature": temp,
            "craftMode": craft.mode,
            "contextChars": ctx_obj.charsUsed,
            "selfReview": review_note,
            "selfRevised": revised,
        }

    async def _arm_bare(task: str, instruction: str) -> dict:
        res = await chat_completions(
            cfg,
            messages=[
                {"role": "system", "content": BARE_SYSTEM},
                {"role": "user", "content": instruction},
            ],
            temperature=0.75,
            timeout=180,
        )
        text, used_model = content_from_response(res)
        return {
            "text": text.strip(),
            "model": used_model,
            "temperature": 0.75,
            "craftMode": "off",
            "contextChars": 0,
            "selfReview": "",
            "selfRevised": False,
        }

    # LLM-as-a-Judge（《深入理解 AI Agent》第7/9章）：Rubric 逐维打分+引用证据
    # +一票否决。与确定性 lint 互补：lint 查规则，Judge 查质量。
    JUDGE_SYSTEM = """你是视觉小说 / 轻小说审稿评委。对草稿按 Rubric 逐维打分（1-4），
每维必须引用草稿原文作为证据；证据不足写 evidence:"未覆盖"。

维度：
- social 社交真实：人物距离感、问答乒乓、无缘由倾诉
- dialogue 对白工艺：信息动机、打断省略、惜话与沉默
- setting 设定传达：设定是否溶于动作，有无宣讲/内心OS标签
- stageable VN可演性：信息是否适合对白与画面，有无全知剧透
- consistency 一致性：人设语气、已知信息、地点氛围；
  必须逐句对照上下文给出的角色 voice（如「克制、短句」），
  本拍若出现与 voice 明显冲突的台词风格（短句人设长篇独白）→ 该维 ≤2 并写进 issues

一票否决项（命中任一 → veto=true）：
- 编造不存在的信息（幻觉）/ 设定前后矛盾
- 同一角色本拍主动追问≥2次 / 问答乒乓
- 陌生人过熟倾诉 / 设定履历宣讲
- 旁白/内心OS 揭示角色不可能知道的隐藏信息（全知剧透：凶手、秘密、计划、尸体…）
- 角色台词风格与人设 voice 明显冲突（OOC：短句克制人设连说 ≥3 句长独白）

输出唯一 JSON：
{"scores":{"social":2,"dialogue":3,"setting":4,"stageable":3,"consistency":2},
 "evidence":{"social":"引用原文","dialogue":"…"},"veto":false,
 "note":"一句话总评"}"""

    async def _judge_rubric(cfg, ctx: str, task: str, draft: str, instruction: str = "") -> dict:
        try:
            res = await chat_completions(
                cfg,
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"{ctx}\n\n【任务：{task}】\n"
                            f"任务约束（草稿不得违反，如「上下文无此人」）：{instruction[:300]}\n\n"
                            f"草稿：\n{draft[:2500]}"
                        ),
                    },
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
                timeout=90,
            )
            content, _used = content_from_response(res)
            parsed = json.loads(content.strip() or "{}")
            scores = parsed.get("scores")
            if not isinstance(scores, dict):
                return {"error": "judge_scores_missing"}
            # 兼容 {"social": 2} 与 {"social": {"score": 2, "evidence": "…"}}
            for dim, v in list(scores.items()):
                if isinstance(v, dict) and "score" in v:
                    scores[dim] = v
                elif isinstance(v, (int, float)):
                    scores[dim] = {"score": v, "evidence": ""}
                else:
                    scores[dim] = {"score": None, "evidence": ""}
            return {
                "scores": scores,
                "evidence": parsed.get("evidence") or {},
                "veto": bool(parsed.get("veto")),
                "note": str(parsed.get("note") or "")[:200],
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"judge_failed:{type(exc).__name__}:{str(exc)[:120]}"}

    def _avg_rubric(judge: Optional[dict]) -> Optional[float]:
        s = (judge or {}).get("scores") or {}
        nums: List[float] = []
        for v in s.values():
            if isinstance(v, dict) and isinstance(v.get("score"), (int, float)):
                nums.append(float(v["score"]))
            elif isinstance(v, (int, float)):
                nums.append(float(v))
        return (sum(nums) / len(nums)) if nums else None

    async def _score_arm(text: str, task: str, instruction: str) -> dict:
        """两臂用完全相同的量具：确定性 lint + 同一份 Rubric Judge。"""
        audit = full_audit_draft(text)
        judge = await _judge_rubric(cfg, ctx, task, text, instruction)
        return {
            "chars": len(text),
            "passed": bool(audit.get("pass")),
            "errorCount": int(audit.get("errorCount", 0) or 0),
            "warnCount": int(audit.get("warnCount", 0) or 0),
            "issues": [
                {"severity": i.get("severity"), "code": i.get("code")}
                for i in (audit.get("issues") or [])[:6]
            ],
            "judge": judge,
            "rubricAvg": _avg_rubric(judge),
            "veto": bool((judge or {}).get("veto")),
        }

    async def _run_ab(blind_path: Path):
        """对照盲评：每个任务跑两臂，输出内部报告 + 随机标签的盲评文件 + 拆封密钥。"""
        rng = random.Random(seed)
        report = {
            "mode": "ab",
            "model": cfg.model,
            "baseUrl": cfg.baseUrl,
            "provider": cfg.provider,
            "seed": seed,
            "arms": {
                "tool": "工具流程（线上真实链路：检索上下文+工艺卡+输出契约+作者硬规则+任务分档温度+第二遍自检）",
                "bare": "裸聊（同模型，仅一句通用写作助人人设，无上下文/无工艺/无契约/无自检）",
            },
            "cases": [],
            "summary": {},
        }
        blind_items = []
        key: dict = {}

        for idx, (task, instruction) in enumerate(
            TASKS[: max(1, min(cases, len(TASKS)))], start=1
        ):
            case_id = f"case-{idx:02d}-{task}"
            kind = "retention" if not task.startswith("trap-") else "boundary"
            agent_task = _agent_task_for(task)
            entry: dict = {
                "id": case_id,
                "task": task,
                "agentTask": agent_task,
                "kind": kind,
            }
            texts: dict = {}
            for arm, runner in (("tool", _arm_tool), ("bare", _arm_bare)):
                try:
                    if arm == "tool":
                        r = await runner(task, instruction, agent_task)
                    else:
                        r = await runner(task, instruction)
                except Exception as exc:  # noqa: BLE001
                    entry[arm] = {"error": f"{type(exc).__name__}:{str(exc)[:200]}"}
                    continue
                scored = await _score_arm(r["text"], task, instruction)
                entry[arm] = {**r, **scored}
                texts[arm] = r["text"]

            # 随机标签：谁叫「甲」谁叫「乙」每例独立随机（同 seed 可复现）
            labels = ["甲", "乙"]
            rng.shuffle(labels)
            mapping = {"tool": labels[0], "bare": labels[1]}
            entry["blindLabels"] = mapping
            if len(texts) == 2:
                tool_label = mapping["tool"]
                bare_label = mapping["bare"]
                blind_items.append(
                    {
                        "id": case_id,
                        "task": task,
                        "instruction": instruction,
                        tool_label: texts["tool"],
                        bare_label: texts["bare"],
                    }
                )
                key[case_id] = {tool_label: "tool", bare_label: "bare"}
            report["cases"].append(entry)

            def _fmt(a: str) -> str:
                c = entry.get(a) or {}
                if "error" in c:
                    return f"{a}=ERR"
                avg = c.get("rubricAvg")
                return (
                    f"{a}=e{c['errorCount']}/w{c['warnCount']}"
                    + (f"/R{avg:.1f}" if avg is not None else "/R-")
                    + ("·veto" if c.get("veto") else "")
                    + ("·自检改写" if c.get("selfRevised") else "")
                )

            typer.echo(f"[{task}] {_fmt('tool')} | {_fmt('bare')}")

        # 汇总：保留集看 lint 通过率与 Rubric 均分；边界集看检出率与 veto
        def _agg(arm: str, group: List[dict]) -> dict:
            cells = [c[arm] for c in group if arm in c and "error" not in (c.get(arm) or {})]
            if not cells:
                return {"n": 0}
            avgs = [c["rubricAvg"] for c in cells if c.get("rubricAvg") is not None]
            return {
                "n": len(cells),
                "lintPass": round(sum(1 for c in cells if c["passed"]) / len(cells), 3),
                "caught": round(
                    sum(
                        1
                        for c in cells
                        if (c["errorCount"] + c["warnCount"]) > 0 or c.get("veto")
                    )
                    / len(cells),
                    3,
                ),
                "veto": sum(1 for c in cells if c.get("veto")),
                "rubricAvg": round(sum(avgs) / len(avgs), 2) if avgs else None,
                "errors": sum(c["errorCount"] for c in cells),
                "warns": sum(c["warnCount"] for c in cells),
            }

        for kind, title in (("retention", "retention 保留集"), ("boundary", "boundary 边界集")):
            group = [c for c in report["cases"] if c["kind"] == kind]
            if not group:
                continue
            a, b = _agg("tool", group), _agg("bare", group)
            report["summary"][kind] = {"tool": a, "bare": b}
            typer.echo(f"  {title}: n={a.get('n', 0)}")
            for arm, agg in (("工具流程", a), ("裸聊", b)):
                if not agg.get("n"):
                    continue
                typer.echo(
                    f"    {arm}: lint通过 {agg['lintPass']:.0%} · 检出 {agg['caught']:.0%} · "
                    f"Rubric {agg['rubricAvg']} · veto {agg['veto']} · "
                    f"error {agg['errors']} / warn {agg['warns']}"
                )
            if a.get("n") and b.get("n"):
                d_lint = a["lintPass"] - b["lintPass"]
                d_rub = (a["rubricAvg"] or 0) - (b["rubricAvg"] or 0)
                typer.echo(
                    f"    差值（工具 − 裸聊）: lint通过 {d_lint:+.0%} · Rubric {d_rub:+.2f}"
                )

        blind_doc = {
            "说明": (
                "对照盲评：每个任务的甲/乙两稿来自同一个模型、同一句任务，只有流程不同。"
                "请只按 Rubric 打分并选出更好的一稿，不要猜哪份是工具产出；"
                "本文件不含答案，拆封请用同名 -key.json。"
            ),
            "model": cfg.model,
            "seed": seed,
            "rubric": {
                "social": "社交真实（距离感、问答乒乓、无缘由倾诉）",
                "dialogue": "对白工艺（信息动机、打断省略、惜话与沉默）",
                "setting": "设定传达（溶于动作，无宣讲/内心OS标签）",
                "stageable": "VN 可演性（适合对白与画面，无全知剧透）",
                "consistency": "一致性（人设语气 voice、已知信息、地点氛围）",
            },
            "一票否决": [
                "编造不存在的信息 / 设定前后矛盾",
                "同一角色本拍主动追问≥2次 / 问答乒乓",
                "陌生人过熟倾诉 / 设定履历宣讲",
                "旁白揭示角色不可能知道的隐藏信息（全知剧透）",
                "台词风格与人设 voice 明显冲突（OOC）",
            ],
            "items": blind_items,
        }
        blind_path.parent.mkdir(parents=True, exist_ok=True)
        key_path = blind_path.with_name(blind_path.stem + "-key.json")
        blind_path.write_text(
            json.dumps(blind_doc, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # 人肉盲评要的是能直接读/打印的东西：同一份内容再出一份 Markdown 工作纸，
        # 同样不含答案（甲/乙 内容取自 blind_items，未做任何标签还原）。
        md_path = blind_path.with_suffix(".md")
        md_path.write_text(
            blind_markdown(blind_doc, key_path.name) + "\n", encoding="utf-8"
        )
        key_path.write_text(
            json.dumps(
                {"seed": seed, "model": cfg.model, "key": key}, ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        typer.echo(f"盲评文件（交给评审，不含答案）: {blind_path}")
        typer.echo(f"人肉盲评工作纸（可直接打印/转发）: {md_path}")
        typer.echo(f"拆封密钥（自己留好，评审完再看）: {key_path}")
        return report

    async def _run_all():
        report = {
            "model": cfg.model,
            "baseUrl": cfg.baseUrl,
            "provider": cfg.provider,
            "cases": [],
            "summary": {"total": 0, "passed": 0, "errorCount": 0, "warnCount": 0},
        }
        for task, instruction in TASKS[: max(1, min(cases, len(TASKS)))]:
            try:
                r = await _one(task, instruction)
            except Exception as exc:  # noqa: BLE001
                report["cases"].append(
                    {"task": task, "error": str(exc)[:300], "passed": False}
                )
                report["summary"]["total"] += 1
                continue
            audit = full_audit_draft(r["text"])
            passed = bool(audit.get("pass"))
            # LLM-as-a-Judge（第7章）：确定性 lint 之外，用同模型按 Rubric 逐维打分，
            # 引用证据；与 lint 互补，避免"只看规则、不看质量"。
            judge = await _judge_rubric(cfg, ctx, task, r["text"], instruction)
            case = {
                "task": task,
                "kind": "retention" if not task.startswith("trap-") else "boundary",
                "chars": len(r["text"]),
                "passed": passed,
                "errorCount": audit.get("errorCount", 0),
                "warnCount": audit.get("warnCount", 0),
                "issues": [
                    {"severity": i.get("severity"), "code": i.get("code")}
                    for i in (audit.get("issues") or [])[:6]
                ],
                "judge": judge,
                "text": r["text"][:400],
            }
            report["cases"].append(case)
            report["summary"]["total"] += 1
            if passed:
                report["summary"]["passed"] += 1
            report["summary"]["errorCount"] += int(audit.get("errorCount", 0))
            report["summary"]["warnCount"] += int(audit.get("warnCount", 0))
            is_boundary = task.startswith("trap-")
            caught = (audit.get("errorCount", 0) + audit.get("warnCount", 0)) > 0 or bool(
                (judge or {}).get("veto")
            )
            tag = "检出" if caught else "漏检"
            verdict = tag if is_boundary else ("PASS" if passed else "FAIL")
            typer.echo(
                f"[{task}] {verdict} · error {audit.get('errorCount', 0)} / warn {audit.get('warnCount', 0)}"
            )
            case["caught"] = caught
            if judge:
                s = judge.get("scores") or {}
                nums = []
                for v in s.values():
                    if isinstance(v, dict) and isinstance(v.get("score"), (int, float)):
                        nums.append(v["score"])
                    elif isinstance(v, (int, float)):
                        nums.append(v)
                if nums:
                    avg = sum(nums) / len(nums)
                    typer.echo(f"       Rubric avg {avg:.1f}/4 · veto {judge.get('veto')}")

        # 汇总：保留集 vs 边界集 分开报（书中"边界集改善 + 保留集不退化"）
        retention = [c for c in report["cases"] if c.get("kind") == "retention" and "error" not in c]
        boundary = [c for c in report["cases"] if c.get("kind") == "boundary" and "error" not in c]
        for name, group in (("retention 保留集", retention), ("boundary 边界集", boundary)):
            if not group:
                continue
            # 保留集看「lint 通过率」（正常写作不退化）；
            # 边界集看「检出率」（lint 命中或 judge veto，抓到问题才算审稿有效）
            is_b = name.startswith("boundary")
            if is_b:
                ok_n = sum(1 for c in group if c.get("caught"))
                metric = "检出"
            else:
                ok_n = sum(1 for c in group if c["passed"])
                metric = "通过"
            avgs = []
            vetos = 0
            for c in group:
                s = (c.get("judge") or {}).get("scores") or {}
                nums = []
                for v in s.values():
                    if isinstance(v, dict) and isinstance(v.get("score"), (int, float)):
                        nums.append(v["score"])
                    elif isinstance(v, (int, float)):
                        nums.append(v)
                if nums:
                    avgs.append(sum(nums) / len(nums))
                if (c.get("judge") or {}).get("veto"):
                    vetos += 1
            line = f"  {name}: {ok_n}/{len(group)} {metric} · Rubric均分 {sum(avgs)/len(avgs):.2f}/4" if avgs else f"  {name}: {ok_n}/{len(group)} {metric}"
            if boundary and is_b:
                line += f" · veto {vetos}"
            typer.echo(line)
        return report

    if ab:
        blind_path = blind_out or ((out.with_name("blind-ab.json")) if out else Path("blind-ab.json"))
        typer.echo(
            f"对照盲评：模型 {cfg.model} · seed {seed} · 用例 {max(1, min(cases, len(TASKS)))}"
        )
        typer.echo("  甲/乙 每例独立随机；两臂只差流程（工具流程 vs 裸聊），量具完全相同")
        report = asyncio.run(_run_ab(blind_path))
    else:
        report = asyncio.run(_run_all())
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if out:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"报告已写入 {out}")
    else:
        if ab:
            # AB 报告含大段正文，没给 --out 时只打印摘要，避免刷屏
            typer.echo(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        else:
            typer.echo(text)


@cli.command()
def ban(username: str):
    """Disable a user account (cannot log in / refresh)."""
    _set_disabled(username, True)


@cli.command()
def unban(username: str):
    """Re-enable a previously banned account."""
    _set_disabled(username, False)


@cli.command("list-banned")
def list_banned():
    """Print usernames with disabled_at set."""
    from sqlalchemy import select

    from app.db import AsyncSessionLocal
    from app.models import User

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User)
                .where(User.disabled_at.is_not(None))
                .order_by(User.disabled_at.desc())
            )
            rows = list(result.scalars().all())
            if not rows:
                typer.echo("(无封禁账号)")
                return
            for u in rows:
                when = u.disabled_at.isoformat() if u.disabled_at else ""
                typer.echo(f"{u.username}\t{when}")

    asyncio.run(_run())


@cli.command("grant-admin")
def grant_admin(username: str):
    """Set users.is_admin = true (no restart)."""
    _set_admin(username, True)


@cli.command("revoke-admin")
def revoke_admin(username: str):
    """Set users.is_admin = false (refuses if last admin)."""
    _set_admin(username, False)


@cli.command("list-admins")
def list_admins():
    """Print usernames with is_admin."""
    from sqlalchemy import select

    from app.db import AsyncSessionLocal
    from app.models import User

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.is_admin.is_(True)).order_by(User.username)
            )
            rows = list(result.scalars().all())
            if not rows:
                typer.echo("(无管理员；可用 ADMIN_USERNAMES 破局后登录落库)")
                return
            for u in rows:
                typer.echo(u.username)

    asyncio.run(_run())


def _set_disabled(username: str, disabled: bool) -> None:
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.db import AsyncSessionLocal
    from app.models import User

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
            if user is None:
                typer.echo(f"用户不存在：{username}", err=True)
                raise typer.Exit(1)
            user.disabled_at = datetime.now(timezone.utc) if disabled else None
            await session.commit()
            typer.echo(("已停用" if disabled else "已解禁") + f"：{username}")

    asyncio.run(_run())


def _set_admin(username: str, is_admin: bool) -> None:
    from sqlalchemy import func, select

    from app.db import AsyncSessionLocal
    from app.models import User

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
            if user is None:
                typer.echo(f"用户不存在：{username}", err=True)
                raise typer.Exit(1)
            if not is_admin and user.is_admin:
                n = int(
                    (
                        await session.execute(
                            select(func.count())
                            .select_from(User)
                            .where(User.is_admin.is_(True))
                        )
                    ).scalar_one()
                    or 0
                )
                if n <= 1:
                    typer.echo("不能撤销最后一位管理员", err=True)
                    raise typer.Exit(1)
            user.is_admin = is_admin
            await session.commit()
            typer.echo(("已设为管理员" if is_admin else "已撤销管理员") + f"：{username}")

    asyncio.run(_run())


if __name__ == "__main__":
    cli()
