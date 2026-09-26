"""Git Collector — extracts commit history, diffs, and file change manifest."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import git

from models import Signal

# File patterns to skip (generated / binary / large lockfiles)
_SKIP_EXTENSIONS = {
    ".lock", ".min.js", ".map", ".png", ".jpg", ".jpeg", ".gif",
    ".ico", ".svg", ".woff", ".woff2", ".ttf", ".eot", ".pdf",
    ".zip", ".tar", ".gz", ".exe", ".dll", ".so", ".dylib",
    ".pyc", ".class",
}
_SKIP_PATH_FRAGMENTS = {
    "node_modules/", "dist/", "build/", ".git/", "__pycache__/",
    ".tox/", ".venv/", "venv/", ".eggs/",
}
_MAX_DIFF_LINES_PER_FILE = 500
_MAX_MANIFEST_FILES = 20
_FALLBACK_LOOKBACK = 10  # commits to look back when no tag exists


def _should_skip(filepath: str) -> bool:
    ext = Path(filepath).suffix.lower()
    if ext in _SKIP_EXTENSIONS:
        return True
    fp = filepath.replace("\\", "/")
    for frag in _SKIP_PATH_FRAGMENTS:
        if frag in fp:
            return True
    return False


def _get_since_sha(repo: git.Repo, since_sha: str | None) -> str:
    """Return the best available 'last known good' commit SHA."""
    if since_sha:
        return since_sha

    # Prefer most recent tag
    if repo.tags:
        sorted_tags = sorted(repo.tags, key=lambda t: t.commit.committed_date, reverse=True)
        return sorted_tags[0].commit.hexsha

    # Fall back to HEAD~N (clamp to available history)
    commits = list(repo.iter_commits("HEAD", max_count=_FALLBACK_LOOKBACK + 1))
    if len(commits) > _FALLBACK_LOOKBACK:
        return commits[_FALLBACK_LOOKBACK].hexsha
    if len(commits) > 1:
        return commits[-1].hexsha
    # Single-commit repo: diff against empty tree
    return git.NULL_TREE  # type: ignore[attr-defined]


class GitCollector:
    def collect(self, repo_path: str, since_sha: str | None = None) -> Signal:
        repo = git.Repo(repo_path)
        since = _get_since_sha(repo, since_sha)

        # ------------------------------------------------------------------
        # Collect commits in range
        # ------------------------------------------------------------------
        if since is git.NULL_TREE:
            commits_in_range = list(repo.iter_commits("HEAD"))
            commit_range = "initial..HEAD"
        else:
            since_short = since[:8] if isinstance(since, str) and len(since) >= 8 else str(since)
            commit_range = f"{since_short}..HEAD"
            commits_in_range = list(repo.iter_commits(f"{since}..HEAD"))

        total_commits = len(commits_in_range)

        # ------------------------------------------------------------------
        # Build per-commit summaries
        # ------------------------------------------------------------------
        commit_summaries: list[dict[str, Any]] = []
        for c in commits_in_range:
            changed_files = []
            try:
                parent = c.parents[0] if c.parents else git.NULL_TREE
                for diff in c.diff(parent):
                    fp = diff.b_path or diff.a_path or ""
                    if not _should_skip(fp):
                        changed_files.append(fp)
            except Exception:  # noqa: BLE001
                pass
            commit_summaries.append({
                "sha": c.hexsha[:8],
                "message": c.message.strip().splitlines()[0][:120],
                "author": str(c.author),
                "timestamp": c.committed_datetime.isoformat(),
                "changed_files": changed_files,
            })

        # ------------------------------------------------------------------
        # Build file change manifest and collect diffs
        # ------------------------------------------------------------------
        file_line_counts: dict[str, int] = {}
        file_diffs: dict[str, str] = {}

        # Base commit for diffing
        if since is git.NULL_TREE:
            base = git.NULL_TREE
        else:
            try:
                base = repo.commit(since)
            except Exception:  # noqa: BLE001
                base = git.NULL_TREE

        head = repo.head.commit

        try:
            diff_index = head.diff(base, create_patch=True)
        except Exception:  # noqa: BLE001
            diff_index = []

        for diff_item in diff_index:
            fp = diff_item.b_path or diff_item.a_path or ""
            if _should_skip(fp):
                continue

            # Count lines changed
            lines_added = 0
            lines_removed = 0
            raw_diff = ""
            try:
                patch = diff_item.diff
                if isinstance(patch, bytes):
                    patch = patch.decode("utf-8", errors="replace")
                lines = patch.splitlines()
                # Cap diff at max lines
                if len(lines) > _MAX_DIFF_LINES_PER_FILE:
                    lines = lines[:_MAX_DIFF_LINES_PER_FILE]
                    lines.append(f"... [truncated at {_MAX_DIFF_LINES_PER_FILE} lines]")
                raw_diff = "\n".join(lines)
                for line in lines:
                    if line.startswith("+") and not line.startswith("+++"):
                        lines_added += 1
                    elif line.startswith("-") and not line.startswith("---"):
                        lines_removed += 1
            except Exception:  # noqa: BLE001
                pass

            total_changed = lines_added + lines_removed
            file_line_counts[fp] = file_line_counts.get(fp, 0) + total_changed
            if raw_diff:
                file_diffs[fp] = raw_diff

        # Sort manifest by most-changed, cap at top 20
        file_change_manifest = sorted(
            file_line_counts.items(), key=lambda x: x[1], reverse=True
        )[:_MAX_MANIFEST_FILES]

        # ------------------------------------------------------------------
        # Determine severity
        # ------------------------------------------------------------------
        source_extensions = {".py", ".js", ".ts", ".java", ".go", ".rs", ".rb", ".php", ".cs", ".cpp", ".c"}
        has_source_changes = any(
            Path(fp).suffix.lower() in source_extensions
            for fp, _ in file_change_manifest
        )
        severity = "high" if has_source_changes else "medium"

        # ------------------------------------------------------------------
        # Build evidence list
        # ------------------------------------------------------------------
        evidence: list[str] = []
        evidence.append(f"Analysed {total_commits} commit(s) in range {commit_range}")
        for c in commit_summaries[:10]:  # cap at 10 commits in evidence
            evidence.append(
                f"[{c['sha']}] {c['message']} — {c['author']} @ {c['timestamp'][:10]}"
            )
        if file_change_manifest:
            evidence.append(
                "Top changed files: "
                + ", ".join(f"{fp} ({n} lines)" for fp, n in file_change_manifest[:5])
            )

        return Signal(
            name="git",
            severity=severity,  # type: ignore[arg-type]
            evidence=evidence,
            raw={
                "commit_range": commit_range,
                "total_commits_analyzed": total_commits,
                "file_change_manifest": file_change_manifest,
                "commit_summaries": commit_summaries,
                "file_diffs": file_diffs,
                "since_sha": since if isinstance(since, str) else "NULL_TREE",
            },
        )
