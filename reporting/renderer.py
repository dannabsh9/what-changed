"""HTML Report Renderer — converts AnalysisResult + signals into a self-contained report.html."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from models import AnalysisResult, RepoContext, Signal


class Renderer:
    def render(
        self,
        analysis: AnalysisResult,
        signals: list[Signal],
        repo_context: RepoContext,
        output_path: str,
    ) -> None:
        template_dir = Path(__file__).parent / "templates"
        env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True,
        )
        template = env.get_template("report.html.j2")

        rendered = template.render(
            analysis=analysis,
            signals=signals,
            repo_context=repo_context,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )

        Path(output_path).write_text(rendered, encoding="utf-8")
