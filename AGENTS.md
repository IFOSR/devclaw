# Repository Guidelines

## Project Structure & Module Organization

DevClaw is a Python CLI package. Core implementation lives in `devclaw/`, with CLI entry points in `devclaw/__main__.py` and `devclaw/cli.py`. Agent role logic is under `devclaw/agents/`, reusable workflow logic under `devclaw/core/`, and external tool adapters under `devclaw/adapters/`. Tests live in `tests/` and mirror the package by behavior area, for example `tests/test_loop.py` and `tests/test_tool_runner.py`. Planning and design notes are kept in `docs/plans/`. The `scripts/devclaw` wrapper runs the package from the repository checkout.

## Build, Test, and Development Commands

- `python3 -m devclaw`: start the interactive CLI from the repo root.
- `scripts/devclaw start`: start the same interactive CLI through the shell wrapper.
- `python3 -m devclaw run "Build a customer feedback triage Agent"`: run one non-interactive request.
- `python3 -m pytest -q`: run the full test suite.
- `python3 -m pytest tests/test_cli_e2e.py -q`: run a focused test file while iterating.

There is currently no packaging file or Makefile, so prefer direct Python module and pytest commands.

## Coding Style & Naming Conventions

Use Python 3 type hints where they clarify interfaces, especially for public functions and dataclass-like models. Follow the existing style: 4-space indentation, `snake_case` functions and variables, `PascalCase` classes, and explicit imports from `devclaw.*`. Keep functions small and behavior-oriented. Use `pathlib.Path` for filesystem paths, and preserve UTF-8 reads/writes where files are created in tests or project artifacts.

## Testing Guidelines

Tests use `pytest`; asynchronous fixture loop scope is configured in `pytest.ini`. Name test files `test_*.py` and test functions `test_<behavior>()`. Prefer temporary directories via `tmp_path` for filesystem behavior, and use fakes from `tests/fakes.py` instead of invoking real Codex or Deepseek adapters unless the test is explicitly an integration/e2e case. Run `python3 -m pytest -q` before submitting changes.

## Commit & Pull Request Guidelines

The current history uses Conventional Commit style, for example `feat: add DevClaw AI R&D workflow`. Continue with short, imperative messages such as `fix: handle empty tool output` or `test: cover context refresh`. Pull requests should include a concise problem statement, implementation summary, test results, and links to any relevant issue or planning document. Include terminal output or screenshots only when they clarify CLI behavior.

## Agent-Specific Instructions

Do not overwrite a target project’s root `README.md` during DevClaw runs; delivery artifacts should remain under `.devclaw/delivery/latest/`. Treat `.devclaw/` as generated project metadata unless a task explicitly targets it.
