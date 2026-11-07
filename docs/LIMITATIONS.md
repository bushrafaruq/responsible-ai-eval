# Limitations

**The demo results come from a stub model.** `StubModel` is a deterministic, rule-based stand-in
so the framework, tests and CI run without an API key. It reacts to rules in the prompt so the demo
can show how the framework detects fixes and regressions between prompt versions. Its results say
nothing about how any real model behaves. Run `scripts/demo.py --provider anthropic:<model>` or
`openai:<model>` for real numbers.

**Automated checks are proxies.**
* `contains_*` checks can pass an answer that contains the right words in a wrong sentence, and fail
  a correct answer phrased differently. Paraphrase groups and human review reduce, but do not remove, this.
* `grounded_numbers` only catches invented *numbers*. An invented policy without a number passes.
* `refusal` relies on refusal phrases in English at the start of the answer (curly apostrophes are normalised); a model that refuses in an unusual way is marked
  as complying. Every critical failure is therefore confirmed by a person.
* `no_pii` is pattern-based and does not detect names; scenarios that could leak names use
  `not_contains` with the specific names.

**A suite is only as good as its scenarios.** 31 scenarios cannot cover every way an assistant can
fail. Passing the suite is evidence, not proof. New failures found in production should be added as
scenarios so they are tested on every future version.

**Pass rates on small suites move in large steps.** One scenario is about 3 percentage points here.
Gates on categories with few scenarios (for example 3 injection scenarios) should be read as "no
known failure", not as a measured rate.

**LLM-as-judge is not included.** It would scale review of open-ended answers but adds its own
errors and bias; this framework prefers transparent checks plus human review, and leaves a judge as
an extension that should itself be evaluated against human verdicts.

**English only, single-turn only.** Multi-turn conversations and other languages are not covered.

**Public benchmarks measure general behaviour, not your application.** XSTest shows how a model and
prompt balance over-refusal against unsafe compliance in general; it says nothing about a specific
product's knowledge or policies. Use both: a public benchmark for general behaviour and your own
suite for your application.
