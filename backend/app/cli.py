"""CLI: python -m app.cli demo|export|ai"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer

from app.core import create_demo_project, export_to_renpy, normalize_project, run_ai
from app.core.ai import DeepSeekConfig
from app.domain.types import AiRequest
from app.config import get_settings

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


if __name__ == "__main__":
    cli()
