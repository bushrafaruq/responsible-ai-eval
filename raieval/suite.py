"""Scenario suites: the repeatable test cases a prompt/model version is evaluated against.

A suite is a YAML file:

    name: resident-assistant
    description: ...
    knowledge_file: knowledge.md          # optional context injected into every prompt
    scenarios:
      - id: FAQ-01
        category: capability              # capability | safety | privacy | injection | format | robustness
        severity: medium                  # low | medium | high | critical
        input: "What time does the front desk close?"
        context: "..."                    # optional extra context for this scenario only
        group: desk-hours                 # optional: paraphrases share a group (consistency check)
        review: false                     # optional: always send to human review
        checks:
          - {type: contains_any, values: ["20:00", "8pm", "8 pm"]}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

CATEGORIES = {"capability", "safety", "privacy", "injection", "format", "robustness"}
SEVERITIES = ["low", "medium", "high", "critical"]


@dataclass
class Scenario:
    id: str
    category: str
    severity: str
    input: str
    checks: list[dict]
    context: str = ""
    group: str | None = None
    review: bool = False
    tags: list[str] = field(default_factory=list)


@dataclass
class Suite:
    name: str
    description: str
    knowledge: str
    scenarios: list[Scenario]
    path: Path | None = None


class SuiteError(ValueError):
    pass


def load_suite(path: str | Path) -> Suite:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    knowledge = ""
    if raw.get("knowledge_file"):
        knowledge = (path.parent / raw["knowledge_file"]).read_text(encoding="utf-8")
    scenarios, seen = [], set()
    for s in raw.get("scenarios", []):
        sid = s.get("id")
        if not sid or sid in seen:
            raise SuiteError(f"missing or duplicate scenario id: {sid!r}")
        seen.add(sid)
        if s.get("category") not in CATEGORIES:
            raise SuiteError(f"{sid}: category must be one of {sorted(CATEGORIES)}")
        if s.get("severity", "medium") not in SEVERITIES:
            raise SuiteError(f"{sid}: severity must be one of {SEVERITIES}")
        if not s.get("checks"):
            raise SuiteError(f"{sid}: at least one check is required")
        scenarios.append(Scenario(
            id=sid, category=s["category"], severity=s.get("severity", "medium"),
            input=s["input"], checks=s["checks"], context=s.get("context", ""),
            group=s.get("group"), review=bool(s.get("review", False)), tags=s.get("tags", []),
        ))
    return Suite(raw.get("name", path.stem), raw.get("description", ""), knowledge, scenarios, path)
