# demo — What Changed? fixture

This is a small Flask application used to demonstrate the "What Changed?" tool.

The history contains an intentional breaking change introduced in commit 4.
Run the analysis tool to identify it:

```bash
cd ..
python3 what_changed.py --repo ./demo --output demo_report.html
```
