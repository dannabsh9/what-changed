"""Log Parser — scans log files for ERROR/EXCEPTION/FATAL patterns."""
from __future__ import annotations

import re
from pathlib import Path

from models import Signal

_MAX_FILES = 5
_MAX_LINES_PER_FILE = 1000
_CONTEXT_LINES = 3  # lines of context around each hit

# Patterns that signal a problem
_ERROR_RE = re.compile(
    r"\b(ERROR|EXCEPTION|FATAL|TRACEBACK|CRITICAL|CAUSED BY)\b",
    re.IGNORECASE,
)

# Patterns to strip for deduplication: timestamps, PIDs, hex addresses
_NORMALIZE_RE = re.compile(
    r"""
    \d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?  # ISO timestamps
    |\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}                                   # US timestamps
    |\[\d+\]                                                                    # PIDs like [1234]
    |0x[0-9a-fA-F]+                                                            # hex addresses
    |\s+at\s+0x\w+                                                              # at 0x... frames
    """,
    re.VERBOSE,
)


def _normalize(line: str) -> str:
    """Strip variable parts for deduplication."""
    return _NORMALIZE_RE.sub("", line).strip()


def _discover_log_files(repo_path: str) -> list[Path]:
    """Find log files up to 2 levels deep."""
    root = Path(repo_path)
    candidates: list[Path] = []

    # Direct *.log files in root
    candidates.extend(root.glob("*.log"))

    # One level deep in common log directories
    for log_dir_name in ("logs", "log", ".log", "var"):
        log_dir = root / log_dir_name
        if log_dir.is_dir():
            candidates.extend(log_dir.glob("*.log"))
            # Two levels deep
            for subdir in log_dir.iterdir():
                if subdir.is_dir():
                    candidates.extend(subdir.glob("*.log"))

    # Deduplicate and sort by modification time (newest first)
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in sorted(candidates, key=lambda f: f.stat().st_mtime if f.exists() else 0, reverse=True):
        if p not in seen:
            seen.add(p)
            unique.append(p)

    return unique[:_MAX_FILES]


def _extract_errors(log_path: Path) -> list[str]:
    """
    Read up to _MAX_LINES_PER_FILE lines and return context blocks around error hits.
    """
    try:
        lines = log_path.read_text(errors="replace").splitlines()[:_MAX_LINES_PER_FILE]
    except OSError:
        return []

    hits: list[tuple[int, str]] = []  # (line_index, normalized_key) for dedup
    seen_normalized: set[str] = set()
    results: list[str] = []

    for i, line in enumerate(lines):
        if not _ERROR_RE.search(line):
            continue

        norm = _normalize(line)
        if norm in seen_normalized:
            continue
        seen_normalized.add(norm)

        # Collect context: _CONTEXT_LINES before and after
        start = max(0, i - _CONTEXT_LINES)
        end = min(len(lines), i + _CONTEXT_LINES + 1)
        block = lines[start:end]
        results.append(f"[{log_path.name}:L{i + 1}]")
        results.extend(block)
        results.append("")  # blank separator

    return results


class LogParser:
    def collect(self, repo_path: str) -> Signal:
        log_files = _discover_log_files(repo_path)

        if not log_files:
            return Signal(
                name="logs",
                severity="low",
                evidence=["No log files found."],
                raw={"log_files_found": []},
            )

        all_evidence: list[str] = []
        has_fatal = False
        has_error = False
        files_with_errors: list[str] = []

        for log_path in log_files:
            blocks = _extract_errors(log_path)
            if blocks:
                files_with_errors.append(log_path.name)
                all_evidence.extend(blocks)
                # Determine severity upgrade
                content = " ".join(blocks).upper()
                if "FATAL" in content or "EXCEPTION" in content or "TRACEBACK" in content:
                    has_fatal = True
                elif "ERROR" in content or "CRITICAL" in content:
                    has_error = True

        if not all_evidence:
            return Signal(
                name="logs",
                severity="low",
                evidence=[
                    f"Scanned {len(log_files)} log file(s), no error patterns found.",
                    f"Files: {', '.join(p.name for p in log_files)}",
                ],
                raw={"log_files_found": [str(p) for p in log_files]},
            )

        severity: str
        if has_fatal:
            severity = "high"
        elif has_error:
            severity = "medium"
        else:
            severity = "low"

        summary = (
            f"Found error patterns in {len(files_with_errors)} log file(s): "
            f"{', '.join(files_with_errors)}"
        )
        all_evidence.insert(0, summary)

        # Cap total evidence at 50 items
        all_evidence = all_evidence[:50]

        return Signal(
            name="logs",
            severity=severity,  # type: ignore[arg-type]
            evidence=all_evidence,
            raw={
                "log_files_found": [str(p) for p in log_files],
                "files_with_errors": files_with_errors,
            },
        )
