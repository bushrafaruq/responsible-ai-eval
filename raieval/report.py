"""Metrics, run reports and version-to-version comparison."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from .runner import load_run
from .suite import SEVERITIES


def final_verdict(row: dict) -> bool | None:
    """Human verdict overrides the automated one when present."""
    hv = row.get("human_verdict")
    if hv in ("pass", "fail"):
        return hv == "pass"
    return row["passed"]


def scenario_verdicts(rows: list[dict]) -> dict[str, bool | None]:
    """A scenario passes only if every repeat passes (strict: catches non-determinism)."""
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r["scenario_id"]].append(final_verdict(r))
    out = {}
    for sid, vs in by.items():
        out[sid] = False if False in vs else (None if None in vs else True)
    return out


def metrics(rows: list[dict]) -> dict:
    verdicts = scenario_verdicts(rows)
    first = {r["scenario_id"]: r for r in rows if r["repeat"] == 0}
    decided = {k: v for k, v in verdicts.items() if v is not None}
    n = len(verdicts)

    def rate(ids):
        d = [verdicts[i] for i in ids if verdicts[i] is not None]
        return round(sum(d) / len(d), 3) if d else None

    by_cat = defaultdict(list)
    by_sev = defaultdict(list)
    by_tag = defaultdict(list)
    for sid, r in first.items():
        by_cat[r["category"]].append(sid)
        by_sev[r["severity"]].append(sid)
        for t in r.get("tags") or []:
            if ":" in t:                        # structured tags such as "type:homonyms"
                by_tag[t].append(sid)

    fail_counts = Counter(f for r in rows for f in r["failures"] if final_verdict(r) is False)
    groups = defaultdict(set)
    for sid, r in first.items():
        if r["group"]:
            groups[r["group"]].add(verdicts[sid])
    consistent = [len(v) == 1 for v in groups.values()]
    repeat_flips = sum(1 for sid in verdicts if len({final_verdict(r) for r in rows if r["scenario_id"] == sid}) > 1)

    return {
        "scenarios": n,
        "pass_rate": round(sum(decided.values()) / len(decided), 3) if decided else None,
        "passed": sum(1 for v in verdicts.values() if v is True),
        "failed": sum(1 for v in verdicts.values() if v is False),
        "pending_review": sum(1 for v in verdicts.values() if v is None),
        "critical_failures": sum(1 for sid in by_sev["critical"] if verdicts[sid] is False),
        "high_failures": sum(1 for sid in by_sev["high"] if verdicts[sid] is False),
        "by_category": {c: rate(ids) for c, ids in sorted(by_cat.items())},
        "by_severity": {s: rate(by_sev[s]) for s in SEVERITIES if by_sev[s]},
        "by_tag": {t: {"pass_rate": rate(ids), "n": len(ids)} for t, ids in sorted(by_tag.items())},
        "failure_categories": dict(fail_counts.most_common()),
        "paraphrase_consistency": round(sum(consistent) / len(consistent), 3) if consistent else None,
        "repeat_flips": repeat_flips,
        "mean_score": round(sum(sc) / len(sc), 3) if (sc := [r["score"] for r in rows if r.get("score") is not None]) else None,
        "mean_latency_ms": round(sum(r["latency_ms"] for r in rows) / len(rows), 1) if rows else 0,
        "human_reviewed": sum(1 for r in rows if r.get("human_verdict")),
    }


def run_report(run_dir: str | Path) -> str:
    meta, rows = load_run(run_dir)
    m = metrics(rows)
    lines = [
        f"# Run report: {meta['suite']} / {meta['prompt_version']} / {meta['provider']}", "",
        (f"Run `{meta['run_id']}` · prompt sha `{meta['prompt_sha']}` · suite sha `{meta['suite_sha']}` · "
         f"{meta['repeats']} repeat(s) · {meta['started_at']}"), "",
        "| Metric | Value |", "|---|---|",
        f"| Scenarios | {m['scenarios']} |",
        f"| Pass rate | {pct(m['pass_rate'])} ({m['passed']} passed, {m['failed']} failed, {m['pending_review']} pending review) |",
        f"| Mean check score | {pct(m['mean_score'])} (share of checks passed, averaged over scenarios) |",
        f"| Critical failures | {m['critical_failures']} |",
        f"| High-severity failures | {m['high_failures']} |",
        f"| Paraphrase consistency | {pct(m['paraphrase_consistency'])} |",
        f"| Human-reviewed results | {m['human_reviewed']} |", "",
        "## Pass rate by category", "", "| Category | Pass rate |", "|---|---|",
    ]
    lines += [f"| {c} | {pct(v)} |" for c, v in m["by_category"].items()]
    if m["by_tag"]:
        lines += ["", "## Pass rate by tag", "", "| Tag | Scenarios | Pass rate |", "|---|---|---|"]
        lines += [f"| {t} | {v['n']} | {pct(v['pass_rate'])} |" for t, v in m["by_tag"].items()]
    lines += ["", "## Failure categories", "", "| Failure | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in m["failure_categories"].items()] or ["| none | 0 |"]
    lines += ["", "## Failed or pending scenarios", "", "| ID | Category | Severity | Failures | Output (truncated) |", "|---|---|---|---|---|"]
    for r in rows:
        v = final_verdict(r)
        if v is not True:
            out = r["output"].replace("|", "/").replace("\n", " ")[:90]
            lines.append(f"| {r['scenario_id']} | {r['category']} | {r['severity']} | "
                         f"{', '.join(r['failures']) or 'pending review'} | {out} |")
    return "\n".join(lines) + "\n"


def compare(base_dir: str | Path, new_dir: str | Path) -> dict:
    bm, brows = load_run(base_dir)
    nm, nrows = load_run(new_dir)
    bv, nv = scenario_verdicts(brows), scenario_verdicts(nrows)
    sev = {r["scenario_id"]: r["severity"] for r in nrows}
    cat = {r["scenario_id"]: r["category"] for r in nrows}
    shared = sorted(set(bv) & set(nv))
    regressions = [s for s in shared if bv[s] is True and nv[s] is False]
    fixes = [s for s in shared if bv[s] is False and nv[s] is True]
    return {
        "base": f"{bm['prompt_version']} / {bm['provider']}", "new": f"{nm['prompt_version']} / {nm['provider']}",
        "base_metrics": metrics(brows), "new_metrics": metrics(nrows),
        "regressions": [{"id": s, "category": cat[s], "severity": sev[s]} for s in regressions],
        "fixes": [{"id": s, "category": cat[s], "severity": sev[s]} for s in fixes],
    }


def compare_report(base_dir, new_dir) -> str:
    c = compare(base_dir, new_dir)
    b, n = c["base_metrics"], c["new_metrics"]
    cats = sorted(set(b["by_category"]) | set(n["by_category"]))
    lines = [f"# Comparison: {c['base']} → {c['new']}", "",
             "| Metric | Base | New |", "|---|---|---|",
             f"| Pass rate | {pct(b['pass_rate'])} | {pct(n['pass_rate'])} |",
             f"| Mean check score | {pct(b['mean_score'])} | {pct(n['mean_score'])} |",
             f"| Critical failures | {b['critical_failures']} | {n['critical_failures']} |",
             f"| High-severity failures | {b['high_failures']} | {n['high_failures']} |"]
    lines += [f"| {k} | {pct(b['by_category'].get(k))} | {pct(n['by_category'].get(k))} |" for k in cats]
    lines += ["", f"**Fixed ({len(c['fixes'])}):** " + (", ".join(f"{x['id']}" for x in c["fixes"]) or "none"),
              "", f"**Regressions ({len(c['regressions'])}):** "
              + (", ".join(f"{x['id']} ({x['category']}, {x['severity']})" for x in c["regressions"]) or "none")]
    return "\n".join(lines) + "\n"


def pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"
