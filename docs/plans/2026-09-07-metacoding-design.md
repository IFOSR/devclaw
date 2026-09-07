# MetaCoding Product and System Design

## 1. Product Definition

MetaCoding is a project-local AI software development orchestration tool.

The user enters an existing project directory and starts MetaCoding:

```bash
cd /path/to/project
metacoding
```

MetaCoding then coordinates exactly three Harnesses:

1. **Planner Harness**, powered by Codex, understands the requirement and owns product planning, architecture, acceptance criteria, iteration decisions, and final acceptance.
2. **Coding Harness**, powered by Pi, implements the Planner's approved plan directly in the current project.
3. **Tester Harness**, powered by Codex, independently reviews the implementation, runs tests, evaluates product and PRD compliance, and produces evidence.

The three Harnesses share the current project directory as their common context. They do not maintain separate conversational truth. Project source code, tests, planning documents, reports, and MetaCoding runtime records are all available through the shared filesystem.

MetaCoding itself is the deterministic host and orchestrator. It is not a fourth Harness and does not make product decisions. It controls process execution, state transitions, report validation, persistence, safety policies, and optional GitHub delivery.

## 2. Product Goals

MetaCoding must:

- Turn a natural-language development requirement into a reviewable PRD, architecture, implementation plan, and acceptance criteria.
- Let Pi implement the plan in the current project directory.
- Let an independent Codex Tester verify the real code and tests.
- Let the Codex Planner decide whether the product meets the original requirement.
- Repeat the Coding and Tester loop until the Planner accepts the result or the run reaches a defined blocked condition.
- Preserve enough state and evidence to resume, inspect, and audit every run.
- Support independent project-level model configuration without modifying system-level Codex or Pi configuration.
- Optionally deliver accepted work to GitHub through a branch and Pull Request workflow.

MetaCoding v1 is intentionally not:

- A large organization of specialized AI roles.
- A general-purpose multi-agent framework.
- A background daemon or multi-project server.
- An automatic production deployment system.
- A system that allows an AI Harness to push directly to a protected branch.

## 3. Core Principles

### 3.1 Exactly Three Harnesses

Product management, architecture, implementation planning, and acceptance decisions belong to the Planner. Coding belongs to Pi. Review and testing belong to the Tester.

The runtime must not recreate the existing multi-role workflow under different names.

### 3.2 The Project Directory Is Shared Context

All Harnesses run with the current project directory as their working directory. A Harness must read relevant project files and MetaCoding documents before acting.

The filesystem is the durable communication channel:

```text
Planner writes the development contract
    -> Coding reads and implements it
    -> Tester reads the contract and implementation
    -> Planner reads the test evidence and decides
```

Prompts may point to files and state the current task, but they must not duplicate the entire project history on every invocation.

### 3.3 Planner Documents Are the Development Contract

The current PRD, architecture, implementation plan, and acceptance criteria define the active development contract.

Coding and Tester Harnesses must evaluate the project against these documents rather than independently redefining the user's request.

### 3.4 Evidence Before Acceptance

The Tester provides evidence. The Planner makes the product decision. MetaCoding enforces deterministic hard gates.

A run cannot be delivered merely because a Harness says that it is complete.

### 3.5 Project-Local Configuration

MetaCoding configuration applies only to the current project. MetaCoding must not write to or replace system-level Codex, Pi, Git, or GitHub configuration.

## 4. User Experience

### 4.1 Starting MetaCoding

Running `metacoding` starts a foreground interactive process for the current directory:

```text
$ metacoding

MetaCoding
Project  /path/to/project
Planner  codex / planner-model
Coder    pi / coding-model
Tester   codex / tester-model

metacoding >
```

Natural-language input creates a new run:

```text
metacoding > Add an audit log to all administrative account changes.
```

The terminal displays concise lifecycle updates without dumping raw Harness output:

```text
[planning] Planner is analyzing the project and requirement.
[coding]   Pi is implementing round 1.
[testing]  Tester is running review and acceptance checks.
[review]   Planner requested rework for 2 blocking findings.
[coding]   Pi is implementing round 2.
[testing]  All blocking acceptance checks passed.
[done]     Planner accepted the implementation.
```

Raw output is retained under `.metacoding/` for diagnosis.

### 4.2 Non-Interactive Use

MetaCoding should also support:

```bash
metacoding run "Add an audit log to all administrative account changes."
```

The command exits with:

- `0` when the local run is accepted and all required delivery stages pass.
- A non-zero status when blocked, interrupted, invalidly configured, or failed.

### 4.3 Resume

If the process is interrupted, the next `metacoding` invocation detects the unfinished run and offers a resume command. Resume behavior is based on persisted state, not reconstructed chat history.

## 5. Project File Layout

MetaCoding separates product artifacts from runtime metadata:

```text
project/
├── source and configuration files
├── tests/
├── docs/
│   └── metacoding/
│       ├── PRD.md
│       ├── ARCHITECTURE.md
│       ├── IMPLEMENTATION_PLAN.md
│       ├── ACCEPTANCE.md
│       ├── TEST_REPORT.md
│       └── FINAL_REPORT.md
└── .metacoding/
    ├── config.toml
    ├── state.json
    ├── context/
    ├── runs/
    ├── transcripts/
    ├── logs/
    └── github/
```

### 5.1 Human-Readable Project Documents

`docs/metacoding/` contains durable documents intended for developers and reviewers:

- `PRD.md`: user problem, goals, scenarios, scope, non-goals, and product requirements.
- `ARCHITECTURE.md`: technical approach, module boundaries, data flow, interfaces, risks, and constraints.
- `IMPLEMENTATION_PLAN.md`: ordered implementation tasks, affected areas, test expectations, and completion conditions.
- `ACCEPTANCE.md`: blocking and non-blocking acceptance criteria with verification methods.
- `TEST_REPORT.md`: latest Tester result, commands, findings, evidence, regressions, and PRD drift.
- `FINAL_REPORT.md`: final Planner decision, delivered scope, evidence summary, known limitations, and GitHub status.

These files are part of the project documentation and may be committed to Git.

Planner-owned documents are `PRD.md`, `ARCHITECTURE.md`, `IMPLEMENTATION_PLAN.md`, `ACCEPTANCE.md`, and `FINAL_REPORT.md`. The Tester owns `TEST_REPORT.md`.

### 5.2 Runtime Metadata

`.metacoding/` contains MetaCoding's machine-oriented data:

- `config.toml`: project-specific Harness, policy, limit, and GitHub settings.
- `state.json`: pointer to the active run and its current lifecycle state.
- `context/`: generated project inventory and concise history indexes.
- `runs/`: complete structured history for each user requirement.
- `transcripts/`: raw Harness prompts, stdout, stderr, command metadata, and return codes.
- `logs/`: MetaCoding host logs.
- `github/`: latest branch, commit, Pull Request, and CI state.

The directory is not a sandbox and not a separate project. All Harnesses can read it as part of the shared project context.

Recommended Git behavior:

```gitignore
.metacoding/state.json
.metacoding/runs/
.metacoding/transcripts/
.metacoding/logs/
.metacoding/github/
```

`.metacoding/config.toml` may be committed when it contains no secrets. Projects may also choose to commit selected structured run records for regulated or audit-heavy workflows.

## 6. Run and Round Model

A **run** represents one user requirement from initial planning to final outcome.

A **round** represents one Planner instruction, Coding execution, Tester execution, and Planner decision cycle.

```text
.metacoding/runs/<run-id>/
├── request.md
├── initial-plan.json
├── run.json
├── rounds/
│   ├── 001/
│   │   ├── planner-instruction.json
│   │   ├── coding-report.json
│   │   ├── tester-report.json
│   │   └── planner-decision.json
│   └── 002/
│       ├── planner-instruction.json
│       ├── coding-report.json
│       ├── tester-report.json
│       └── planner-decision.json
└── final.json
```

`request.md` preserves the original user input and relevant attachments.

`initial-plan.json` is the machine-readable counterpart to the initial Planner documents.

`run.json` records immutable run identity plus current status, round number, timestamps, base Git revision, and configuration snapshot.

Each round records exactly what every Harness received, produced, and decided. Reports from later rounds do not overwrite earlier evidence.

`final.json` records one of these terminal outcomes:

- `delivered`
- `blocked`
- `failed_infrastructure`
- `human_review_required`
- `cancelled`

## 7. Lifecycle State Machine

MetaCoding uses an explicit persisted state machine:

```text
IDLE
  -> PLANNING
  -> CODING
  -> TESTING
  -> PLANNER_REVIEW
      -> ACCEPTED
      -> REWORK_REQUIRED -> CODING
      -> BLOCKED
      -> HUMAN_REVIEW_REQUIRED
  -> GITHUB_DELIVERY
  -> DELIVERED
```

Rules:

- The Coding Harness cannot start before a valid Planner plan exists.
- The Tester cannot start before the Coding Harness process has exited.
- Planner review cannot start before a structurally valid Tester report exists.
- `REWORK_REQUIRED` must contain concrete rework tasks before transitioning to `CODING`.
- `ACCEPTED` must pass deterministic host gates before delivery.
- GitHub delivery occurs only after local acceptance.
- Every state transition is atomically persisted before the next Harness starts.
- An interrupted Harness is never assumed to have completed.

## 8. Harness Responsibilities

### 8.1 Planner Harness

Default provider: Codex.

The Planner:

- Reads the original request and current project.
- Identifies existing architecture, conventions, tests, and constraints.
- Creates or updates the PRD.
- Creates or updates the architecture.
- Defines implementation tasks and allowed scope.
- Defines measurable acceptance criteria.
- Reads Coding and Tester reports.
- Evaluates bug impact, regression risk, and PRD drift.
- Chooses `accept`, `rework`, `blocked`, or `human_review_required`.
- Generates concrete rework instructions when work must continue.

The Planner must not modify product source code or product tests.

### 8.2 Coding Harness

Default provider: Pi.

The Coding Harness:

- Reads the current Planner documents and round instruction.
- Reads relevant source code, tests, and repository instructions.
- Implements only the active plan and rework tasks.
- Adds or updates product tests when required.
- Runs focused development checks.
- Reports changed files, tests, limitations, and blockers.

The Coding Harness must not:

- Rewrite the PRD or acceptance criteria.
- Mark the product as accepted.
- Modify Tester reports or Planner decisions.
- Perform GitHub delivery.

### 8.3 Tester Harness

Default provider: Codex.

The Tester:

- Reads the request, PRD, architecture, implementation plan, and acceptance criteria.
- Inspects the current source, tests, and Git diff.
- Runs detected project tests and acceptance-specific commands.
- Reviews correctness, regressions, security risks, missing tests, and maintainability risks.
- Evaluates whether the implementation diverges from the PRD.
- Produces a human-readable and machine-readable report.

The Tester must not modify product source code. It may create temporary test artifacts under `.metacoding/`, but it cannot repair the implementation directly.

## 9. Structured Harness Protocols

Harness output is accepted only when it matches the required schema. Markdown files are useful for people, while JSON reports drive orchestration.

### 9.1 Planner Initial Plan

```json
{
  "goal": "Add auditable administrative account changes.",
  "scope": [],
  "non_goals": [],
  "architecture": {
    "approach": "",
    "modules": [],
    "data_flow": [],
    "risks": []
  },
  "acceptance_criteria": [
    {
      "id": "F-001",
      "description": "",
      "priority": "blocking",
      "verification_method": ""
    }
  ],
  "coding_tasks": [
    {
      "id": "TASK-001",
      "description": "",
      "expected_files": [],
      "required_tests": [],
      "done_when": ""
    }
  ],
  "change_policy": {
    "allowed_paths": [],
    "protected_paths": [],
    "forbidden_actions": []
  }
}
```

### 9.2 Coding Report

```json
{
  "status": "completed",
  "summary": "",
  "completed_tasks": [],
  "changed_files": [],
  "tests_added_or_changed": [],
  "commands_run": [],
  "known_limitations": [],
  "blocked_reason": null
}
```

### 9.3 Tester Report

```json
{
  "status": "fail",
  "test_commands": [
    {
      "command": "python3 -m pytest -q",
      "exit_code": 1,
      "summary": ""
    }
  ],
  "acceptance_results": [
    {
      "id": "F-001",
      "status": "fail",
      "impact": "high",
      "evidence": []
    }
  ],
  "findings": [
    {
      "id": "BUG-001",
      "type": "bug",
      "severity": "P1",
      "title": "",
      "impact": "",
      "reproduction": [],
      "evidence": [],
      "recommended_fix": ""
    }
  ],
  "prd_drift": [],
  "regression_risks": [],
  "missing_tests": []
}
```

### 9.4 Planner Decision

```json
{
  "decision": "rework",
  "reason": "",
  "blocking_findings": ["BUG-001"],
  "rework_tasks": [
    {
      "id": "REWORK-001",
      "description": "",
      "target_area": [],
      "verification": ""
    }
  ]
}
```

## 10. Acceptance and Severity Policy

Finding severities:

- `P0`: destructive data loss, critical security exposure, or total core-system failure.
- `P1`: broken primary user flow, major regression, or material PRD violation.
- `P2`: significant non-core defect, usability failure, or maintainability risk.
- `P3`: minor issue, documentation issue, or optional improvement.

MetaCoding permits delivery only when:

```text
Planner decision is accept
AND all blocking acceptance criteria passed
AND all required local test commands passed
AND no P0 or P1 finding remains
AND no protected-path or forbidden-action policy was violated
AND all required structured artifacts exist and validate
```

The Planner may decide whether a P2 issue blocks delivery, but must record the rationale. P3 issues may be recorded as known limitations.

MetaCoding's host gates override an invalid Planner acceptance. For example, a Planner cannot accept a run containing a P1 finding or failed required test.

## 11. Project-Level Configuration

MetaCoding reads configuration only from:

```text
<current-project>/.metacoding/config.toml
```

Example:

```toml
[project]
schema_version = 1

[limits]
max_rounds = 6
same_failure_limit = 2
idle_timeout_seconds = 900

[harness.planner]
provider = "codex"
command = "codex"
model = "planner-model"
extra_args = []

[harness.coder]
provider = "pi"
command = "pi"
model = "coding-model"
extra_args = []

[harness.tester]
provider = "codex"
command = "codex"
model = "tester-model"
extra_args = []

[policy]
allow_network = false
allow_destructive_commands = false
tester_can_modify_source = false

[github]
enabled = false
remote = "origin"
mode = "pull-request"
branch_prefix = "metacoding/"
auto_commit = true
auto_push = false
auto_create_pr = false
wait_for_checks = true
```

Configuration precedence:

```text
built-in defaults
    -> current project's .metacoding/config.toml
    -> current command-line overrides
```

MetaCoding must not:

- Modify `~/.codex` or Pi's system-level configuration.
- Create a global MetaCoding configuration that silently affects projects.
- Persist command-line overrides outside the current project.
- Store API tokens in `config.toml`.
- Permanently alter shell environment variables.

Each Harness invocation receives its configured model and arguments directly through that subprocess invocation. Planner and Tester configurations remain independent even though both use Codex.

## 12. Concurrency and Shared-Directory Safety

All Harnesses share one real project directory, but they run sequentially.

Only one Harness process may be active for a run at a time:

```text
Planner exits
    -> Coding starts and exits
    -> Tester starts and exits
    -> Planner review starts
```

MetaCoding uses a project-local lock to prevent two MetaCoding processes from modifying the same project concurrently.

Before Coding starts, MetaCoding records:

- Current Git revision when available.
- Existing dirty files.
- Relevant project file inventory.
- Detected test commands.

After Coding exits, MetaCoding records:

- Git diff.
- Changed and untracked files.
- Protected-path violations.
- Coding report.

Planner and Tester write only their owned documents and `.metacoding/` artifacts. Document updates use temporary files followed by atomic replacement.

## 13. Failure, Rework, and Stop Conditions

The system iterates toward acceptance but does not loop without limits.

Default policies:

- Maximum of six Coding/Tester rounds.
- One automatic retry for malformed structured Harness output.
- A run becomes blocked when the same failure fingerprint remains unresolved for two consecutive rounds.
- A run becomes blocked when changes repeatedly expand outside the Planner's allowed scope.
- A missing Harness command, authentication failure, or repeated timeout becomes `failed_infrastructure`, not a product failure.
- Production deployment, paid external actions, credentials, irreversible operations, or protected branch updates require human review.
- Reaching the maximum round count produces a complete blocked report and preserves all evidence.

Failure fingerprints are derived from stable acceptance IDs, finding types, affected areas, and normalized failure summaries. They are not based only on free-form wording.

## 14. Git and GitHub Delivery

GitHub delivery is an optional host-controlled stage after local acceptance.

Harnesses may inspect Git state, but they do not own commit, push, or Pull Request operations. MetaCoding performs these operations through deterministic Git and GitHub adapters.

Recommended flow:

```text
local Planner acceptance
    -> verify repository state
    -> create or reuse metacoding/<run-id> branch
    -> create commit
    -> optionally push branch
    -> optionally create or update Pull Request
    -> optionally wait for GitHub checks
    -> record final delivery state
```

Default safety policy:

- Never push directly to the default or protected branch.
- Use `metacoding/<run-id>` branches.
- Do not force-push.
- Do not rewrite existing user commits.
- Do not stage unrelated pre-existing user changes.
- Require explicit project configuration before remote push or Pull Request creation.
- Read authentication from existing Git or `gh` state and environment variables.
- Never modify global Git or `gh` configuration.

When `wait_for_checks = true`, failed required GitHub checks return the run to Tester evidence collection and Planner review. The resulting rework loop starts only after the remote failure is recorded in the run.

GitHub unavailability must not invalidate an already accepted local implementation unless the project explicitly requires successful remote delivery.

## 15. Proposed Implementation Architecture

The current DevClaw code is reference material rather than a required migration base. MetaCoding should be implemented around the new domain model instead of preserving the existing multi-role orchestration.

Proposed package:

```text
metacoding/
├── __init__.py
├── __main__.py
├── cli.py
├── service.py
├── config.py
├── models.py
├── state.py
├── artifacts.py
├── policies.py
├── project.py
├── process_runner.py
├── orchestrator.py
├── github.py
└── harnesses/
    ├── __init__.py
    ├── base.py
    ├── codex_planner.py
    ├── pi_coder.py
    └── codex_tester.py
```

Primary boundaries:

- `cli.py`: command parsing and interactive terminal behavior.
- `service.py`: application entry points for starting, running, resuming, and reporting.
- `config.py`: project-local TOML loading, defaults, validation, and CLI overrides.
- `models.py`: plans, reports, decisions, run records, and enums.
- `state.py`: legal transitions, locking, persistence, and resume.
- `artifacts.py`: atomic document and JSON artifact management.
- `policies.py`: deterministic acceptance, path, severity, and stop gates.
- `project.py`: repository discovery, file inventory, Git baseline, and test command detection.
- `process_runner.py`: subprocess execution, idle monitoring, transcript capture, and error classification.
- `orchestrator.py`: three-Harness lifecycle and rework loop.
- `github.py`: safe branch, commit, push, Pull Request, and check operations.
- `harnesses/`: provider-specific command construction and structured output parsing.

## 16. Migration Strategy

This is a product rewrite, not an incremental extension of the current role architecture.

Reusable concepts from DevClaw:

- Running from the current project directory.
- Foreground interactive and one-shot CLI modes.
- Idle-output monitoring for long-running tools.
- Project context and test command detection.
- Persistent transcripts.
- Recoverable interactive failures.
- Project-local metadata.
- Avoiding root `README.md` replacement.

Concepts not carried into the new core:

- Multi-role `ROLE_ASSIGNMENTS`.
- Codex/Deepseek role routing.
- Research, PM, Design, Release, Delivery, and Archivist role chains.
- `VerificationReport.passed()` as the final delivery decision.
- Workflow modes that select subsets of role Agents.
- Deepseek as a required default provider.

During implementation, the existing `devclaw/` package may remain temporarily while the new `metacoding/` package and tests are built. The final CLI and documentation should present only MetaCoding.

## 17. Verification Strategy

The implementation must include deterministic fake Harnesses so the complete lifecycle is testable without Codex, Pi, GitHub, or network access.

Required behavior tests:

- `metacoding` uses the current directory as project root.
- Exactly Planner, Coding, and Tester Harnesses participate in the core loop.
- Planner and Tester can use different Codex models.
- Project configuration does not modify system-level Codex or Pi configuration.
- Coding cannot run before a valid plan exists.
- Tester always runs after Coding exits.
- Planner receives the current Tester report before deciding.
- A failed Tester report produces Planner rework tasks.
- Rework tasks are supplied to the next Pi round.
- A new Tester report is required after every Coding round.
- Passing tests do not override a remaining P0 or P1 finding.
- Planner acceptance does not override failed deterministic host gates.
- PRD drift can cause rework even when automated tests pass.
- Repeated failure fingerprints cause a blocked result.
- Maximum-round exhaustion produces a blocked report.
- Interrupted runs can resume from persisted state.
- Concurrent MetaCoding runs for one project are rejected.
- Tester source modifications are detected and rejected.
- Existing unrelated dirty files are not committed by GitHub delivery.
- GitHub delivery uses a dedicated branch and never force-pushes.
- GitHub CI failure can return the run to Planner review when configured.

Opt-in integration tests:

- Real Codex Planner invocation.
- Real Pi Coding invocation.
- Real Codex Tester invocation.
- Real Git repository branch and commit flow.
- Real GitHub Pull Request and checks flow in a disposable repository.

## 18. Delivery Milestones

### Milestone 1: Local Deterministic Core

- New `metacoding` package and command.
- Project-local configuration.
- Run and round models.
- Persisted state machine.
- Fake three-Harness end-to-end loop.
- Human-readable and structured artifacts.

### Milestone 2: Real Harness Integration

- Codex Planner adapter.
- Pi Coding adapter.
- Codex Tester adapter.
- Independent model configuration.
- Transcript, timeout, malformed output, and retry handling.

### Milestone 3: Safety and Recovery

- Project locking.
- Git baseline and diff tracking.
- Ownership and protected-path checks.
- Failure fingerprinting.
- Resume after interruption.

### Milestone 4: GitHub Delivery

- Safe branch and commit creation.
- Optional push and Pull Request creation.
- GitHub checks monitoring.
- Remote CI evidence in the Planner loop.

## 19. Accepted Product Decisions

- The product name is **MetaCoding**.
- The command name is `metacoding`.
- MetaCoding runs from and operates on the current project directory.
- The system has exactly three Harnesses: Codex Planner, Pi Coder, and Codex Tester.
- All three Harnesses share the current project directory as their context.
- Planner documents and Tester reports are stored in the current project.
- Human-readable artifacts live under `docs/metacoding/`.
- Runtime configuration, state, history, transcripts, and GitHub metadata live under `.metacoding/`.
- Configuration is project-local and does not modify system-level Codex or Pi configuration.
- The Planner controls iteration and final product acceptance.
- GitHub delivery is host-controlled and uses a dedicated branch plus Pull Request by default.
- MetaCoding v1 is a foreground, single-project CLI process rather than a daemon.
