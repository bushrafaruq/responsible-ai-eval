# Methodology

## What is being evaluated

A **target** is one prompt version running on one model. The framework answers one question
about a target: *is it safe and good enough to release, compared with what is live today?*

## Scenarios

A suite is a fixed set of scenarios, each with:

| Field | Purpose |
|---|---|
| `category` | capability, robustness, safety, privacy, injection, format |
| `severity` | low, medium, high, critical. Critical means a single failure blocks release |
| `input` / `context` | the user message and any document or record the assistant can see |
| `checks` | one or more automated checks; all must pass |
| `group` | paraphrases of the same question, used for the consistency metric |
| `review` | always send this scenario to a person |

Scenarios are written to cover the risks, not to make the score look good. Each risk has at least
one scenario where the right behaviour is to **help** (to catch over-refusal) as well as one where it
is to **refuse**.

## Checks

Checks are deliberately simple and transparent so a reviewer can see why something failed.

| Check | Tests for | Failure category |
|---|---|---|
| `contains_any`, `contains_all`, `regex` | the expected content is present | wrong_answer |
| `grounded_numbers` | every number in the answer appears in the knowledge base or context | unsupported_claim |
| `not_contains` | specific content that must not appear | configurable |
| `json_schema` | output parses and matches a JSON schema | format_violation |
| `max_words` | length limit | format_violation |
| `refusal` / `no_refusal` | refuses when it should, and only then | unsafe_compliance / over_refusal |
| `no_pii` | no emails, phone numbers, IBANs or card numbers | pii_leak |
| `injection_canary` | a secret token planted in an injected instruction does not appear | injection_followed |
| `human` | needs judgement; always routed to a person | needs_review |

## Running and recording

Every run writes `run.json` (suite hash, prompt file and SHA-256, provider, timestamps) and
`results.jsonl` (input, output, every check with its detail, failure categories, latency). A run can
be traced back to the exact prompt text and suite that produced it.

Each scenario result carries a verdict (pass, fail or pending review) and a **score**: the share of its
automated checks that passed. The verdict drives gates; the score shows partial progress (for example
an answer that leaks nothing but also fails to refuse scores 0.5).

`--repeats N` runs every scenario N times. A scenario passes only if every repeat passes, and
`repeat_flips` counts scenarios that gave different verdicts across repeats (non-determinism).

## Comparing versions

`compare` lists **fixes** (fail → pass) and **regressions** (pass → fail) scenario by scenario. A
better headline score can hide a regression; the comparison makes it visible.

## Human review

Three things go to a person: undecidable checks, scenarios marked `review: true`, and every
critical failure (to confirm it before it blocks a release). Reviewers record `pass`/`fail` with
their name; human verdicts override automated ones in every report. The agreement rate between
automated and human verdicts is reported, so the checks are audited too.

## Release gates

Gates are written down before results are seen (`gates.yaml`) and versioned with the prompt.
Typical rules: zero critical failures, 100% on safety, privacy and injection, a minimum capability
score, no unreviewed items, and no regressions against the live version. The `gate` command exits
with code 1 when a rule fails, so it can block a CI pipeline.
