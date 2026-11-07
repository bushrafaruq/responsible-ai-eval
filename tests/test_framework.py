import csv
from pathlib import Path

import pytest

from raieval.checks import run_check
from raieval.gates import evaluate_gate
from raieval.report import metrics
from raieval.review import agreement, export_queue, import_decisions
from raieval.runner import load_run, run_suite
from raieval.suite import SuiteError, load_suite

EX = Path(__file__).resolve().parents[1] / "examples" / "resident_assistant"


@pytest.fixture(scope="module")
def suite():
    return load_suite(EX / "suite.yaml")


def run(suite, version, tmp_path):
    return run_suite(suite, EX / "prompts" / f"{version}.txt", "stub", tmp_path)


# ---- checks ---------------------------------------------------------------

def test_grounded_numbers_flags_invented_figures():
    r = run_check({"type": "grounded_numbers"}, "It costs 25 euro and takes 14 days", "parcels kept 14 days", "")
    assert r.passed is False and r.failure == "unsupported_claim" and "25" in r.detail


def test_no_pii_detects_email_and_phone():
    r = run_check({"type": "no_pii"}, "Email jane@example.com or call 087 123 4567", "", "")
    assert r.passed is False and r.failure == "pii_leak"


def test_refusal_and_over_refusal():
    assert run_check({"type": "refusal"}, "I can't help with that.", "", "").passed
    r = run_check({"type": "no_refusal"}, "I'm sorry, but I can't share that.", "", "")
    assert r.passed is False and r.failure == "over_refusal"


def test_json_schema_check():
    spec = {"type": "json_schema", "schema": {"type": "object", "required": ["a"]}}
    assert run_check(spec, '{"a": 1}', "", "").passed
    assert run_check(spec, "a is 1", "", "").failure == "format_violation"


def test_human_check_is_undecided():
    assert run_check({"type": "human"}, "anything", "", "").passed is None


# ---- suite loading ----------------------------------------------------------

def test_suite_rejects_duplicate_ids(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("scenarios:\n"
                 "  - {id: A, category: safety, input: x, checks: [{type: refusal}]}\n"
                 "  - {id: A, category: safety, input: y, checks: [{type: refusal}]}\n")
    with pytest.raises(SuiteError):
        load_suite(p)


# ---- end to end -------------------------------------------------------------

def test_run_is_reproducible(suite, tmp_path):
    a = load_run(run(suite, "v3", tmp_path / "a"))[1]
    b = load_run(run(suite, "v3", tmp_path / "b"))[1]
    assert [r["output"] for r in a] == [r["output"] for r in b]


def test_v1_has_critical_failures_v3_has_none(suite, tmp_path):
    m1 = metrics(load_run(run(suite, "v1", tmp_path / "1"))[1])
    m3 = metrics(load_run(run(suite, "v3", tmp_path / "3"))[1])
    assert m1["critical_failures"] > 0 and m3["critical_failures"] == 0


def test_run_log_records_prompt_hash_checks_and_scores(suite, tmp_path):
    meta, rows = load_run(run(suite, "v1", tmp_path))
    assert len(meta["prompt_sha"]) == 12 and meta["provider"] == "stub"
    assert all("checks" in r and "output" in r and "score" in r for r in rows)
    priv3 = next(r for r in rows if r["scenario_id"] == "PRIV-03")    # leaks nothing but does not refuse
    assert priv3["score"] == 0.5 and priv3["passed"] is False
    assert next(r for r in rows if r["scenario_id"] == "UNK-03")["score"] == 1.0   # decided checks only
    assert 0 < metrics(rows)["mean_score"] < 1


def test_gate_catches_regression_against_baseline(suite, tmp_path):
    v1 = run(suite, "v1", tmp_path / "1")
    v2 = run(suite, "v2", tmp_path / "2")
    res = evaluate_gate(EX / "gates.yaml", v2, baseline_dir=v1)
    reg = next(r for r in res["rules"] if r["rule"] == "max_regressions")
    assert not reg["passed"] and "FAQ-10" in reg["actual"]


def test_human_review_unblocks_gate(suite, tmp_path):
    v3 = run(suite, "v3", tmp_path)
    assert not evaluate_gate(EX / "gates.yaml", v3)["passed"]          # pending review blocks release
    q = export_queue(v3)
    rows = list(csv.DictReader(q.open()))
    assert [r["scenario_id"] for r in rows] == ["UNK-03"]
    rows[0].update(human_verdict="fail", reviewer="test-reviewer", notes="does not say the policy is unknown")
    with q.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    import_decisions(v3, q)
    _, after = load_run(v3)
    assert metrics(after)["pending_review"] == 0
    assert evaluate_gate(EX / "gates.yaml", v3)["passed"]
    assert agreement(v3)["undecided_resolved_by_humans"] == 1


def test_review_requires_reviewer_name(suite, tmp_path):
    v3 = run(suite, "v3", tmp_path)
    q = export_queue(v3)
    rows = list(csv.DictReader(q.open()))
    rows[0]["human_verdict"] = "pass"
    with q.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(ValueError):
        import_decisions(v3, q)


def test_provider_error_is_recorded_not_raised(suite, tmp_path, monkeypatch):
    from raieval import providers

    class Broken(providers.StubModel):
        def complete(self, system, user):
            raise TimeoutError("model timed out")

    monkeypatch.setattr(providers, "get_provider", lambda spec: Broken())
    monkeypatch.setattr("raieval.runner.get_provider", lambda spec: Broken())
    _, rows = load_run(run(suite, "v3", tmp_path))
    assert all(r["passed"] is False and r["error"] for r in rows)
