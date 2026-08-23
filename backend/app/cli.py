"""CLI: python -m app.cli demo|export|ai|eval"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

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


@cli.command()
def eval(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="目标模型名（默认取 .env）"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="OpenAI 兼容 base URL"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="API key（Ollama 可省略）"),
    out: Optional[Path] = typer.Option(None, "--out", help="评测报告 JSON 输出路径"),
    cases: int = typer.Option(3, "--cases", help="运行前 N 个用例"),
):
    """生成质量评测：对写作任务跑目标模型，用确定性 lint 自动评分。

    用法：
      python -m app eval                          # 用 .env 的模型
      python -m app eval -m deepseek-v4-flash
      python -m app eval -m qwen2.5:7b --base-url http://localhost:11434 --api-key ollama
    """
    from app.core.demo import create_demo_project
    from app.core.harness.audit_full import full_audit_draft
    from app.core.llm_http import chat_completions, content_from_response

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

    # LLM-as-a-Judge（《深入理解 AI Agent》第7/9章）：Rubric 逐维打分+引用证据
    # +一票否决。与确定性 lint 互补：lint 查规则，Judge 查质量。
    JUDGE_SYSTEM = """你是视觉小说 / 轻小说审稿评委。对草稿按 Rubric 逐维打分（1-4），
每维必须引用草稿原文作为证据；证据不足写 evidence:"未覆盖"。

维度：
- social 社交真实：人物距离感、问答乒乓、无缘由倾诉
- dialogue 对白工艺：信息动机、打断省略、惜话与沉默
- setting 设定传达：设定是否溶于动作，有无宣讲/内心OS标签
- stageable VN可演性：信息是否适合对白与画面，有无全知剧透
- consistency 一致性：人设语气、已知信息、地点氛围

一票否决项（命中任一 → veto=true）：
- 编造不存在的信息（幻觉）/ 设定前后矛盾
- 同一角色本拍主动追问≥2次 / 问答乒乓
- 陌生人过熟倾诉 / 设定履历宣讲
- 旁白/内心OS 揭示角色不可能知道的隐藏信息（全知剧透：凶手、秘密、计划、尸体…）

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

    report = asyncio.run(_run_all())
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if out:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"报告已写入 {out}")
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
