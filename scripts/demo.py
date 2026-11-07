"""Reproduce the demo in the README: three prompt versions of the resident assistant,
evaluated with the offline stub model, compared and gated.

    python scripts/demo.py                      # stub model, no API key
    python scripts/demo.py --provider anthropic:claude-haiku-5-5
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raieval.gates import evaluate_gate  # noqa: E402
from raieval.report import compare_report, metrics, pct, run_report  # noqa: E402
from raieval.runner import load_run, run_suite  # noqa: E402
from raieval.suite import load_suite  # noqa: E402

EX = ROOT / "examples" / "resident_assistant"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="stub")
    ap.add_argument("--out", default=str(ROOT / "runs" / "demo"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    suite = load_suite(EX / "suite.yaml")

    runs = {}
    for v in ["v1", "v2", "v3"]:
        d = run_suite(suite, EX / "prompts" / f"{v}.txt", a.provider, out)
        (d / "report.md").write_text(run_report(d), encoding="utf-8")
        runs[v] = d

    lines = [f"# Demo results ({a.provider})", "",
             "| | v1 | v2 | v3 |", "|---|---|---|---|"]
    ms = {v: metrics(load_run(d)[1]) for v, d in runs.items()}
    lines.append("| Pass rate | " + " | ".join(pct(ms[v]["pass_rate"]) for v in runs) + " |")
    lines.append("| Mean check score | " + " | ".join(pct(ms[v]["mean_score"]) for v in runs) + " |")
    lines.append("| Critical failures | " + " | ".join(str(ms[v]["critical_failures"]) for v in runs) + " |")
    cats = sorted(ms["v1"]["by_category"])
    for c in cats:
        lines.append(f"| {c} | " + " | ".join(pct(ms[v]["by_category"].get(c)) for v in runs) + " |")
    lines.append("| Pending human review | " + " | ".join(str(ms[v]["pending_review"]) for v in runs) + " |")
    gates = {
        "v1": evaluate_gate(EX / "gates.yaml", runs["v1"]),
        "v2": evaluate_gate(EX / "gates.yaml", runs["v2"], runs["v1"]),
        "v3": evaluate_gate(EX / "gates.yaml", runs["v3"], runs["v2"]),
    }
    lines.append("| Release gate | " + " | ".join(
        "PASS" if gates[v]["passed"] else "FAIL: " + ", ".join(r["rule"] for r in gates[v]["rules"] if not r["passed"])
        for v in runs) + " |")
    lines += ["", compare_report(runs["v1"], runs["v2"]), compare_report(runs["v2"], runs["v3"])]
    (out / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        x = np.arange(len(cats))
        fig, ax = plt.subplots(figsize=(8, 4))
        for i, (v, col) in enumerate(zip(runs, ["#b8c4c8", "#e9a23b", "#117a8b"], strict=True)):
            vals = [(ms[v]["by_category"].get(c) or 0) * 100 for c in cats]
            ax.bar(x + (i - 1) * 0.26, vals, 0.26, label=f"prompt {v}", color=col)
        ax.set_xticks(x, cats)
        ax.set_ylabel("Pass rate (%)")
        ax.set_ylim(0, 105)
        ax.set_title(f"Pass rate by category across prompt versions ({a.provider})")
        ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.1))
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(out / "version_comparison.png", dpi=150)
        if out == ROOT / "runs" / "demo":                 # the published stub demo also updates the README chart
            fig.savefig(ROOT / "docs" / "version_comparison.png", dpi=150)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
