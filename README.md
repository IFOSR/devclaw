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
/parallel-run <requirement> Run independent Codex subtasks in parallel.
/paste-image [note]  Attach the current clipboard image to the next request.
/attach <path> [note] Attach an image file to the next request.
/attachments          List pending image attachments.
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

Interactive sessions are resilient by design. If a single DevClaw task fails, the
CLI prints a concise `Task failed` message and returns to the prompt instead of
exiting the application. Natural-language requests are persisted before the run
starts, so after a restart you can use the up/down arrow keys to recall earlier
tasks and retry them.

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
  stages/<project_id>/<session_id>/
  scaffolds/
  tasks/
  acceptance-contract.json
  final-delivery-report.json
  project-brief.json
```

Delivery docs are written to `.devclaw/delivery/latest/` by default. DevClaw does not overwrite the project root `README.md`.

Every default R&D run is sequential: each Agent starts only after the previous Agent has produced output. Implementation is verified before final release and delivery reports are written. Reviewable Markdown for each phase is written under `.devclaw/stages/<project_id>/<session_id>/`, including `workflow-plan.md` and `index.md`. Parallel execution happens only when you explicitly run `/parallel-run`.

Long-running Codex/Deepseek steps emit compact heartbeat lines about once per minute so the terminal shows which Agent is still active without dumping raw tool logs.

Before each run, DevClaw writes `.devclaw/context/current-context-pack.md` from recent memory, session manifests, changed files, and stage document references. Follow-up requests can use an incremental workflow such as `targeted-change` or `bugfix`; reused stages write `stage-reuse-note.md` instead of pretending the full research/PRD/design flow ran again.

In interactive terminals, paste a screenshot with `Ctrl+V` or use `/paste-image`; DevClaw shows a pending image count in the prompt and attaches the image to the next requirement.

Default role assignment is tuned to each model family: Codex handles intake, UX
research, architecture reasoning, technical planning, implementation, QA
verification, and fix loops; Deepseek handles product research, PRD, test
execution, code review, release review, delivery reporting, and archiving. Each
role prompt asks the Agent to document skills used, reasoning, evidence, and
output so stage artifacts remain auditable.

## Current Capabilities

- Project-local interactive CLI.
- Slash command system.
- Research-first workflow.
- Sequential role workflow with per-stage Markdown outputs.
- Cross-session context pack and incremental workflow routing.
- Screenshot attachment from clipboard or file before a run.
- Persistent prompt history with arrow-key recall across restarts.
- Recoverable interactive task failures that keep DevClaw running.
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
