# DevClaw Roadmap and Product Plan

## 1. Product North Star

DevClaw is a project-local AI-native R&D team.

The user enters a project directory, starts DevClaw, and describes product, feature, tool, or Agent requirements in natural language. DevClaw coordinates specialist Agents to research, design, implement, verify, rework, and deliver changes inside the current project.

DevClaw is not a generic company operating system. It does not clone sales, finance, legal, HR, or general operations. It focuses on the full product R&D delivery lifecycle.

## 2. Current Implementation State

Implemented as of `v0.1.1`:

- Current directory is the project root.
- Interactive CLI with slash commands.
- Non-interactive `run` command.
- `.devclaw/` project metadata directory.
- Acceptance Contract generation.
- Research-first workflow.
- Role specs under `.devclaw/agents/`.
- Product, UX, and technical research reports.
- PM, Designer, Architect, Engineer, QA, Release, Delivery, and Archivist outputs.
- DevClaw Lead loop.
- Gap Report and rework routing.
- Local deterministic execution and verification adapters.
- Codex CLI executor adapter shell.
- Deepseek TUI verifier adapter shell.
- End-to-end tests.

Known issues in current implementation:

- Delivery Agent can overwrite project root `README.md`. This must be fixed before real project use.
- Research reports are deterministic templates, not real external or repo-aware research.
- Codex and Deepseek adapters exist, but real end-to-end AI execution is not yet validated.
- DevClaw does not yet scan the current project context.
- Project memory is not persisted beyond latest `.devclaw/` artifacts.
- Feedback Agent role exists in spec, but implementation is missing.
- Acceptance Contract is still generic and not generated from deep project/user research.

## 3. External Survey Takeaways

### Aider

Relevant ideas:

- Project-local CLI coding assistant.
- In-chat slash commands.
- Repository map / context compression.
- Git diff and commit-oriented workflow.
- Test/lint integration.

DevClaw implication:

- Keep project-local mode.
- Add `/diff`, `/test`, `/review`, `/commit`, and context summary.
- Build a project context engine similar in spirit to repo maps.

### OpenHands

Relevant ideas:

- Software engineering agent with CLI, GUI, cloud, and SDK layers.
- Workspace abstraction.
- Local and isolated execution environments.

DevClaw implication:

- Keep core loop as SDK-like logic.
- Add optional isolated workspace or git worktree mode for risky changes.
- Keep CLI first, but design for future UI/API layers.

### SWE-agent / mini-swe-agent

Relevant ideas:

- Issue/task oriented software engineering loop.
- Tool use and verification.
- Minimal agent core can be effective.

DevClaw implication:

- Keep loop small and testable.
- Prioritize real verification and repair over elaborate role theater.
- Make each failed acceptance map to a concrete rework action.

### MetaGPT

Relevant ideas:

- SOP-based multi-Agent software organization.
- PM, Architect, Engineer, QA roles.

DevClaw implication:

- Keep role chain, but do not clone a whole company.
- Each Agent needs role spec, inputs, outputs, non-goals, and acceptance criteria.

### Continue

Relevant ideas:

- Repo-local AI checks.
- Rules/checks versioned with the repository.

DevClaw implication:

- Store project-specific checks under `.devclaw/checks/`.
- Convert acceptance items into executable or reviewable quality gates.

### GPT Pilot / Pythagora

Relevant ideas:

- Build app from high-level requirements.
- Developer remains in the loop.

DevClaw implication:

- Maintain human approval for risky operations.
- Avoid opaque automation or external package execution without safeguards.

### CrewAI / smolagents

Relevant ideas:

- Multi-agent orchestration and lightweight agent abstractions.
- Code-as-action and sandboxing.

DevClaw implication:

- Keep adapters and Agents modular.
- Avoid heavy framework lock-in until DevClaw's own loop is stable.

## 4. Product Architecture

Target architecture:

```text
Project Directory
→ DevClaw Interactive CLI
→ DevClaw Lead
→ Project Context Engine
→ Research Agents
→ Acceptance Contract
→ PM / Designer / Architect / Engineer / QA / Release / Delivery / Feedback / Archivist
→ Verification Harness
→ Gap Report
→ Rework Loop
→ Project Memory
```

Project-local storage:

```text
project/
  .devclaw/
    agents/
    artifacts/
    checks/
    context/
    feedback/
    memory/
    reports/
    sessions/
    acceptance-contract.json
    final-delivery-report.json
  src/
  tests/
  README.md
```

Core rule:

> DevClaw never creates a new project unless the user explicitly creates or enters a new directory. All interactions are about the current project.

## 5. Agent Role Design

### DevClaw Lead

Mission:

- Own the full acceptance-driven loop.

Responsibilities:

- Interpret user input.
- Enforce research-before-build.
- Manage context gathering.
- Create or update Acceptance Contract.
- Assign Agent work.
- Judge integrated output.
- Generate Gap Reports.
- Decide stop condition.

Future work:

- Add ambiguity detection.
- Add human review gate.
- Add project memory lookup before each response.

### PM Agent

Mission:

- Convert researched intent into product definition.

Responsibilities:

- Product research.
- User/job analysis.
- Alternatives and status quo.
- PRD.
- Scope and non-goals.
- Product acceptance criteria.

Future work:

- Real web/GitHub/market research.
- Research citations.
- Product option comparison.
- MVP tradeoff scoring.

### Designer Agent

Mission:

- Ensure the product or Agent is usable.

Responsibilities:

- UX reference research.
- User journey.
- Information architecture.
- Conversation flow for Agent products.
- Usability risks.

Future work:

- Terminal UX patterns.
- Web/app UX pattern library.
- Screenshot or prototype support.
- Usability acceptance checks.

### Architect Agent

Mission:

- Choose a feasible and maintainable technical approach.

Responsibilities:

- Technical research.
- Framework and library comparison.
- Module boundaries.
- Data flow.
- Risk analysis.
- Implementation plan.

Future work:

- Project-specific architecture scanning.
- ADR generation.
- Dependency risk analysis.
- Worktree/sandbox strategy.

### Engineer Agent

Mission:

- Implement changes in the current project.

Responsibilities:

- Use Codex CLI by default.
- Modify project files.
- Add tests.
- Run project checks.
- Apply Gap Report fixes.

Future work:

- Real Codex adapter validation.
- Diff-based execution.
- Safe edit boundaries.
- Worktree isolation.

### QA Agent

Mission:

- Independently verify against Acceptance Contract.

Responsibilities:

- Use Deepseek TUI by default.
- Run tests/checks.
- Challenge assumptions.
- Produce structured verification.
- Fail blocking acceptance items precisely.

Future work:

- Real Deepseek report parser.
- Acceptance-to-test mapping.
- Regression selection.
- Quality scoring.

### Release Agent

Mission:

- Prepare safe handoff and release.

Responsibilities:

- Build checks.
- Environment and config checks.
- Deploy plan.
- Rollback plan.

Future work:

- Detect project build commands.
- Generate `.env.example`.
- Release checklist automation.
- Deployment approval gate.

### Delivery Agent

Mission:

- Package delivery without damaging existing project docs.

Responsibilities:

- Summarize changes.
- Provide run instructions.
- List known limitations.
- Link reports.

Future work:

- Do not overwrite existing `README.md`.
- Write delivery docs to `.devclaw/delivery/` by default.
- Optionally propose README patch with user approval.

### Feedback Agent

Mission:

- Convert user feedback into future iterations.

Responsibilities:

- Classify feedback.
- Link feedback to delivery version.
- Propose bugfix or feature iterations.

Future work:

- Implement `/feedback`.
- Implement feedback queue.
- Connect feedback to Acceptance Contract updates.

### Archivist Agent

Mission:

- Preserve reusable learning and project memory.

Responsibilities:

- Store decisions, reports, outcomes, and lessons.
- Extract reusable templates and failure cases.

Future work:

- Persistent `.devclaw/memory/project.json`.
- ADR index.
- Similar request retrieval.

## 6. Versioned TODO

### v0.1.2: Safe Project-Local Delivery

Goal:

Prevent DevClaw from damaging project files while preserving useful delivery artifacts.

TODO:

- Stop writing generated delivery docs directly to root `README.md` by default.
- Write delivery package to `.devclaw/delivery/latest/`.
- Add optional README patch proposal instead of overwrite.
- Add `/report` to print latest delivery report.
- Add `/artifacts` to list latest Agent outputs.
- Add tests proving existing README is not overwritten.

Acceptance:

- Existing project README remains unchanged unless explicitly approved.
- Delivery report and docs are available under `.devclaw/delivery/`.
- End-to-end CLI test verifies project-local safe delivery.

### v0.2: Project Memory

Goal:

Make DevClaw remember the current project across sessions and iterations.

TODO:

- Add `.devclaw/memory/project.json`.
- Store project name, stack, current version, and goals.
- Store historical user requests.
- Store historical Acceptance Contracts.
- Store historical Gap Reports.
- Store historical Final Delivery Reports.
- Store architecture decisions.
- Add `/memory`.
- Add `/history`.
- Add `/decisions`.
- Update memory after every completed run.
- Load memory before every new run.

Acceptance:

- User can say "continue the previous feature" and DevClaw can reference recent project memory.
- Memory survives process restart.
- Tests cover memory read/write and CLI history commands.

### v0.3: Project Context Engine

Goal:

Make DevClaw understand the current repository before planning or editing.

TODO:

- Detect language and framework.
- Detect package manager.
- Detect test commands.
- Detect lint/typecheck/build commands.
- Parse README and key docs.
- Scan directory tree with ignores.
- Read git status and recent diff.
- Build project context summary.
- Store context under `.devclaw/context/`.
- Add `/context`.
- Add `/refresh-context`.

Acceptance:

- DevClaw can summarize a Python, Node, or generic project.
- Acceptance Contract and Architecture Spec reference detected project context.
- Tests cover context extraction fixtures.

### v0.4: Real Research Workflow

Goal:

Make PM, Designer, and Architect research real, sourced, and decision-driving.

TODO:

- Add Research Plan before reports.
- Add GitHub/open-source project survey support.
- Add official documentation lookup for technical decisions.
- Add competitor/reference pattern summary.
- Add source links and timestamps.
- Add research-to-decision traceability.
- Add `/research`.
- Add `/research-only`.

Acceptance:

- PRD and Architecture Spec cite research findings.
- Research artifacts include sources and implications.
- Tests cover deterministic mocked research provider.

### v0.5: Real Codex and Deepseek Execution

Goal:

Turn adapter shells into robust real AI execution and verification.

TODO:

- Validate Codex CLI execution against current project.
- Validate Deepseek TUI verification against current project.
- Parse Deepseek output into structured Verification Report.
- Convert failed verification into Gap Report.
- Add retries and timeout handling.
- Archive raw tool transcripts.
- Add `/executor`.
- Add `/verifier`.
- Add `/review`.

Acceptance:

- End-to-end test can run real Codex/Deepseek path when credentials are available.
- Mocked tests cover tool failure, timeout, malformed output, and retry.
- Gap Report identifies failed acceptance IDs.

### v0.6: Quality Harness

Goal:

Make verification depend on real project checks, not only generated reports.

TODO:

- Run detected test commands.
- Run detected lint commands.
- Run detected typecheck commands.
- Run build commands.
- Map Acceptance Contract items to checks.
- Add quality score.
- Add `/test`.
- Add `/quality`.
- Add `/fix-tests`.

Acceptance:

- QA fails when project tests fail.
- Engineer rework can be triggered by failed checks.
- Final Delivery Report includes command evidence.

### v0.7: Feedback Loop

Goal:

Turn user feedback into structured iterations.

TODO:

- Add `/feedback <content>`.
- Classify feedback as bug, feature, usability, performance, docs, or other.
- Store feedback under `.devclaw/feedback/`.
- Link feedback to delivery version.
- Add `/feedback-list`.
- Add `/feedback-run`.
- Convert accepted feedback to Acceptance Contract delta.

Acceptance:

- Feedback can trigger a new DevClaw loop.
- Feedback is traceable to implementation and verification.
- Tests cover bug feedback and feature feedback.

### v0.8: Parallel R&D and Work Isolation

Goal:

Support complex tasks with parallel subtask execution and safe integration.

TODO:

- Add subtask DAG.
- Add multiple Engineer Agent sessions.
- Add git worktree or branch isolation.
- Add subtask QA.
- Add integration QA.
- Add conflict detection.
- Add merge plan.
- Add `/tasks`.
- Add `/pause`.
- Add `/resume`.
- Add `/cancel`.

Acceptance:

- A task can split into independent subtasks.
- Subtasks can be verified before integration.
- Failed subtasks can be retried without corrupting the project.

### v0.9: Operator Experience

Goal:

Make DevClaw feel like a polished CLI Agent similar to Codex or Claude Code.

TODO:

- Streaming status output.
- Better terminal formatting.
- Multi-line input.
- Command completion.
- Session transcripts.
- `/sessions`.
- `/resume`.
- `/diff`.
- `/commit`.
- `/undo`.
- Error recovery hints.

Acceptance:

- User can understand what each Agent is doing.
- User can resume previous sessions.
- User can inspect and commit changes safely.

### v1.0: AI R&D Factory

Goal:

Stable project-local AI R&D delivery system.

TODO:

- Template library.
- Agent scaffold.
- Web app scaffold.
- CLI tool scaffold.
- API service scaffold.
- Reusable Skill and Agent spec extraction.
- Cross-project reusable assets.
- Full research-to-acceptance-to-implementation traceability.
- Real Codex execution by default.
- Real Deepseek verification by default.
- Human approval gates for risky operations.
- Reliable delivery and feedback loop.

Acceptance:

- User can enter a project, describe a requirement, and get a verified implementation.
- DevClaw understands project context, runs real checks, and preserves project memory.
- Similar future tasks become faster through reuse.

## 7. Recommended Implementation Order

Priority order:

1. v0.1.2 Safe Project-Local Delivery.
2. v0.3 Project Context Engine.
3. v0.2 Project Memory.
4. v0.6 Quality Harness.
5. v0.5 Real Codex and Deepseek Execution.
6. v0.4 Real Research Workflow.
7. v0.7 Feedback Loop.
8. v0.9 Operator Experience.
9. v0.8 Parallel R&D and Work Isolation.
10. v1.0 Factory-level reuse and hardening.

Reasoning:

- Safe delivery must come first to avoid damaging real projects.
- Context and memory are prerequisites for focused iteration.
- Quality harness is required before trusting real execution.
- Real AI execution should be added only after the loop has strong context and checks.

## 8. Testing Strategy

Every version must include:

- Unit tests for core models and contracts.
- Agent output tests.
- CLI interaction tests.
- End-to-end project-local tests.
- Regression tests proving existing project files are not unexpectedly overwritten.
- DevClaw self-regression on this repository.

Real AI tests:

- Keep deterministic local tests as default.
- Add opt-in integration tests for Codex and Deepseek using environment flags.
- Archive raw transcripts under `.devclaw/reports/`.

## 9. Definition of Done

A version is done only when:

- It has tests.
- It has an end-to-end project-local run.
- It updates `.devclaw/` artifacts correctly.
- It does not overwrite project files unexpectedly.
- It updates docs.
- It passes DevClaw self-regression.
