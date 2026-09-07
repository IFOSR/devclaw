# MetaCoding

MetaCoding is a project-local AI software development orchestration tool.
Run it inside an existing project directory and it coordinates exactly three
harnesses on a shared filesystem:

1. **Planner harness** (Codex) — owns the PRD, architecture, implementation
   plan, acceptance criteria, iteration decisions, and final acceptance.
2. **Coder harness** (Pi) — implements the planner's contract directly in
   the current project directory.
3. **Tester harness** (Codex) — independently verifies the implementation
   against the contract and produces evidence.

MetaCoding itself is the deterministic host: it owns the state machine, the
project lock, file ownership rules, structured protocols, safety gates, and
optional GitHub delivery. It never pushes to protected branches and never
force-pushes.

## Requirements

- Python 3.10+ (`tomllib` from the standard library on 3.11+, or `tomli`)
- `codex` CLI on PATH for the Planner and Tester harnesses
- `pi` CLI on PATH for the Coder harness
- `git` for delivery; optional `gh` for push / Pull Request / checks

## Quick start

```bash
cd /path/to/your/project

# interactive TUI
metacoding            # or: python3 -m metacoding / scripts/metacoding

# one-shot run
metacoding run "Add an audit log to all administrative account changes."
```

Exit codes: `0` accepted/delivered, `1` blocked or human review required,
`2` harness infrastructure failure, `3` usage/configuration/lock errors,
`130` interrupted.

## Commands

```text
metacoding                      interactive TUI (default)
metacoding run "REQUIREMENT"    one non-interactive run
metacoding status               active or most recent run
metacoding resume               resume an interrupted run
metacoding report [--run-id ID] final report of a run
metacoding artifacts [--run-id ID] artifact paths of a run
metacoding cancel               cancel the active run
metacoding deliver [--run-id ID] deliver an accepted run to git/GitHub
```

TUI commands: `/status`, `/report`, `/artifacts`, `/resume`, `/cancel`,
`/deliver`, `/help`, `/exit`. Type any other text to start a run.

## Configuration

Configuration lives in `<project>/.metacoding/config.toml` and never touches
system-level Codex or Pi configuration. Each harness has its **own** model:

```toml
[harness.planner]
provider = "codex"
command = "codex"
model = "planner-model"      # passed as `codex exec -m ...`

[harness.coder]
provider = "pi"
command = "pi"
model = "coding-model"       # passed as `pi -p --model ...`

[harness.tester]
provider = "codex"
command = "codex"
model = "tester-model"       # independent of the planner model
```

See [docs/metacoding/config.example.toml](docs/metacoding/config.example.toml)
for the full schema (limits, policy, GitHub). Precedence is
built-in defaults → `.metacoding/config.toml` → command-line overrides.
Overrides apply to the current invocation only and are never written back:

```text
--planner-model MODEL   --planner-command PATH
--coder-model MODEL     --coder-command PATH
--tester-model MODEL    --tester-command PATH
--max-rounds N
```

Secrets are rejected in `config.toml`; harnesses inherit authentication from
the current process environment. Harness `extra_args` cannot override the
host-controlled sandbox level or CLI configuration (`-s/--sandbox/-c/--config/--profile/--yolo/...`
are rejected at load time), and Codex harnesses always run with the
`workspace-write` sandbox.

## Trust and safety model

- **Host-executed checks**: after every tester round the host itself runs the
  project's detected test commands and records them in `host-checks.json`.
  The deterministic gate fails on host failures and on tester reports that
  contradict them — a harness claiming success cannot pass the gate.
- **Host-protected paths**: `.git/**`, `.metacoding/config.toml`,
  `.metacoding/state.json`, and `.metacoding/active-run.lock` are protected
  by the host itself, even when a planner allows `**`.
- **Tester write scope**: during its stage the tester may only write inside
  `.metacoding/runs/<run-id>/` and `docs/metacoding/TEST_REPORT.md`.
- **Owned diff delivery**: the delivery staging set is computed from a
  content-hash baseline captured at run start. Files that were already dirty
  before the run ("mixed" files), files outside the allowed scope, and files
  whose contract-document content no longer matches what the host rendered
  are never staged automatically — they are recorded as warnings instead.

## File layout

```text
docs/metacoding/          human-readable, committable contract documents
  PRD.md ARCHITECTURE.md IMPLEMENTATION_PLAN.md ACCEPTANCE.md
  TEST_REPORT.md FINAL_REPORT.md README.md
.metacoding/              runtime metadata (see .gitignore)
  config.toml             project configuration (committable, no secrets)
  state.json              pointer to the active run
  runs/<run-id>/          structured run history: run.json, initial-plan.json,
                          rounds/round-NNN/*.json, transcripts/, git/, final.json
  fake-scenario.json      fake-harness scripts for tests
```

Planner documents are the development contract: the Coder and Tester work
against `docs/metacoding/`, and every round's evidence is preserved under
`.metacoding/runs/<run-id>/rounds/`.

## Recovery

Every state transition is persisted atomically before the next harness
starts. If the process is interrupted, run:

```bash
metacoding status   # see the persisted state
metacoding resume   # continue from the exact pending stage
```

Terminal runs (delivered / blocked / failed infrastructure / human review /
cancelled) cannot be resumed. One MetaCoding run is active per project at a
time (`.metacoding/active-run.lock`); stale locks from dead processes are
detected and replaced, live ones are never overwritten.

## GitHub delivery (optional, off by default)

After local acceptance and all deterministic gates pass, MetaCoding can
deliver on a dedicated `metacoding/<run-id>` branch:

- only the run's owned files are staged — never your pre-existing dirty files
  (files mixing your edits with run edits are excluded and reported)
- no force-push, no rewriting of existing commits, never the default branch
- push / Pull Request / check waiting require explicit `[github]` opt-in
- required checks are polled until settled; failed checks (with
  `wait_for_checks = true`) send the run back to tester evidence and planner
  review once — a second failure requires human review instead of silently
  marking the run delivered

## Development

```bash
python3 -m pytest -q                # full suite (offline, fake harnesses)
python3 -m pytest tests/metacoding/test_orchestrator.py -q
python3 -m metacoding --help
```

Real-harness integration tests are skipped unless explicitly enabled with
environment variables (see `tests/metacoding/test_real_integrations.py`).

Design documents: [docs/plans/2026-09-07-metacoding-design.md](docs/plans/2026-09-07-metacoding-design.md)
and [docs/plans/2026-09-07-metacoding-implementation.md](docs/plans/2026-09-07-metacoding-implementation.md).
