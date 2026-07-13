"""Render Markdown / HTML reports from a run JSON."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATES = Path(__file__).parent / "templates"


def render(run_path: str | Path, output: str | Path) -> Path:
    """Render report; format inferred from output extension (.md or .html)."""
    run = json.loads(Path(run_path).read_text(encoding="utf-8"))
    out = Path(output)
    fmt = "html" if out.suffix.lower() in (".html", ".htm") else "md"
    env = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=(fmt == "html"))
    template = env.get_template(f"report.{fmt}.j2")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(template.render(run=run), encoding="utf-8")
    return out
