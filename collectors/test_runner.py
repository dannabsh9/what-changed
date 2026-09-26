"""Test Runner — detects and runs the project's test suite, capturing failures."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from models import Signal

_TEST_TIMEOUT = 120  # seconds


def _detect_framework(repo_path: str) -> tuple[str, list[str]] | None:
    """
    Return (framework_name, command_list) or None if no framework detected.
    Detection order: pytest -> npm test -> mvn test.
    """
    p = Path(repo_path)

    # --- pytest ---
    pytest_indicators = [
        p / "pytest.ini",
        p / "setup.cfg",
        p / "pyproject.toml",
        p / "tox.ini",
    ]
    has_pytest_cfg = any(f.exists() for f in pytest_indicators)

    # Also accept a tests/ or test/ directory with .py files
    has_test_dir = any(
        list((p / d).glob("test_*.py")) or list((p / d).glob("*_test.py"))
        for d in ("tests", "test", ".")
        if (p / d).is_dir()
    )

    if has_pytest_cfg or has_test_dir:
        # Prefer `python -m pytest` so it always resolves against the running
        # interpreter even when the `pytest` script is not on PATH.
        return ("pytest", [sys.executable, "-m", "pytest", "--tb=short", "-q", "--no-header"])

    # --- npm test ---
    pkg_json = p / "package.json"
    if pkg_json.exists():
        try:
            import json
            data = json.loads(pkg_json.read_text(errors="replace"))
            if "test" in data.get("scripts", {}):
                return ("npm", ["npm", "test", "--", "--watchAll=false"])  # npm is always on PATH or absent
        except Exception:  # noqa: BLE001
            pass

    # --- Maven ---
    if (p / "pom.xml").exists():
        return ("maven", ["mvn", "test", "-q"])

    return None


def _parse_pytest_output(output: str) -> tuple[list[str], int, int]:
    """
    Parse pytest output and return (failures_evidence, passed_count, failed_count).
    """
    evidence: list[str] = []
    passed = 0
    failed = 0

    # Summary line: "3 failed, 12 passed in 0.45s"
    summary_re = re.compile(r"(\d+)\s+failed", re.IGNORECASE)
    passed_re = re.compile(r"(\d+)\s+passed", re.IGNORECASE)

    m = summary_re.search(output)
    if m:
        failed = int(m.group(1))
    m = passed_re.search(output)
    if m:
        passed = int(m.group(1))

    # Extract FAILED lines and the short tracebacks that follow
    lines = output.splitlines()
    capture = False
    current_block: list[str] = []
    failure_count = 0

    for line in lines:
        if re.match(r"^FAILED\s+", line):
            if current_block:
                evidence.extend(current_block[:8])
                evidence.append("")
            current_block = [line]
            failure_count += 1
            capture = True
            if failure_count >= 10:
                evidence.append("... [further failures truncated]")
                break
        elif capture:
            if line.startswith("=") or line.startswith("_"):
                # Section separator — end of block
                if current_block:
                    evidence.extend(current_block[:8])
                    evidence.append("")
                current_block = []
                capture = False
            else:
                current_block.append(line)

    if current_block:
        evidence.extend(current_block[:8])

    return evidence, passed, failed


def _parse_generic_output(output: str) -> tuple[list[str], int, int]:
    """Generic failure parser for npm/maven output."""
    evidence: list[str] = []
    error_re = re.compile(r"(FAIL|ERROR|FAILED|BUILD FAILURE|✕|✗)", re.IGNORECASE)
    for line in output.splitlines():
        if error_re.search(line):
            evidence.append(line.rstrip())
    return evidence[:20], 0, len(evidence)


class TestRunner:
    def collect(self, repo_path: str, skip: bool = False) -> Signal:
        if skip:
            return Signal(
                name="tests",
                severity="skipped",
                evidence=["Test runner skipped via --no-tests flag."],
                raw={"skipped": True},
            )

        detected = _detect_framework(repo_path)
        if detected is None:
            return Signal(
                name="tests",
                severity="skipped",
                evidence=["No supported test framework detected (looked for pytest, npm test, mvn)."],
                raw={"framework": None},
            )

        framework, cmd = detected

        try:
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=_TEST_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return Signal(
                name="tests",
                severity="medium",
                evidence=[f"Test suite timed out after {_TEST_TIMEOUT}s — possible infinite loop or hanging test."],
                raw={"framework": framework, "timed_out": True},
            )
        except FileNotFoundError:
            return Signal(
                name="tests",
                severity="skipped",
                evidence=[f"Test command not found: {cmd[0]}. Install the test runner and retry."],
                raw={"framework": framework},
            )

        combined_output = result.stdout + ("\n" + result.stderr if result.stderr else "")

        if framework == "pytest":
            failure_evidence, passed, failed = _parse_pytest_output(combined_output)
        else:
            failure_evidence, passed, failed = _parse_generic_output(combined_output)

        exit_code = result.returncode
        all_passed = exit_code == 0

        if all_passed:
            return Signal(
                name="tests",
                severity="low",
                evidence=[f"All tests passed (framework: {framework}, exit code: {exit_code})."],
                raw={
                    "framework": framework,
                    "exit_code": exit_code,
                    "passed": passed,
                    "failed": 0,
                },
            )

        evidence: list[str] = [
            f"Tests FAILED (framework: {framework}, exit code: {exit_code})",
            f"Passed: {passed}  Failed: {failed}",
            "",
        ]
        evidence.extend(failure_evidence)

        return Signal(
            name="tests",
            severity="high",
            evidence=evidence,
            raw={
                "framework": framework,
                "exit_code": exit_code,
                "passed": passed,
                "failed": failed,
                "raw_output": combined_output[:3000],
            },
        )
