#!/usr/bin/env bash
# demo.sh — End-to-end What Changed? demonstration
# Usage: bash demo.sh
set -e

PYTHON=/usr/local/bin/python3.13
if ! command -v "$PYTHON" &>/dev/null; then
  PYTHON=python3
fi

echo "=========================================="
echo "  What Changed? — Hackathon Demo"
echo "=========================================="
echo ""

# Step 1: Install dependencies
echo "[1/3] Installing dependencies …"
"$PYTHON" -m pip install -q gitpython jinja2 flask pytest

# Step 2: Build the demo fixture repo
echo "[2/3] Building demo fixture repository …"
"$PYTHON" setup_demo.py

# Step 3: Run the analysis
echo ""
echo "[3/3] Running What Changed? on the demo repo …"
"$PYTHON" what_changed.py --repo ./demo --output demo_report.html

echo ""
echo "=========================================="
echo "  Demo complete!"
echo "  Opening demo_report.html …"
echo "=========================================="

# Open the report
if command -v open &>/dev/null; then
  open demo_report.html
elif command -v xdg-open &>/dev/null; then
  xdg-open demo_report.html
else
  echo "  Report saved to: $(pwd)/demo_report.html"
  echo "  Open it manually in your browser."
fi
