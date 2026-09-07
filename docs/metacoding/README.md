# MetaCoding documents

This directory holds the human-readable development contract and reports.
These files are part of the project documentation and may be committed.

## Planner-owned contract

- `PRD.md` — user problem, goals, scope, non-goals, and acceptance criteria.
- `ARCHITECTURE.md` — technical approach, modules, data flow, risks.
- `IMPLEMENTATION_PLAN.md` — ordered tasks, expected files, tests, done-when.
- `ACCEPTANCE.md` — blocking and non-blocking criteria with verification.
- `FINAL_REPORT.md` — final decision, delivered scope, warnings, GitHub status.

The host renders these from the planner's structured plan before each run's
coding stage begins. The Coder and the Tester must evaluate the project
against these documents rather than redefining the request.

## Tester-owned report

- `TEST_REPORT.md` — latest tester evidence: commands run, acceptance
  results, findings with severity, PRD drift, regression risks, and missing
  tests. Rewritten (atomically) after every testing stage.

## Boundary with `.metacoding/`

| Path | Purpose | Git |
| --- | --- | --- |
| `docs/metacoding/` | durable documents for humans and reviewers | committable |
| `.metacoding/config.toml` | project configuration (no secrets) | committable |
| `.metacoding/state.json` | active-run pointer | ignored |
| `.metacoding/runs/` | structured run history and round evidence | ignored |
| `.metacoding/transcripts/` | raw harness prompts/output | ignored |
| `.metacoding/logs/`, `.metacoding/github/` | host logs and delivery state | ignored |

See `config.example.toml` in this directory for the full configuration
schema, and the repository README for commands and model overrides.
