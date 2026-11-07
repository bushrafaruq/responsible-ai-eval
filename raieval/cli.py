"""Command line.

    python -m raieval run      SUITE PROMPT [--provider stub] [--repeats 1] [--out runs]
    python -m raieval report   RUN_DIR
    python -m raieval compare  BASE_RUN_DIR NEW_RUN_DIR
    python -m raieval gate     GATES.yaml RUN_DIR [--baseline BASE_RUN_DIR]   (exit code 1 if it fails)
    python -m raieval review-export RUN_DIR
    python -m raieval review-import RUN_DIR CSV
"""

from __future__ import annotations

import argparse
import json
import sys

from .gates import evaluate_gate
from .report import compare_report, run_report
from .review import agreement, export_queue, import_decisions
from .runner import run_suite
from .suite import load_suite


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="raieval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("suite")
    r.add_argument("prompt")
    r.add_argument("--provider", default="stub")
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--out", default="runs")
    r.add_argument("--label")
    r.add_argument("--workers", type=int, default=1, help="parallel model calls (mind API rate limits)")
    p = sub.add_parser("report")
    p.add_argument("run_dir")
    c = sub.add_parser("compare")
    c.add_argument("base")
    c.add_argument("new")
    g = sub.add_parser("gate")
    g.add_argument("gates")
    g.add_argument("run_dir")
    g.add_argument("--baseline")
    e = sub.add_parser("review-export")
    e.add_argument("run_dir")
    i = sub.add_parser("review-import")
    i.add_argument("run_dir")
    i.add_argument("csv")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        run_dir = run_suite(load_suite(a.suite), a.prompt, a.provider, a.out, a.repeats, a.label, a.workers)
        report = run_report(run_dir)
        (run_dir / "report.md").write_text(report, encoding="utf-8")
        print(report)
        print(f"Saved to {run_dir}")
    elif a.cmd == "report":
        print(run_report(a.run_dir))
    elif a.cmd == "compare":
        print(compare_report(a.base, a.new))
    elif a.cmd == "gate":
        res = evaluate_gate(a.gates, a.run_dir, a.baseline)
        for rule in res["rules"]:
            print(f"{'PASS' if rule['passed'] else 'FAIL'}  {rule['rule']}: actual={rule['actual']} required={rule['required']}")
        print("GATE PASSED" if res["passed"] else "GATE FAILED")
        return 0 if res["passed"] else 1
    elif a.cmd == "review-export":
        print(f"Review queue written to {export_queue(a.run_dir)}")
    elif a.cmd == "review-import":
        print(json.dumps({**import_decisions(a.run_dir, a.csv), **agreement(a.run_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
