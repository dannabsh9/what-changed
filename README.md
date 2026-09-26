# What Changed?

> **IBM Bob Hackathon Prototype** — Identify the change that broke your project.

"What Changed?" is a CLI tool that analyses a local Git repository and produces a ranked, evidence-based HTML report identifying the most likely commit or change that caused a previously working project to break.

---

## How It Works

```
python what_changed.py --repo ./my-project
```

The pipeline runs 5 signal collectors in order:

| Signal | What it analyses |
|--------|-----------------|
| **Git** | Commits, diffs, file change manifest |
| **Dependencies** | Changed `requirements.txt`, `package.json`, lockfiles |
| **Config** | Changed `.env`, YAML, Dockerfile, etc. (secrets redacted) |
| **Tests** | Auto-detected pytest / npm test / mvn — captures failures |
| **Logs** | Scans `*.log` files for ERROR/EXCEPTION patterns |

Bob then reasons over all signals and produces:
1. A **confidence-rated root cause finding** with a commit SHA and file pointer
2. A full **evidence chain** explaining why each signal matters
3. **Recommended next steps** to verify and fix the issue
4. An **HTML report** you can open in any browser and share offline
5. A **suggested Bob chat prompt** to continue the investigation interactively

---

## Prerequisites

- Python 3.11+
- No external services or API keys required

---

## Quickstart

### Run the built-in demo (recommended for judges)

```bash
cd what-changed
bash demo.sh
```

This will:
1. Install dependencies
2. Build the demo fixture repo (Flask app with an intentional breaking change)
3. Run the full analysis
4. Open `demo_report.html` in your browser

### Run against your own repository

```bash
# Install dependencies
pip install -r requirements.txt

# Analyse a repo (auto-detects last known good commit)
python what_changed.py --repo /path/to/your-repo

# Specify a known-good commit
python what_changed.py --repo /path/to/your-repo --since abc1234

# Skip running tests (faster)
python what_changed.py --repo /path/to/your-repo --no-tests

# Custom output path
python what_changed.py --repo /path/to/your-repo --output my-report.html
```

---

## Bob Reasoning Flow

After signal collection, the tool writes a structured prompt to `what_changed_prompt.txt`.

**Option A — Interactive (default):** The tool pauses and asks you to paste Bob's JSON response.  
**Option B — Automated:** Place Bob's JSON response in `bob_response.json` next to the repo and re-run. The tool reads it automatically.

The raw prompt and response are saved to `analysis_debug.json` for full transparency.

---

## Demo Fixture

The `demo/` directory (created by `setup_demo.py`) contains a small Flask app with this commit history:

| Commit | Change | Effect |
|--------|--------|--------|
| 1 | Baseline Flask app + tests | ✅ All tests pass |
| 2 | `flask 2.3.2 → 3.0.0` | Dependency bump |
| 3 | Wrong `DATABASE_URL`, `DEBUG=True` | Config change |
| 4 | `a // b` instead of `a / b` in `/divide` | **❌ Test fails** |

"What Changed?" should identify commit 4 as the most likely cause with **high confidence**.

---

## Project Structure

```
what-changed/
├── what_changed.py          # CLI entry point + Pipeline
├── models.py                # Shared dataclasses (Signal, RepoContext, AnalysisResult)
├── requirements.txt
├── setup_demo.py            # Builds demo/ fixture repo
├── demo.sh                  # One-command end-to-end demo
├── collectors/
│   ├── git_collector.py     # Sub-Task 2
│   ├── dependency_checker.py # Sub-Task 3
│   ├── config_checker.py    # Sub-Task 4
│   ├── test_runner.py       # Sub-Task 5
│   └── log_parser.py        # Sub-Task 6
├── reasoning/
│   └── llm_reasoner.py      # Sub-Task 7 — Bob-driven analysis
└── reporting/
    ├── renderer.py           # Sub-Task 8
    └── templates/
        └── report.html.j2   # Self-contained HTML report template
```

---

## Built With

- [IBM Bob](https://www.ibm.com/bob) — AI reasoning engine
- [gitpython](https://gitpython.readthedocs.io/) — Git history extraction
- [Jinja2](https://jinja.palletsprojects.com/) — HTML report rendering
