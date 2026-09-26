"""Shared dataclasses used across all pipeline modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


SeverityLevel = Literal["high", "medium", "low", "skipped"]


@dataclass
class Signal:
    """Output produced by every collector module."""

    name: str
    severity: SeverityLevel
    evidence: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def is_actionable(self) -> bool:
        return self.severity in ("high", "medium")


@dataclass
class RepoContext:
    """Metadata about the repository being analysed."""

    repo_name: str
    detected_language: str
    detected_framework: str
    commit_range: str
    total_commits_analyzed: int
    repo_path: str


@dataclass
class CausalFinding:
    description: str
    commit_sha: str = ""
    file: str = ""


@dataclass
class EvidenceItem:
    signal: str
    detail: str


@dataclass
class AlternativeCause:
    description: str
    confidence: str


@dataclass
class AnalysisResult:
    """Structured output from the LLM reasoning step."""

    most_likely_cause: CausalFinding
    confidence: Literal["high", "medium", "low"]
    evidence_chain: list[EvidenceItem] = field(default_factory=list)
    alternative_causes: list[AlternativeCause] = field(default_factory=list)
    recommended_next_steps: list[str] = field(default_factory=list)
