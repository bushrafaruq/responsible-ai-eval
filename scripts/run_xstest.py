"""Run the public XSTest benchmark with both example prompts and summarise the trade-off between
over-refusal (refusing safe prompts) and unsafe compliance (answering unsafe ones).

    export ANTHROPIC_API_KEY=...
    python scripts/run_xstest.py --provider anthropic:claude-haiku-5-5

900 model calls in total (450 prompts x 2 prompt versions). Writes runs/xstest_<provider>/SUMMARY.md,
one run folder per prompt, and a chart. The stub provider runs too, but its numbers mean nothing for
this benchmark: it is only used to test the pipeline.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raieval.gates import evaluate_gate  # noqa: E402
from raieval.report import compare_report, metrics, pct, run_report  # noqa: E402
from raieval.runner import load_run, run_suite  # noqa: E402
from raieval.suite import load_suite  # noqa: E402

EX = ROOT / "examples" / "xstest"
PROMPTS = ["default", "calibrated"]


def summarise(provider: str, runs: dict[str, Path], out: Path) -> str:
    ms = {v: metrics(load_run(d)[1]) for v, d in runs.items()}

    def rate(v, cat):
        return ms[v]["by_category"].get(cat)

    lines = [f"# XSTest results: {provider}", "",
             "XSTest (Röttger et al., NAACL 2024, CC BY 4.0): 250 safe prompts that sound unsafe and 200 unsafe "
             "contrast prompts. Refusals detected by phrase matching; check a sample by hand before quoting.", "",
             "| | " + " | ".join(f"prompt `{v}`" for v in runs) + " |", "|---|" + "---|" * len(runs)]
    lines.append("| Safe prompts answered (higher is better) | " + " | ".join(pct(rate(v, "capability")) for v in runs) + " |")
    lines.append("| **Over-refusal rate** (safe prompts refused) | " + " | ".join(
        pct(None if rate(v, "capability") is None else 1 - rate(v, "capability")) for v in runs) + " |")
    lines.append("| Unsafe prompts refused (higher is better) | " + " | ".join(pct(rate(v, "safety")) for v in runs) + " |")
    lines.append("| **Unsafe compliance rate** (unsafe prompts answered) | " + " | ".join(
        pct(None if rate(v, "safety") is None else 1 - rate(v, "safety")) for v in runs) + " |")
    errors = {v: sum(1 for r in load_run(d)[1] if r.get("error")) for v, d in runs.items()}
    lines.append("| Model call errors | " + " | ".join(str(errors[v]) for v in runs) + " |")
    gates = {}
    prev = None
    for v, d in runs.items():
        gates[v] = evaluate_gate(EX / "gates.yaml", d, prev)
        prev = d
    lines.append("| Release gate | " + " | ".join(
        "PASS" if gates[v]["passed"] else "FAIL: " + ", ".join(r["rule"] for r in gates[v]["rules"] if not r["passed"])
        for v in runs) + " |")

    lines += ["", "## By XSTest prompt type (pass rate)", "",
              "| Type | Should | " + " | ".join(runs) + " |", "|---|---|" + "---|" * len(runs)]
    types = sorted({t for v in runs for t in ms[v]["by_tag"] if t.startswith("type:")})
    for t in types:
        should = "refuse" if t.startswith("type:contrast_") else "answer"
        lines.append(f"| {t[5:]} | {should} | " + " | ".join(
            pct(ms[v]["by_tag"].get(t, {}).get("pass_rate")) for v in runs) + " |")
    lines += ["", compare_report(runs[PROMPTS[0]], runs[PROMPTS[1]])]
    text = "\n".join(lines) + "\n"
    (out / "SUMMARY.md").write_text(text, encoding="utf-8")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5.5, 4.5))
        for v, col in zip(runs, ["#e9a23b", "#117a8b"], strict=False):
            x = 1 - (rate(v, "capability") or 0)
            y = 1 - (rate(v, "safety") or 0)
            ax.scatter([x * 100], [y * 100], s=120, color=col, label=f"prompt {v}")
        ax.set_xlabel("Over-refusal: safe prompts refused (%)")
        ax.set_ylabel("Unsafe compliance: unsafe prompts answered (%)")
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.set_title(f"XSTest trade-off ({provider}); best is bottom-left")
        ax.legend(frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(out / "xstest_tradeoff.png", dpi=150)
    except ImportError:
        pass
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, help="e.g. anthropic:claude-haiku-5-5 or openai:gpt-4o-mini")
    ap.add_argument("--workers", type=int, default=4, help="parallel calls; lower it if you hit rate limits")
    ap.add_argument("--limit", type=int, help="only the first N prompts (for a quick trial)")
    ap.add_argument("--out")
    a = ap.parse_args()
    slug = re.sub(r"[^a-z0-9]+", "_", a.provider.lower()).strip("_")
    out = Path(a.out) if a.out else ROOT / "runs" / f"xstest_{slug}"
    if out.exists():
        shutil.rmtree(out)
    suite = load_suite(EX / "suite.yaml")
    if a.limit:
        safe = [s for s in suite.scenarios if s.category == "capability"][: a.limit // 2]
        unsafe = [s for s in suite.scenarios if s.category == "safety"][: a.limit - a.limit // 2]
        suite.scenarios = safe + unsafe
    runs = {}
    for v in PROMPTS:
        print(f"Running prompt '{v}' on {len(suite.scenarios)} XSTest prompts with {a.provider} ...", flush=True)
        d = run_suite(suite, EX / "prompts" / f"{v}.txt", a.provider, out, workers=a.workers)
        (d / "report.md").write_text(run_report(d), encoding="utf-8")
        runs[v] = d
    print(summarise(a.provider, runs, out))
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
