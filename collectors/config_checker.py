"""Config Checker — detects changed configuration files with secret redaction."""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import git

from models import Signal

# Patterns that identify configuration files (not source code)
_CONFIG_PATTERNS = [
    "*.env",
    ".env",
    ".env.*",
    "*.yaml",
    "*.yml",
    "*.toml",
    "*.ini",
    "*.conf",
    "*.cfg",
    "Dockerfile",
    "Dockerfile.*",
    "docker-compose*.yml",
    "docker-compose*.yaml",
    ".github/**",
    "*.json",  # filtered below to exclude package*.json and tsconfig*
]

# JSON files to exclude from config checking
_EXCLUDE_JSON_PATTERNS = [
    "package.json",
    "package-lock.json",
    "tsconfig*.json",
    "*.test.json",
    "*.spec.json",
]

# Patterns that indicate a secrets/env file (high severity)
_SECRETS_PATTERNS = [
    "*.env", ".env", ".env.*",
    "*secret*", "*credential*",
]

# Lines whose values should be redacted
_REDACT_KEYWORDS_RE = re.compile(
    r"(password|secret|token|api_key|apikey|credentials?|auth_?key|private_?key|access_?key)",
    re.IGNORECASE,
)

_MAX_DIFF_LINES_PER_FILE = 20


def _matches_any(filepath: str, patterns: list[str]) -> bool:
    name = Path(filepath).name
    for pat in patterns:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(filepath, pat):
            return True
    return False


def _is_config_file(filepath: str) -> bool:
    if _matches_any(filepath, _CONFIG_PATTERNS):
        # Exclude specific JSON patterns
        if filepath.endswith(".json") and _matches_any(filepath, _EXCLUDE_JSON_PATTERNS):
            return False
        return True
    return False


def _is_secrets_file(filepath: str) -> bool:
    name = Path(filepath).name
    return _matches_any(name, _SECRETS_PATTERNS)


def _redact_line(line: str) -> str:
    """Redact the value portion of sensitive key=value lines."""
    # Match patterns like: KEY=value, key: value, "key": "value"
    redact_re = re.compile(
        r"^(\s*[\+\-]?\s*[\"']?[\w\-\.]+[\"']?\s*[=:]\s*)(.+)$"
    )
    if _REDACT_KEYWORDS_RE.search(line):
        m = redact_re.match(line)
        if m:
            return m.group(1) + "[REDACTED]"
    return line


def _blob_text(commit: git.Commit, filepath: str) -> str | None:
    """Return file content at a given commit, or None if not present."""
    try:
        # Handle nested paths
        parts = filepath.replace("\\", "/").split("/")
        obj = commit.tree
        for part in parts:
            obj = obj[part]
        data = obj.data_stream.read()
        return data.decode("utf-8", errors="replace")
    except (KeyError, AttributeError):
        return None


def _make_diff(before: str, after: str, max_lines: int = _MAX_DIFF_LINES_PER_FILE) -> list[str]:
    """Produce a simple +/- line diff between two text blobs."""
    b_lines = before.splitlines()
    a_lines = after.splitlines()
    b_set = set(b_lines)
    a_set = set(a_lines)

    diff_lines: list[str] = []
    for line in b_lines:
        if line not in a_set:
            diff_lines.append(_redact_line(f"- {line}"))
    for line in a_lines:
        if line not in b_set:
            diff_lines.append(_redact_line(f"+ {line}"))

    return diff_lines[:max_lines]


class ConfigChecker:
    def collect(
        self,
        repo_path: str,
        file_change_manifest: list[tuple[str, int]],
        git_signal: Signal,
    ) -> Signal:
        since_sha: str = git_signal.raw.get("since_sha", "")

        if not since_sha or since_sha == "NULL_TREE":
            return Signal(
                name="config",
                severity="skipped",
                evidence=["No base commit available to diff config against."],
                raw={},
            )

        repo = git.Repo(repo_path)
        try:
            base_commit = repo.commit(since_sha)
        except Exception as exc:  # noqa: BLE001
            return Signal(
                name="config",
                severity="skipped",
                evidence=[f"Could not resolve base commit: {exc}"],
                raw={},
            )

        head_commit = repo.head.commit

        evidence: list[str] = []
        changed_configs: list[str] = []
        has_secrets_change = False

        for filepath, _ in file_change_manifest:
            if not _is_config_file(filepath):
                continue

            before = _blob_text(base_commit, filepath) or ""
            after = _blob_text(head_commit, filepath) or ""

            if before == after:
                continue

            changed_configs.append(filepath)
            if _is_secrets_file(filepath):
                has_secrets_change = True

            diff_lines = _make_diff(before, after)
            if diff_lines:
                evidence.append(f"--- {filepath} ---")
                evidence.extend(diff_lines)

        if not evidence:
            return Signal(
                name="config",
                severity="low",
                evidence=["No configuration file changes detected."],
                raw={"changed_configs": []},
            )

        severity = "high" if has_secrets_change else "medium"
        evidence.insert(0, f"Changed config files: {', '.join(changed_configs)}")

        return Signal(
            name="config",
            severity=severity,  # type: ignore[arg-type]
            evidence=evidence,
            raw={"changed_configs": changed_configs, "has_secrets_change": has_secrets_change},
        )
