"""Human-review controls.

Automated checks are cheap but blunt. The framework routes three kinds of result to a person:
  * any check that cannot decide automatically (type: human),
  * any scenario marked `review: true`,
  * every failure on a critical-severity scenario (to confirm it before it blocks a release).

Workflow:
    raieval review-export runs/<run>     -> runs/<run>/review_queue.csv
    (reviewer fills in human_verdict = pass|fail, reviewer, notes)
    raieval review-import runs/<run> review_queue.csv  -> runs/<run>/review_decisions.json

Human verdicts override automated ones in every report, and the agreement between the
automated verdict and the human verdict is reported so the checks themselves are audited.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .runner import load_run

FIELDS = ["scenario_id", "repeat", "category", "severity", "input", "output", "auto_verdict", "auto_score",
          "auto_failures", "check_details", "human_verdict", "reviewer", "notes"]


def export_queue(run_dir: str | Path, out: str | Path | None = None) -> Path:
    run_dir = Path(run_dir)
    _, rows = load_run(run_dir)
    out = Path(out) if out else run_dir / "review_queue.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            if not r["needs_review"]:
                continue
            w.writerow({
                "scenario_id": r["scenario_id"], "repeat": r["repeat"], "category": r["category"],
                "severity": r["severity"], "input": r["input"], "output": r["output"],
                "auto_verdict": {True: "pass", False: "fail", None: "undecided"}[r["passed"]],
                "auto_score": "" if r.get("score") is None else r["score"],
                "auto_failures": ";".join(r["failures"]),
                "check_details": "; ".join(f"{c['check']}: {c['detail']}" for c in r["checks"] if c["detail"]),
                "human_verdict": r.get("human_verdict") or "", "reviewer": r.get("reviewer", ""),
                "notes": r.get("human_notes", ""),
            })
    return out


def import_decisions(run_dir: str | Path, csv_path: str | Path) -> dict:
    run_dir = Path(run_dir)
    path = run_dir / "review_decisions.json"
    decisions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    added = 0
    with Path(csv_path).open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            v = row.get("human_verdict", "").strip().lower()
            if v not in ("pass", "fail"):
                continue
            if not row.get("reviewer", "").strip():
                raise ValueError(f"{row['scenario_id']}: a reviewer name is required for every decision")
            decisions[f"{row['scenario_id']}#{row['repeat']}"] = {
                "verdict": v, "reviewer": row["reviewer"].strip(), "notes": row.get("notes", ""),
                "auto_verdict": row.get("auto_verdict"),
                "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            added += 1
    path.write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    return {"imported": added, "total_decisions": len(decisions)}


def agreement(run_dir: str | Path) -> dict:
    """How often did the automated verdict match the human one, where both exist?"""
    _, rows = load_run(run_dir)
    both = [r for r in rows if r.get("human_verdict") and r["passed"] is not None]
    agree = sum((r["human_verdict"] == "pass") == r["passed"] for r in both)
    return {"compared": len(both), "agreed": agree,
            "agreement_rate": round(agree / len(both), 3) if both else None,
            "undecided_resolved_by_humans": sum(1 for r in rows if r.get("human_verdict") and r["passed"] is None)}
