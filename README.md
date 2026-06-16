# DevClaw

DevClaw is a project-local, acceptance-driven AI-native R&D team.

Run it inside the project directory you want to modify. All natural-language requests are treated as work for the current project, and DevClaw stores its metadata under `.devclaw/`.

## Quick Start

Interactive mode:

```bash
scripts/devclaw start
```

Or directly:

```bash
python3 -m devclaw
```

Non-interactive one-shot run:

```bash
python3 -m devclaw run "Build a customer feedback triage Agent"
```

Use real tool adapters explicitly:

```bash
python3 -m devclaw \
  --executor codex \
  --verifier deepseek \
  --idle-timeout 900 \
  run "Implement the next feature"
```

## Interactive Commands

Natural language without `/` is always treated as a current-project R&D request.

```text
/help                 Show help.
/status               Show current project and metadata path.
/config               Show runtime configuration.
/context              Show project context.
/refresh-context      Rescan project context.
/memory               Show project memory summary.
/history              Show request history.
/decisions            Show architecture decisions.
/research <topic>     Create a project-aware research report.
/scaffold <type> <name> Create an agent or CLI scaffold spec.
/risk                 Create a risk review report.
/tasks <requirement>  Create a task DAG plan.
/test                 Run detected project tests.
/quality              Run/show quality report.
/feedback <content>   Record feedback.
/feedback-list        List feedback.
/feedback-run <id>    Run feedback as a DevClaw task.
/report               Print latest final delivery report.
/artifacts            List latest artifacts.
/sessions             Show previous requests.
/diff                 Show current git diff if available.
/clear                Visually separate output.
/run <requirement>    Run one requirement explicitly.
/exit                 Exit DevClaw.
```

## Project Output

DevClaw writes metadata and delivery artifacts under `.devclaw/`:

```text
.devclaw/
  agents/
  artifacts/
  context/
  delivery/latest/
  feedback/
  memory/
  reports/
  research/
  scaffolds/
  tasks/
  acceptance-contract.json
  final-delivery-report.json
  project-brief.json
```

Delivery docs are written to `.devclaw/delivery/latest/` by default. DevClaw does not overwrite the project root `README.md`.

## Current Capabilities

- Project-local interactive CLI.
- Slash command system.
- Research-first workflow.
- Agent role specifications.
- Acceptance Contract generation.
- DevClaw Lead loop with verification and rework.
- Project context scanning.
- Project memory.
- Feedback capture and feedback-driven runs.
- Quality checks based on detected test commands.
- Safe project-local delivery.
- Codex CLI and Deepseek TUI adapter shells.
- Codex CLI adapter uses non-interactive `codex exec -C <project> --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox`.
- Real tool calls use an idle-output monitor, not a hard total timeout. Long-running Codex/Deepseek work may continue as long as the process keeps producing output; DevClaw only treats it as stalled after `--idle-timeout` seconds with no stdout/stderr activity.

## Test

```bash
python3 -m pytest -q
```

## Design Docs

- [DevClaw Design](docs/plans/devclaw-design.md)
- [DevClaw Roadmap and Product Plan](docs/plans/devclaw-roadmap.md)
- [DevClaw v0.1 Implementation Plan](docs/plans/2026-06-14-devclaw-v0.1-implementation.md)
