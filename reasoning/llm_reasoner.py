"""
LLM Reasoner — assembles all signals into a structured prompt and parses
the JSON analysis returned by Bob.

For the hackathon, this module:
1. Builds a self-contained prompt from all collected signals.
2. Writes it to a temp file so Bob can read it directly.
3. Expects Bob to return a JSON block — parses and validates it.
4. Saves prompt + response to analysis_debug.json for transparency.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from models import (
    AnalysisResult,
    AlternativeCause,
    CausalFinding,
    EvidenceItem,
    RepoContext,
    Signal,
)

_MAX_EVIDENCE_ITEMS = 20
_MAX_DIFF_TOTAL_LINES = 300


def _truncate_evidence(evidence: list[str], max_items: int = _MAX_EVIDENCE_ITEMS) -> list[str]:
    return evidence[:max_items]


def _build_prompt(signals: list[Signal], repo_context: RepoContext) -> str:
    """
    Build a self-contained analysis prompt for Bob.
    Returns the full prompt string.
    """
    lines: list[str] = []

    lines.append("You are a senior software engineer performing a regression analysis.")
    lines.append(
        "Your task: identify the most likely change that caused a previously working "
        "project to break, based on the evidence below."
    )
    lines.append("")
    lines.append("## Repository Context")
    lines.append(f"- Name: {repo_context.repo_name}")
    lines.append(f"- Language: {repo_context.detected_language}")
    lines.append(f"- Framework: {repo_context.detected_framework}")
    lines.append(f"- Commit range analysed: {repo_context.commit_range}")
    lines.append(f"- Total commits in range: {repo_context.total_commits_analyzed}")
    lines.append("")

    diff_lines_used = 0

    for signal in signals:
        if signal.severity == "skipped":
            lines.append(f"## Signal: {signal.name.upper()} [SKIPPED]")
            lines.append(signal.evidence[0] if signal.evidence else "No data.")
            lines.append("")
            continue

        lines.append(f"## Signal: {signal.name.upper()} [severity: {signal.severity}]")
        evidence = _truncate_evidence(signal.evidence)
        for item in evidence:
            # Track diff line budget
            if item.startswith("+") or item.startswith("-"):
                diff_lines_used += 1
                if diff_lines_used > _MAX_DIFF_TOTAL_LINES:
                    lines.append("... [diff truncated to stay within context budget]")
                    break
            lines.append(item)
        lines.append("")

    lines.append("## Your Task")
    lines.append(
        "Based on the evidence above, respond with ONLY a valid JSON object "
        "(no markdown fences, no explanation before or after the JSON). "
        "Use this exact schema:"
    )
    lines.append("")
    lines.append(json.dumps({
        "most_likely_cause": {
            "description": "One or two sentence description of the most likely root cause",
            "commit_sha": "short SHA of the most suspicious commit, or empty string if unknown",
            "file": "most relevant changed file, or empty string if unknown"
        },
        "confidence": "high | medium | low",
        "evidence_chain": [
            {"signal": "signal name", "detail": "what this signal tells us"}
        ],
        "alternative_causes": [
            {"description": "alternative explanation", "confidence": "high | medium | low"}
        ],
        "recommended_next_steps": [
            "Specific action the developer should take"
        ]
    }, indent=2))
    lines.append("")
    lines.append(
        "Rules: confidence is 'high' if test failures + a suspicious commit are present, "
        "'medium' if only one strong signal exists, 'low' if evidence is inconclusive. "
        "Keep descriptions concise. List up to 3 next steps. List up to 2 alternative causes."
    )

    return "\n".join(lines)


def _parse_analysis(raw_json: str) -> AnalysisResult | None:
    """Parse and validate the JSON response from Bob."""
    # Strip markdown code fences if Bob wrapped the JSON anyway
    cleaned = re.sub(r"```(?:json)?\s*", "", raw_json).strip()
    # Find the first {...} block
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

    mlc_data = data.get("most_likely_cause", {})
    most_likely_cause = CausalFinding(
        description=mlc_data.get("description", "Unknown"),
        commit_sha=mlc_data.get("commit_sha", ""),
        file=mlc_data.get("file", ""),
    )

    confidence = data.get("confidence", "low")
    if confidence not in ("high", "medium", "low"):
        confidence = "low"

    evidence_chain = [
        EvidenceItem(signal=e.get("signal", ""), detail=e.get("detail", ""))
        for e in data.get("evidence_chain", [])
    ]

    alternative_causes = [
        AlternativeCause(
            description=a.get("description", ""),
            confidence=a.get("confidence", "low"),
        )
        for a in data.get("alternative_causes", [])
    ]

    recommended_next_steps = data.get("recommended_next_steps", [])

    return AnalysisResult(
        most_likely_cause=most_likely_cause,
        confidence=confidence,  # type: ignore[arg-type]
        evidence_chain=evidence_chain,
        alternative_causes=alternative_causes,
        recommended_next_steps=recommended_next_steps,
    )


def _fallback_result(reason: str) -> AnalysisResult:
    return AnalysisResult(
        most_likely_cause=CausalFinding(
            description=f"Analysis inconclusive: {reason}",
            commit_sha="",
            file="",
        ),
        confidence="low",
        evidence_chain=[],
        alternative_causes=[],
        recommended_next_steps=[
            "Review the git diff manually with: git log --oneline",
            "Run the test suite to confirm which tests are failing",
            "Check recent dependency or config changes",
        ],
    )


class LLMReasoner:
    def analyze(
        self, signals: list[Signal], repo_context: RepoContext
    ) -> AnalysisResult:
        prompt = _build_prompt(signals, repo_context)

        # Write prompt to a temp file so Bob (or a human) can read it
        prompt_path = Path(repo_context.repo_path).parent / "what_changed_prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        print(f"\n    📝 Prompt written to: {prompt_path}")
        print(
            "    → Bob will now reason over this prompt.\n"
            "      Paste the prompt content to Bob chat, or use Bob's agent mode to read it automatically."
        )

        # ----------------------------------------------------------------
        # Attempt to read a pre-existing response file (bob_response.json)
        # This allows automated flow: Bob writes response → pipeline reads it
        # ----------------------------------------------------------------
        response_path = Path(repo_context.repo_path).parent / "bob_response.json"
        raw_response: str | None = None

        if response_path.exists():
            raw_response = response_path.read_text(encoding="utf-8")
            print(f"    ✓ Found Bob's response at: {response_path}")
        else:
            # Interactive fallback: ask the user to paste Bob's JSON response
            print(
                "\n    📋 No bob_response.json found. You can either:\n"
                f"       1. Have Bob read '{prompt_path.name}' and paste the JSON response below.\n"
                "       2. Create 'bob_response.json' next to this repo and re-run.\n"
                "       3. Press Enter to skip reasoning and use a placeholder result.\n"
            )
            try:
                user_input = input("    Paste Bob's JSON response (or press Enter to skip): ").strip()
                if user_input:
                    raw_response = user_input
            except (EOFError, KeyboardInterrupt):
                raw_response = None

        # ----------------------------------------------------------------
        # Save debug artefact
        # ----------------------------------------------------------------
        debug_path = Path(repo_context.repo_path).parent / "analysis_debug.json"
        debug_data = {
            "prompt": prompt,
            "raw_response": raw_response or "(none)",
        }
        debug_path.write_text(json.dumps(debug_data, indent=2), encoding="utf-8")

        if not raw_response:
            return _fallback_result("No response from Bob — run the prompt manually and re-run.")

        result = _parse_analysis(raw_response)
        if result is None:
            return _fallback_result("Could not parse Bob's JSON response.")

        return result
