"""
setup_demo.py — Creates the demo/ fixture repository programmatically using gitpython.

Run once before using what_changed.py on the demo:
    python3 setup_demo.py

This builds a small Flask app with a 4-commit history:
  Commit 1 (baseline)          — working Flask app + passing test
  Commit 2 (dependency bump)   — bump flask version in requirements.txt
  Commit 3 (config change)     — change DATABASE_URL in config.py to wrong value
  Commit 4 (breaking change)   — introduce a bug in app.py that breaks the /divide route
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import git

DEMO_DIR = Path(__file__).parent / "demo"

# ============================================================
# File contents at each commit
# ============================================================

APP_V1 = '''\
"""demo Flask app — v1 (baseline, working)."""
from flask import Flask, jsonify
import config

app = Flask(__name__)


@app.route("/")
def index():
    return jsonify({"status": "ok", "db": config.DATABASE_URL})


@app.route("/divide/<int:a>/<int:b>")
def divide(a, b):
    """Divide a by b and return the result."""
    if b == 0:
        return jsonify({"error": "division by zero"}), 400
    result = a / b
    return jsonify({"result": result})


if __name__ == "__main__":
    app.run(debug=config.DEBUG)
'''

APP_V4_BROKEN = '''\
"""demo Flask app — v4 (BROKEN: divide always returns 0)."""
from flask import Flask, jsonify
import config

app = Flask(__name__)


@app.route("/")
def index():
    return jsonify({"status": "ok", "db": config.DATABASE_URL})


@app.route("/divide/<int:a>/<int:b>")
def divide(a, b):
    """Divide a by b and return the result."""
    if b == 0:
        return jsonify({"error": "division by zero"}), 400
    # BUG: integer floor-division introduced by mistake; always truncates result
    result = a // b
    return jsonify({"result": result})


if __name__ == "__main__":
    app.run(debug=config.DEBUG)
'''

CONFIG_V1 = '''\
"""App configuration — v1 (baseline)."""
DATABASE_URL = "postgresql://localhost:5432/myapp"
DEBUG = False
SECRET_KEY = "dev-only-secret"
'''

CONFIG_V3_CHANGED = '''\
"""App configuration — v3 (config change: wrong DB host)."""
DATABASE_URL = "postgresql://prod-db-server:5432/myapp"
DEBUG = True
SECRET_KEY = "dev-only-secret"
'''

REQUIREMENTS_V1 = """\
flask==2.3.2
pytest==7.4.0
"""

REQUIREMENTS_V2_BUMPED = """\
flask==3.0.0
pytest==7.4.0
"""

TEST_V1 = '''\
"""Tests for the demo Flask app."""
import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"


def test_divide(client):
    resp = client.get("/divide/10/4")
    assert resp.status_code == 200
    data = resp.get_json()
    # 10 / 4 = 2.5 — float division expected
    assert data["result"] == 2.5, f"Expected 2.5 but got {data['result']}"


def test_divide_by_zero(client):
    resp = client.get("/divide/5/0")
    assert resp.status_code == 400
'''

README_DEMO = """\
# demo — What Changed? fixture

This is a small Flask application used to demonstrate the "What Changed?" tool.

The history contains an intentional breaking change introduced in commit 4.
Run the analysis tool to identify it:

```bash
cd ..
python3 what_changed.py --repo ./demo --output demo_report.html
```
"""


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def build_demo() -> None:
    # Clean slate
    if DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR)
    DEMO_DIR.mkdir(parents=True)

    repo = git.Repo.init(str(DEMO_DIR))
    repo.config_writer().set_value("user", "name", "Demo Author").release()
    repo.config_writer().set_value("user", "email", "demo@what-changed.local").release()

    # ----------------------------------------------------------------
    # Commit 1: baseline — working Flask app + passing test
    # ----------------------------------------------------------------
    _write(DEMO_DIR / "app.py", APP_V1)
    _write(DEMO_DIR / "config.py", CONFIG_V1)
    _write(DEMO_DIR / "requirements.txt", REQUIREMENTS_V1)
    _write(DEMO_DIR / "test_app.py", TEST_V1)
    _write(DEMO_DIR / "README.md", README_DEMO)

    repo.index.add(["app.py", "config.py", "requirements.txt", "test_app.py", "README.md"])
    repo.index.commit("Initial working Flask app with passing tests")
    print("  ✓ Commit 1: baseline")

    # ----------------------------------------------------------------
    # Commit 2: dependency bump — flask 2.3.2 → 3.0.0
    # ----------------------------------------------------------------
    _write(DEMO_DIR / "requirements.txt", REQUIREMENTS_V2_BUMPED)
    repo.index.add(["requirements.txt"])
    repo.index.commit("chore: bump flask from 2.3.2 to 3.0.0")
    print("  ✓ Commit 2: dependency bump (flask 2.3.2 → 3.0.0)")

    # ----------------------------------------------------------------
    # Commit 3: config change — wrong DB URL, DEBUG=True
    # ----------------------------------------------------------------
    _write(DEMO_DIR / "config.py", CONFIG_V3_CHANGED)
    repo.index.add(["config.py"])
    repo.index.commit("config: point to production DB server, enable DEBUG")
    print("  ✓ Commit 3: config change (DATABASE_URL + DEBUG)")

    # ----------------------------------------------------------------
    # Commit 4: breaking change — // instead of / in divide()
    # ----------------------------------------------------------------
    _write(DEMO_DIR / "app.py", APP_V4_BROKEN)
    repo.index.add(["app.py"])
    repo.index.commit("fix: improve divide performance (BREAKING: uses integer division)")
    print("  ✓ Commit 4: breaking change (a // b instead of a / b)")

    print(f"\n✓ Demo repository created at: {DEMO_DIR}")
    print(f"  Commits: {len(list(repo.iter_commits('HEAD')))}")
    print(f"\nRun the analysis:")
    print(f"  python3 what_changed.py --repo {DEMO_DIR} --output demo_report.html")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    print("Building demo fixture repository …\n")
    build_demo()
