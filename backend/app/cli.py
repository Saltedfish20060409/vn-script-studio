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

    TASKS = [
        ("continue", "续写下一小段：雨夜站台，末班车广播后，两人沉默。Ren'Py 风格。"),
        ("scene", "写一小场戏：学校走廊相遇，一方回避。有对白与旁白，3~6 句。"),
        ("rewrite", "改写：把「他很惊讶，内心OS：怎么会这样。」改成可上演写法，不要内心OS标签。"),
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
            report["cases"].append(
                {
                    "task": task,
                    "chars": len(r["text"]),
                    "passed": passed,
                    "errorCount": audit.get("errorCount", 0),
                    "warnCount": audit.get("warnCount", 0),
                    "issues": [
                        {"severity": i.get("severity"), "code": i.get("code")}
                        for i in (audit.get("issues") or [])[:6]
                    ],
                    "text": r["text"][:400],
                }
            )
            report["summary"]["total"] += 1
            if passed:
                report["summary"]["passed"] += 1
            report["summary"]["errorCount"] += int(audit.get("errorCount", 0))
            report["summary"]["warnCount"] += int(audit.get("warnCount", 0))
            typer.echo(f"[{task}] {'PASS' if passed else 'FAIL'} · error {audit.get('errorCount', 0)} / warn {audit.get('warnCount', 0)}")
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
