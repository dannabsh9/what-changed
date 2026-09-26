"""Dependency Checker — detects changed dependency manifests and lockfiles."""
from __future__ import annotations

import re
from pathlib import Path

import git

from models import Signal

# Manifest files to inspect, in priority order
_MANIFEST_FILES = [
    "requirements.txt",
    "setup.cfg",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "Pipfile",
    "Pipfile.lock",
    "pom.xml",
    "build.gradle",
    "go.sum",
    "go.mod",
    "Cargo.toml",
    "Cargo.lock",
]

# Lockfiles — we only report changed package/version lines, not a full diff
_LOCKFILE_NAMES = {"package-lock.json", "yarn.lock", "Pipfile.lock", "go.sum", "Cargo.lock"}


def _blob_text(commit: git.Commit, filepath: str) -> str | None:
    """Return the text content of a file at a given commit, or None if absent."""
    try:
        blob = commit.tree[filepath]
        data = blob.data_stream.read()
        return data.decode("utf-8", errors="replace")
    except (KeyError, AttributeError):
        return None


def _diff_requirements_txt(before: str, after: str) -> list[str]:
    """Return list of changed dependency strings for requirements.txt style files."""
    def parse(text: str) -> dict[str, str]:
        pkgs: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Normalise: package==version, package>=version, package~=version, etc.
            m = re.match(r"^([A-Za-z0-9_\-\.]+)\s*([><=!~^]+.*)?$", line)
            if m:
                pkgs[m.group(1).lower()] = m.group(2) or ""
        return pkgs

    before_pkgs = parse(before)
    after_pkgs = parse(after)
    changes: list[str] = []

    all_keys = set(before_pkgs) | set(after_pkgs)
    for key in sorted(all_keys):
        b_ver = before_pkgs.get(key)
        a_ver = after_pkgs.get(key)
        if b_ver is None:
            changes.append(f"ADDED:   {key} {a_ver}".strip())
        elif a_ver is None:
            changes.append(f"REMOVED: {key} {b_ver}".strip())
        elif b_ver != a_ver:
            changes.append(f"CHANGED: {key}  {b_ver} -> {a_ver}".strip())
    return changes


def _diff_package_json(before: str, after: str) -> list[str]:
    """Extract dependency version changes from package.json."""
    import json
    changes: list[str] = []
    try:
        b = json.loads(before)
        a = json.loads(after)
    except Exception:  # noqa: BLE001
        return []

    for section in ("dependencies", "devDependencies", "peerDependencies"):
        b_deps = b.get(section, {})
        a_deps = a.get(section, {})
        all_keys = set(b_deps) | set(a_deps)
        for key in sorted(all_keys):
            bv = b_deps.get(key)
            av = a_deps.get(key)
            if bv is None:
                changes.append(f"ADDED [{section}]:   {key} {av}")
            elif av is None:
                changes.append(f"REMOVED [{section}]: {key} {bv}")
            elif bv != av:
                changes.append(f"CHANGED [{section}]: {key}  {bv} -> {av}")
    return changes


def _diff_lockfile_versions(before: str, after: str, filename: str) -> list[str]:
    """
    For lockfiles, extract only lines that look like version pins and report
    those that changed. Avoids diffing the whole (potentially enormous) file.
    """
    # Match lines like:  "  version: 1.2.3"  or  "  resolved \"...#abc\""
    # We'll use a simple heuristic: extract (name, version) pairs.
    changes: list[str] = []

    if filename == "go.sum":
        # go.sum lines: "module/path v1.2.3 hash"
        def parse_go(text: str) -> dict[str, str]:
            pkgs: dict[str, str] = {}
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    pkgs[parts[0]] = parts[1]
            return pkgs
        b_pkgs = parse_go(before)
        a_pkgs = parse_go(after)
    else:
        # Generic: extract lines with version-like patterns
        version_re = re.compile(r'"?([A-Za-z0-9_\-\./]+)"?\s*[=:@]\s*"?([0-9][^\s",]+)"?')

        def parse_generic(text: str) -> dict[str, str]:
            pkgs: dict[str, str] = {}
            for line in text.splitlines():
                m = version_re.search(line)
                if m:
                    pkgs[m.group(1)] = m.group(2)
            return pkgs
        b_pkgs = parse_generic(before)
        a_pkgs = parse_generic(after)

    all_keys = set(b_pkgs) | set(a_pkgs)
    for key in sorted(all_keys):
        bv = b_pkgs.get(key)
        av = a_pkgs.get(key)
        if bv is None:
            changes.append(f"ADDED:   {key} {av}")
        elif av is None:
            changes.append(f"REMOVED: {key} {bv}")
        elif bv != av:
            changes.append(f"CHANGED: {key}  {bv} -> {av}")

    # Cap at 30 changes to keep evidence readable
    return changes[:30]


class DependencyChecker:
    def collect(
        self,
        repo_path: str,
        file_change_manifest: list[tuple[str, int]],
        git_signal: Signal,
    ) -> Signal:
        repo = git.Repo(repo_path)
        since_sha: str = git_signal.raw.get("since_sha", "")

        if not since_sha or since_sha == "NULL_TREE":
            return Signal(
                name="dependencies",
                severity="skipped",
                evidence=["No base commit available to diff dependencies against."],
                raw={},
            )

        try:
            base_commit = repo.commit(since_sha)
        except Exception as exc:  # noqa: BLE001
            return Signal(
                name="dependencies",
                severity="skipped",
                evidence=[f"Could not resolve base commit: {exc}"],
                raw={},
            )

        head_commit = repo.head.commit
        changed_paths = {fp for fp, _ in file_change_manifest}

        evidence: list[str] = []
        changed_manifests: list[str] = []
        has_direct_change = False

        for manifest in _MANIFEST_FILES:
            if manifest not in changed_paths:
                continue

            before = _blob_text(base_commit, manifest)
            after = _blob_text(head_commit, manifest)

            if before is None and after is None:
                continue

            changed_manifests.append(manifest)
            before = before or ""
            after = after or ""

            if manifest == "requirements.txt":
                diffs = _diff_requirements_txt(before, after)
                has_direct_change = True
            elif manifest == "package.json":
                diffs = _diff_package_json(before, after)
                has_direct_change = True
            elif manifest in _LOCKFILE_NAMES:
                diffs = _diff_lockfile_versions(before, after, manifest)
            else:
                # Generic: report that the file changed, show a short diff
                b_lines = set(before.splitlines())
                a_lines = set(after.splitlines())
                added = [f"+ {l}" for l in sorted(a_lines - b_lines)][:15]
                removed = [f"- {l}" for l in sorted(b_lines - a_lines)][:15]
                diffs = removed + added
                has_direct_change = True

            if diffs:
                evidence.append(f"--- {manifest} ---")
                evidence.extend(diffs[:20])

        if not evidence:
            return Signal(
                name="dependencies",
                severity="low",
                evidence=["No dependency manifest changes detected."],
                raw={"changed_manifests": []},
            )

        severity = "high" if has_direct_change else "medium"
        evidence.insert(0, f"Changed dependency files: {', '.join(changed_manifests)}")

        return Signal(
            name="dependencies",
            severity=severity,  # type: ignore[arg-type]
            evidence=evidence,
            raw={"changed_manifests": changed_manifests},
        )
