"""Run a suite against a target and write an auditable run record.

Each run creates runs/<run_id>/ containing:
    run.json        metadata: suite, prompt version + SHA-256, provider, timestamps, git-free and reproducible
    results.jsonl   one line per scenario x repeat: input, output, every check, failure categories, latency
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .checks import CheckResult, run_check
from .providers import build_messages, get_provider
from .suite import Suite


@dataclass
class ScenarioResult:
    scenario_id: str
    category: str
    severity: str
    group: str | None
    repeat: int
    input: str
    output: str
    checks: list[dict]
    passed: bool | None          # None = needs human review
    score: float | None          # share of decided checks that passed (0-1); None if no check could decide
    failures: list[str]
    needs_review: bool
    latency_ms: int
    error: str | None = None
    human_verdict: str | None = None
    tags: list[str] = field(default_factory=list)


def _rel(path: Path) -> str:
    """Store paths relative to the repository so run records are portable."""
    try:
        return os.path.relpath(Path(path).resolve(), Path(__file__).resolve().parents[1])
    except ValueError:
        return str(path)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def run_suite(suite: Suite, prompt_path: str | Path, provider_spec: str, out_dir: str | Path = "runs",
              repeats: int = 1, label: str | None = None, workers: int = 1) -> Path:
    """workers > 1 sends model calls in parallel (results keep the suite order). Keep it modest:
    API rate limits apply, and rate-limited calls are retried by the provider client."""
    prompt_path = Path(prompt_path)
    system_prompt = prompt_path.read_text(encoding="utf-8")
    provider = get_provider(provider_spec)
    started = datetime.now(timezone.utc)
    version = label or prompt_path.stem
    run_id = f"{started:%Y%m%dT%H%M%S}_{suite.name}_{version}_{provider.name.replace(':', '-')}"
    run_dir = Path(out_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    def call(job):
        sc, _ = job
        system, user = build_messages(system_prompt, suite.knowledge, sc.context, sc.input)
        try:
            comp = provider.complete(system, user)
            return comp.text, comp.latency_ms, None
        except Exception as exc:  # noqa: BLE001 - a provider failure is itself a result
            return "", 0, f"{type(exc).__name__}: {exc}"

    jobs = [(sc, r) for sc in suite.scenarios for r in range(repeats)]
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            completions = list(pool.map(call, jobs))
    else:
        completions = [call(j) for j in jobs]

    results: list[ScenarioResult] = []
    for (sc, r), (output, latency, error) in zip(jobs, completions, strict=True):
        checks: list[CheckResult] = (
            [run_check(c, output, suite.knowledge, sc.context) for c in sc.checks]
            if error is None else [CheckResult("provider", False, "provider_error", error)]
        )
        decided = [c for c in checks if c.passed is not None]
        undecided = [c for c in checks if c.passed is None]
        failed = [c for c in decided if not c.passed]
        passed = False if failed else (None if undecided else True)
        score = round(sum(1 for c in decided if c.passed) / len(decided), 3) if decided else None
        # Human review: undecided checks, scenarios marked review, and every critical failure.
        needs_review = bool(undecided) or sc.review or (sc.severity == "critical" and passed is False)
        results.append(ScenarioResult(
            scenario_id=sc.id, category=sc.category, severity=sc.severity, group=sc.group, repeat=r,
            input=sc.input, output=output, checks=[asdict(c) for c in checks], passed=passed, score=score,
            failures=sorted({c.failure for c in failed if c.failure}), needs_review=needs_review,
            latency_ms=latency, error=error, tags=sc.tags,
        ))

    meta = {
        "run_id": run_id, "suite": suite.name, "suite_file": _rel(suite.path) if suite.path else None,
        "suite_sha": sha(json.dumps([asdict(s) for s in suite.scenarios], sort_keys=True) + suite.knowledge),
        "prompt_version": version, "prompt_file": _rel(prompt_path), "prompt_sha": sha(system_prompt),
        "provider": provider.name, "repeats": repeats, "n_scenarios": len(suite.scenarios),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    with (run_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for res in results:
            f.write(json.dumps(asdict(res), ensure_ascii=False) + "\n")
    return run_dir


def load_run(run_dir: str | Path) -> tuple[dict, list[dict]]:
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    rows = [json.loads(ln) for ln in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines() if ln]
    review = run_dir / "review_decisions.json"
    if review.exists():
        decisions = json.loads(review.read_text(encoding="utf-8"))
        for row in rows:
            key = f'{row["scenario_id"]}#{row["repeat"]}'
            if key in decisions:
                row["human_verdict"] = decisions[key]["verdict"]
                row["human_notes"] = decisions[key].get("notes", "")
                row["reviewer"] = decisions[key].get("reviewer", "")
    return meta, rows
