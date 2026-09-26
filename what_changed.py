#!/usr/bin/env python3
"""
what_changed.py — CLI entry point for the "What Changed?" analysis pipeline.

Usage:
    python what_changed.py --repo ./my-project
    python what_changed.py --repo ./my-project --since abc1234 --output report.html
    python what_changed.py --repo ./my-project --no-tests
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

# Ensure the project root is on sys.path so sub-modules can import `models`.
sys.path.insert(0, str(Path(__file__).parent))

from collectors.git_collector import GitCollector
from collectors.dependency_checker import DependencyChecker
from collectors.config_checker import ConfigChecker
from collectors.test_runner import TestRunner
from collectors.log_parser import LogParser
from reasoning.llm_reasoner import LLMReasoner
from reporting.renderer import Renderer
from models import RepoContext, Signal


# ---------------------------------------------------------------------------
# Language / framework detection helpers
# ---------------------------------------------------------------------------

def _detect_language(repo_path: str) -> str:
    p = Path(repo_path)
    if (p / "requirements.txt").exists() or (p / "setup.py").exists() or (p / "pyproject.toml").exists():
        return "Python"
    if (p / "package.json").exists():
        return "JavaScript/TypeScript"
    if (p / "pom.xml").exists():
        return "Java"
    if (p / "go.mod").exists():
        return "Go"
    if (p / "Cargo.toml").exists():
        return "Rust"
    return "Unknown"


def _detect_framework(repo_path: str, language: str) -> str:
    p = Path(repo_path)
    if language == "Python":
        req_file = p / "requirements.txt"
        if req_file.exists():
            content = req_file.read_text(errors="replace").lower()
            if "flask" in content:
                return "Flask"
            if "django" in content:
                return "Django"
            if "fastapi" in content:
                return "FastAPI"
    if language == "JavaScript/TypeScript":
        pkg = p / "package.json"
        if pkg.exists():
            content = pkg.read_text(errors="replace").lower()
            if "react" in content:
                return "React"
            if "express" in content:
                return "Express"
            if "next" in content:
                return "Next.js"
    return "Unknown"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class Pipeline:
    """Orchestrates all collectors, the reasoner, and the renderer."""

    def __init__(self, repo_path: str, since_sha: str | None, output: str, no_tests: bool):
        self.repo_path = str(Path(repo_path).resolve())
        self.since_sha = since_sha
        self.output = output
        self.no_tests = no_tests

    def run(self) -> None:
        print(f"\n🔍 What Changed? — analysing {self.repo_path}\n")

        # --- Repo context ------------------------------------------------
        language = _detect_language(self.repo_path)
        framework = _detect_framework(self.repo_path, language)
        repo_name = Path(self.repo_path).name

        # --- Collectors --------------------------------------------------
        print("  [1/5] Collecting git history …")
        git_signal = self._run_collector(
            "git", lambda: GitCollector().collect(self.repo_path, self.since_sha)
        )

        file_change_manifest: list[tuple[str, int]] = git_signal.raw.get("file_change_manifest", [])
        commit_range: str = git_signal.raw.get("commit_range", "HEAD~10..HEAD")
        total_commits: int = git_signal.raw.get("total_commits_analyzed", 0)

        print("  [2/5] Checking dependencies …")
        dep_signal = self._run_collector(
            "dependencies",
            lambda: DependencyChecker().collect(self.repo_path, file_change_manifest, git_signal),
        )

        print("  [3/5] Checking configuration files …")
        cfg_signal = self._run_collector(
            "config",
            lambda: ConfigChecker().collect(self.repo_path, file_change_manifest, git_signal),
        )

        print("  [4/5] Running tests …")
        test_signal = self._run_collector(
            "tests",
            lambda: TestRunner().collect(self.repo_path, skip=self.no_tests),
        )

        print("  [5/5] Parsing logs …")
        log_signal = self._run_collector(
            "logs",
            lambda: LogParser().collect(self.repo_path),
        )

        signals = [git_signal, dep_signal, cfg_signal, test_signal, log_signal]

        repo_context = RepoContext(
            repo_name=repo_name,
            detected_language=language,
            detected_framework=framework,
            commit_range=commit_range,
            total_commits_analyzed=total_commits,
            repo_path=self.repo_path,
        )

        # --- Reasoning ---------------------------------------------------
        print("\n🤖 Bob is reasoning over the evidence …")
        reasoner = LLMReasoner()
        try:
            analysis = reasoner.analyze(signals, repo_context)
        except NotImplementedError:
            print("    ⚠️  LLM reasoning not yet implemented — using placeholder result.")
            from models import AnalysisResult, CausalFinding
            analysis = AnalysisResult(
                most_likely_cause=CausalFinding(
                    description="Analysis pending — LLM reasoner not yet implemented"
                ),
                confidence="low",
            )

        # --- Rendering ---------------------------------------------------
        print("\n📄 Generating report …")
        try:
            Renderer().render(analysis, signals, repo_context, self.output)
        except NotImplementedError:
            print("    ⚠️  Renderer not yet implemented — skipping HTML output.")
            return
        print(f"\n✓ Report written to {self.output}")
        print(
            "\n💬 To continue the investigation in Bob chat, paste this prompt:\n"
            f'   "I ran What Changed? on {repo_name}. '
            f'The most likely cause is: {analysis.most_likely_cause.description}. '
            "Help me verify and fix it.\""
        )

    def _run_collector(self, name: str, fn) -> Signal:
        """Run a collector, catching any errors and returning a skipped Signal."""
        try:
            return fn()
        except NotImplementedError:
            return Signal(name=name, severity="skipped", evidence=["Collector not yet implemented"], raw={})
        except Exception as exc:  # noqa: BLE001
            print(f"    ⚠️  {name} collector failed: {exc}")
            if os.environ.get("WHAT_CHANGED_DEBUG"):
                traceback.print_exc()
            return Signal(name=name, severity="skipped", evidence=[f"Collector error: {exc}"], raw={})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="what_changed",
        description="Identify what change caused a previously working project to break.",
    )
    parser.add_argument(
        "--repo",
        required=True,
        metavar="PATH",
        help="Path to the local Git repository to analyse.",
    )
    parser.add_argument(
        "--since",
        default=None,
        metavar="SHA",
        help="Commit SHA to diff from (last known good). Defaults to most recent tag or HEAD~10.",
    )
    parser.add_argument(
        "--output",
        default="report.html",
        metavar="FILE",
        help="Output path for the HTML report (default: report.html).",
    )
    parser.add_argument(
        "--no-tests",
        action="store_true",
        help="Skip running the test suite.",
    )

    args = parser.parse_args()

    if not Path(args.repo).exists():
        print(f"Error: repository path does not exist: {args.repo}", file=sys.stderr)
        sys.exit(1)

    Pipeline(
        repo_path=args.repo,
        since_sha=args.since,
        output=args.output,
        no_tests=args.no_tests,
    ).run()


if __name__ == "__main__":
    main()
