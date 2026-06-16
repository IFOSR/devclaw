# DevClaw Design

## 1. Product Definition

DevClaw is an AI-native R&D delivery system.

Its goal is not to clone a whole company. It focuses on one thing:

> A user describes a product, feature, tool, or Agent requirement. DevClaw organizes an AI product development team to deliver a runnable product, module, or Agent.

DevClaw covers the full product R&D delivery lifecycle:

- Requirement clarification
- Product definition
- UX and interaction design
- Technical architecture
- Implementation
- QA and verification
- Release preparation
- Delivery packaging
- Feedback tracking
- Project memory and asset reuse

DevClaw does not include unrelated company functions such as sales, finance, legal, HR, or general business operations.

## 2. Core Principle

DevClaw is acceptance-driven.

Every Agent output must be evaluated against the original user need. A role finishing its own task does not mean the project is done.

The project is complete only when all outputs work together and satisfy the acceptance contract.

If the integrated result does not meet the acceptance contract, DevClaw generates a gap report and sends the relevant work back to the responsible Agent until the stop condition is reached.

## 3. System Flow

```text
User Intent
→ DevClaw Lead
→ Acceptance Contract
→ PM / Design / Architecture / Engineering / QA / Release / Delivery / Feedback
→ Integrated Review
→ Gap Report
→ Rework Loop
→ Final Delivery
→ Project Memory
```

Execution rules:

- No execution starts before an acceptance contract exists.
- DevClaw Lead controls the loop.
- Engineer Agent uses Codex CLI by default.
- QA Agent uses Deepseek TUI by default.
- Claude Code should be avoided unless explicitly allowed.
- Verification must be independent from implementation.
- The final decision is based on integrated acceptance, not per-role completion.

## 4. Agent Organization

### 4.1 DevClaw Lead

The central control Agent.

Responsibilities:

- Understand the user intent.
- Ask clarification questions.
- Generate the project brief.
- Create the acceptance contract.
- Assign tasks to specialist Agents.
- Track progress.
- Integrate outputs.
- Judge whether the combined result satisfies the acceptance contract.
- Generate gap reports.
- Route rework to the right Agent.
- Decide whether the project can be delivered.

Main outputs:

- Project Brief
- Acceptance Contract
- Task Assignments
- Integrated Review
- Gap Report
- Final Delivery Decision

### 4.2 PM Agent

The product manager Agent.

Responsibilities:

- Analyze the user requirement.
- Define user scenarios.
- Write the PRD.
- Define scope and non-goals.
- Add product-level acceptance criteria.
- Clarify priority and tradeoffs.

Main outputs:

- PRD
- User Stories
- Scope Definition
- Non-goals
- Product Acceptance Criteria

### 4.3 Designer Agent

The product design Agent.

Responsibilities:

- Design the user journey.
- Define information architecture.
- Create interaction flow.
- Create wireframes or low-fidelity UI plans.
- For Agent products, design conversation flow and user experience.
- Check whether the user can actually complete the intended task.

Main outputs:

- UX Flow
- Wireframe
- Interaction Spec
- Conversation Flow
- Usability Notes

### 4.4 Architect Agent

The technical lead Agent.

Responsibilities:

- Select the technical approach.
- Define system architecture.
- Split modules and responsibilities.
- Define data flow.
- Define API and integration boundaries.
- Identify technical risks.
- Create implementation tasks.

Main outputs:

- Architecture Spec
- Module Breakdown
- Data Flow
- API Spec
- Implementation Plan
- Technical Risk List

### 4.5 Engineer Agent

The implementation Agent.

Responsibilities:

- Use Codex CLI to implement code.
- Build products, modules, tools, scripts, or Agents.
- Integrate APIs and external services.
- Add tests where appropriate.
- Fix issues from QA and DevClaw Lead.

Main outputs:

- Source Code
- Agent Implementation
- Tool Implementation
- Tests
- Build Scripts
- Fixes

Default tool:

- Codex CLI

### 4.6 QA Agent

The verification Agent.

Responsibilities:

- Use Deepseek TUI to independently verify the implementation.
- Check the implementation against the acceptance contract.
- Run functional tests.
- Check edge cases.
- Check error handling.
- Check regression risks.
- Challenge assumptions.
- Produce structured verification reports.

Main outputs:

- Verification Report
- Bug List
- Failed Acceptance Items
- Risk Items
- Reproduction Steps

Default tool:

- Deepseek TUI

### 4.7 Release Agent

The release preparation Agent.

Responsibilities:

- Check build process.
- Check runtime configuration.
- Define deployment steps.
- Define rollback or recovery steps.
- Verify environment requirements.
- Prepare release checklist.

Main outputs:

- Release Plan
- Build Checklist
- Deploy Checklist
- Rollback Plan
- Environment Requirements

Early versions may generate release plans without performing automatic production deployment.

### 4.8 Delivery Agent

The delivery packaging Agent.

Responsibilities:

- Package the final deliverable.
- Write README.
- Write setup guide.
- Write usage guide.
- Write configuration instructions.
- Prepare demo script.
- List known limitations.
- Summarize what was delivered.

Main outputs:

- README
- Setup Guide
- Usage Guide
- Demo Script
- Delivery Checklist
- Known Limitations

### 4.9 Feedback Agent

The feedback tracking Agent.

Responsibilities:

- Collect user feedback.
- Classify feedback as bug, feature request, usability issue, performance issue, or documentation issue.
- Summarize feedback.
- Propose the next iteration.
- Feed accepted feedback back into DevClaw as a new iteration request.

Main outputs:

- Feedback Report
- Feedback Classification
- Next Iteration Proposal

### 4.10 Archivist Agent

The project memory Agent.

Responsibilities:

- Store project context.
- Store decisions.
- Store acceptance contracts.
- Store gap reports.
- Store delivery records.
- Extract reusable templates.
- Extract reusable components.
- Extract Agent specs.
- Extract lessons and failure cases.

Main outputs:

- Project Memory
- Templates
- Agent Specs
- Reusable Components
- Lessons Learned
- Failure Cases

## 5. Acceptance Contract

The acceptance contract is the center of DevClaw.

It defines what must be true before the project can be considered complete.

Example schema:

```yaml
project_id:
goal:
target_user:
background:
scope:
non_goals:
deliverables:
  - name:
    description:
    required: true

functional_acceptance:
  - id:
    description:
    priority: blocking
    verification_method:

ux_acceptance:
  - id:
    description:
    priority:
    verification_method:

technical_acceptance:
  - id:
    description:
    priority:
    verification_method:

quality_acceptance:
  - id:
    description:
    priority:
    verification_method:

release_acceptance:
  - id:
    description:
    priority:
    verification_method:

documentation_acceptance:
  - id:
    description:
    priority:
    verification_method:

blocking_criteria:
  - description:

non_blocking_criteria:
  - description:

human_review_required:
  - condition:
    reason:

stop_condition:
  - all_blocking_acceptance_passed
  - non_blocking_issues_recorded
  - final_delivery_report_generated
```

Rules:

- Blocking acceptance items must pass before delivery.
- Non-blocking issues can be recorded as known limitations.
- Human review is required for risky or ambiguous decisions.
- The stop condition controls when the DevClaw loop ends.

## 6. DevClaw Loop

The DevClaw loop is the quality control mechanism.

```text
Round 1: Agents produce initial outputs.
→ DevClaw Lead performs integrated review.
→ QA Agent performs independent verification.
→ DevClaw Lead compares result with acceptance contract.
→ If failed, DevClaw Lead generates gap report.
→ Relevant Agents rework.
→ QA verifies again.
→ DevClaw Lead reviews again.
→ Repeat until stop condition is satisfied.
```

The loop does not ask only whether each Agent completed its task. It asks:

> Can the user actually use the combined result to achieve the original goal?

## 7. Gap Report

The gap report is the contract for rework.

Example schema:

```yaml
project_id:
round:
status: fail

failed_acceptance:
  - acceptance_id:
    description:
    severity:
    evidence:

root_cause:
  - owner_agent:
    issue:
    reason:

rework_tasks:
  - agent:
    task:
    expected_output:
    verification_required:

next_verification:
  - item:
    method:

human_review_needed:
  - condition:
    reason:
```

Rules:

- Every failed acceptance item must map to at least one rework task.
- Every rework task must have an owner Agent.
- Every rework task must define expected output.
- QA must verify blocking fixes before delivery.

## 8. Final Delivery Report

The final delivery report proves that the project is ready to hand off.

Example schema:

```yaml
project_id:
version:
goal:
delivery_status: delivered

delivered_items:
  - item:
    path_or_location:
    description:

acceptance_result:
  blocking_passed:
  non_blocking_issues:

test_result:
  summary:
  commands:
  evidence:

run_instructions:
  setup:
  start:
  configure:

deployment_notes:
  environment:
  release_steps:
  rollback_steps:

known_limits:
  - description:

next_iteration:
  - suggestion:
```

## 9. Version Roadmap

### 9.1 v0.1: Single Project Loop

Goal:

Run one complete R&D project from requirement to delivery.

Capabilities:

- Natural language requirement intake.
- DevClaw Lead clarification.
- Project Brief generation.
- Acceptance Contract generation.
- PM Agent PRD generation.
- Designer Agent UX or conversation flow generation.
- Architect Agent architecture and task breakdown.
- Engineer Agent implementation through Codex CLI.
- QA Agent verification through Deepseek TUI.
- DevClaw Lead integrated review.
- Gap Report generation.
- Rework loop.
- Delivery Agent README and usage documentation.
- Archivist Agent project summary.

Out of scope:

- Multi-project parallel execution.
- Automatic production deployment.
- Automatic feedback ingestion.
- Graphical management dashboard.
- Long-running task queue.
- Complex permission system.

Success criteria:

- A user can submit one requirement.
- DevClaw generates a clear acceptance contract.
- Codex CLI can implement the main deliverable.
- Deepseek TUI can verify and find issues.
- DevClaw can generate gap reports and drive rework.
- Final deliverable is runnable, documented, and verifiable.

### 9.2 v0.2: Project Memory

Goal:

Support continuous iteration on the same product or Agent.

Capabilities:

- Project state database.
- Historical requirement records.
- Historical acceptance contracts.
- Architecture decision records.
- Historical gap reports.
- Historical delivery reports.
- Version history.
- Support for "continue the previous project".
- Support for iteration types: bugfix, feature, refactor, polish.
- Change impact analysis.

Core project memory schema:

```yaml
project_id:
name:
current_version:
goal:
decisions:
acceptance_contracts:
deliveries:
known_limits:
open_feedback:
reusable_assets:
```

Success criteria:

- A user can ask DevClaw to continue a previous project.
- DevClaw can recover project context.
- DevClaw can identify affected modules and acceptance items.
- DevClaw can complete incremental development and verification.

### 9.3 v0.3: Feedback Loop

Goal:

Turn user feedback into the next R&D iteration.

Capabilities:

- Manual feedback entry.
- Feedback classification.
- Bug reproduction requests.
- Feature request transformation.
- Usability issue transformation.
- Feedback summary.
- Iteration proposal.
- Feedback-linked acceptance contract updates.
- Fix verification.
- Delivery document updates.

Feedback schema:

```yaml
source:
user:
project_id:
feedback_type: bug | feature | usability | performance | documentation
description:
severity:
expected_behavior:
actual_behavior:
evidence:
suggested_next_action:
```

Success criteria:

- A user can submit feedback.
- DevClaw can classify the feedback.
- DevClaw can decide whether it is a bug, new feature, or improvement.
- DevClaw can start a new iteration from accepted feedback.
- The final delivery includes updated change records.

### 9.4 v0.4: Parallel R&D

Goal:

Support multiple Agents and multiple Codex CLI sessions working in parallel on one project.

Capabilities:

- Task queue.
- Subtask dependency graph.
- Multiple Engineer Agents.
- Multiple Codex CLI instances.
- Workspace isolation.
- Branch isolation.
- Conflict detection.
- Merge planning.
- Subtask-level QA.
- Integration QA.
- Failure retry.
- Progress summary.

Parallel flow:

```text
Architect Agent splits implementation into subtasks.
→ DevClaw Lead assigns subtasks.
→ Engineer Agents work in isolated workspaces.
→ QA Agent verifies subtasks.
→ DevClaw Lead integrates outputs.
→ QA Agent performs integration verification.
→ DevClaw Lead accepts or sends rework.
```

Success criteria:

- A medium-complexity project can be split into independent subtasks.
- Subtasks can run without corrupting each other.
- Integration can be verified after merge.
- Failures can be mapped to the responsible Agent and task.

### 9.5 v0.5: Release and Delivery

Goal:

Make deliverables ready for real handoff, not just runnable locally.

Capabilities:

- Build verification.
- Runtime configuration verification.
- Environment requirement detection.
- Deployment plan generation.
- Rollback plan generation.
- Release checklist.
- Delivery package generation.
- Demo script generation.
- Final acceptance verification.
- Final delivery report.

Delivery package standard:

```text
source code
README
.env.example
setup guide
usage guide
test report
verification report
release checklist
known limitations
next iteration suggestions
```

Success criteria:

- The deliverable is not just code.
- A user can follow instructions to start it.
- Release requirements are documented.
- Known limitations are documented.
- Next iteration suggestions are documented.

### 9.6 v1.0: AI R&D Factory

Goal:

Stable delivery of independent products, tools, Agents, and internal systems.

Capabilities:

- Project template library.
- Agent scaffold.
- Web app scaffold.
- CLI tool scaffold.
- API service scaffold.
- Automated test generation.
- Verification harness.
- Quality scoring.
- Reusable component extraction.
- Cross-project knowledge search.
- Semi-automatic deployment approval.
- Multi-project status view.
- Reuse of previous project decisions, templates, and components.

Success criteria:

- A user can submit a product or Agent requirement.
- DevClaw can choose a suitable template.
- DevClaw can organize the R&D loop.
- DevClaw can implement, verify, rework, and deliver.
- DevClaw can extract reusable assets.
- Similar future projects become faster and more reliable.

## 10. Implementation Order

The recommended implementation order is:

1. Implement Acceptance Contract generation.
2. Implement DevClaw Lead loop control.
3. Implement Codex CLI Engineer Agent integration.
4. Implement Deepseek TUI QA Agent integration.
5. Implement Gap Report generation and rework routing.
6. Implement delivery package generation.
7. Implement project memory.
8. Implement feedback loop.
9. Implement parallel R&D execution.
10. Implement template library, quality scoring, and factory-level reuse.

## 11. MVP Build Plan

The first milestone should produce a working v0.1.

Minimum components:

- CLI or simple local web intake.
- Project Brief generator.
- Acceptance Contract generator.
- Agent role prompt/spec definitions.
- Codex CLI execution adapter.
- Deepseek TUI verification adapter.
- Loop controller.
- Gap Report generator.
- Delivery report generator.
- Local file-based project memory.

Suggested file structure:

```text
devclaw/
  core/
    lead/
    contracts/
    loop/
    reports/
  agents/
    pm/
    designer/
    architect/
    engineer/
    qa/
    release/
    delivery/
    feedback/
    archivist/
  adapters/
    codex-cli/
    deepseek-tui/
  memory/
    projects/
    templates/
  schemas/
    acceptance-contract.yaml
    gap-report.yaml
    delivery-report.yaml
  examples/
```

### v0.1 Implementation Status

The current repository includes a runnable v0.1 implementation.

Run locally:

```bash
python3 -m devclaw run "Build a customer feedback triage Agent"
```

Run with Codex CLI and Deepseek TUI adapters:

```bash
python3 -m devclaw run "Build a customer feedback triage Agent" \
  --executor codex \
  --verifier deepseek \
  --workspace .
```

DevClaw should be run from the target project directory. The current directory is the project root; DevClaw metadata is stored under `.devclaw/`.

Run tests:

```bash
python3 -m pytest -q
```

The v0.1 implementation includes:

- Acceptance Contract generation.
- Research-first workflow before PRD, UX, architecture, and implementation.
- Agent role specifications under `.devclaw/agents/`.
- Product, UX, and technical research reports under `.devclaw/artifacts/`.
- PM, Designer, Architect, Engineer, QA, Release, Delivery, and Archivist Agent outputs.
- DevClaw Lead loop control.
- Gap Report generation and rework routing.
- Local deterministic adapters for stable testing.
- Codex CLI execution adapter.
- Deepseek TUI verification adapter.
- CLI end-to-end flow.

## 12. Non-goals

DevClaw is not:

- A full company operating system.
- A sales automation platform.
- A finance automation platform.
- A legal automation platform.
- An HR management platform.
- A generic chatbot.
- A simple task manager.

DevClaw is:

- An AI-native product R&D delivery system.
- An acceptance-driven Agent team.
- A loop-based product implementation and verification engine.
- A system for delivering runnable products, tools, modules, and Agents.

## 13. Summary

DevClaw is an acceptance-driven AI R&D factory.

Its key insight is that Agent roles are not enough. The system must continuously evaluate whether all role outputs combine into a result that satisfies the original user requirement.

The acceptance contract defines the target. The DevClaw loop drives execution and rework. Codex CLI implements. Deepseek TUI verifies. DevClaw Lead controls the loop until the result is ready to deliver.
