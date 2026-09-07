# Repository Guidelines

## Project Structure & Module Organization

MetaCoding is a Python CLI package that orchestrates three AI harnesses
(Codex Planner, Pi Coder, Codex Tester) inside the current project
directory. Core implementation lives in `metacoding/`: CLI entry points in
`__main__.py`/`cli.py`, the interactive loop in `tui.py`, application wiring
in `service.py`, boundary models and protocol validation in `models.py` and
`errors.py`, configuration in `config.py`, project/git inspection in
`project.py`, the project lock in `locking.py`, run persistence in
`persistence.py`, subprocess execution in `process_runner.py`, deterministic
gates in `policies.py`, the state machine in `orchestrator.py`, and delivery
in `github.py`. Harness adapters live under `metacoding/harnesses/`
(`codex_planner.py`, `pi_coder.py`, `codex_tester.py`, and `fake.py` for
offline tests). Tests live in `tests/metacoding/` and mirror the package by
behavior area. Planning and design notes are kept in `docs/plans/`.

## Build, Test, and Development Commands

- `python3 -m metacoding`: start the interactive TUI from the repo root.
- `scripts/metacoding`: run the package through the shell wrapper.
- `python3 -m metacoding run "Add an audit log"`: run one request
  non-interactively.
- `python3 -m pytest -q`: run the full test suite (offline; fake harnesses).
- `python3 -m pytest tests/metacoding/test_orchestrator.py -q`: focused file.

There is no packaging file or Makefile; prefer direct Python module and
pytest commands. Real Codex/Pi integration tests are skipped unless enabled
via environment variables in `tests/metacoding/test_real_integrations.py`.

## Coding Style & Naming Conventions

Use Python 3 type hints where they clarify interfaces, especially for public
functions and dataclass-like models. Follow the existing style: 4-space
indentation, `snake_case` functions and variables, `PascalCase` classes, and
explicit imports from `metacoding.*`. Keep functions small and
behavior-oriented. Use `pathlib.Path` for filesystem paths; persisted paths
are stored as POSIX strings relative to the project root, and timestamps as
ISO 8601 UTC strings ending in `Z`. Harness payloads are validated by
`metacoding.models.validate_*` functions; never silently fill defaults for
invalid structured output.

## Testing Guidelines

Tests use `pytest`; name files `test_*.py` and functions `test_<behavior>()`.
Avoid names starting with `test` for helper factories. Use temporary
directories via `tmp_path` for filesystem behavior. Exercise harnesses with
the scripted fakes from `metacoding.harnesses.fake` (in-process scenario
dicts for orchestrator tests, or `provider = "fake"` subprocess mode for
end-to-end tests) instead of invoking real Codex or Pi unless the test is an
explicitly opt-in integration case. Run `python3 -m pytest -q` before
submitting changes.

## Commit & Pull Request Guidelines

History uses Conventional Commit style. Continue with short, imperative
messages such as `feat: add metacoding orchestrator` or `fix: guard EOF in
TUI loop`. Pull requests should include a concise problem statement,
implementation summary, test results, and links to any relevant planning
document (for this rewrite: the two documents under `docs/plans/`).

## Agent-Specific Instructions

MetaCoding runs operate on the operator's project; never overwrite a target
project's root `README.md` during runs, and keep delivery artifacts under
`docs/metacoding/` and `.metacoding/`. Treat `.metacoding/` runtime state as
generated project metadata unless a task explicitly targets it. Do not
force-push, do not modify global Codex/Pi/Git configuration, and never store
tokens in `.metacoding/config.toml`.
