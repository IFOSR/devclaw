# DevClaw Real Completion TODO

## Completion Definition

A TODO is complete only when all of the following are true:

- Implemented in production code.
- Covered by automated tests.
- Verified by a real end-to-end run.
- Usable by a user from the terminal.
- No mock, fake, or deterministic local substitute is used for the real-completion proof.
- Executor Agents are called non-interactively.
- Executor Agents are called with full authorization flags so the user is not repeatedly prompted.
- Artifacts, transcripts, reports, and evidence are persisted under `.devclaw/`.

Local deterministic tests may remain for fast regression, but they do not count as real completion.

## Real Executor Policy

Codex execution must use non-interactive full-authorization mode:

```bash
codex exec -C <project> --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox <prompt>
```

Deepseek verification must use non-interactive full-authorization mode:

```bash
deepseek exec --approval-policy never --sandbox-mode danger-full-access <prompt>
```

No interactive confirmation loop is allowed during real executor runs.

## Active TODO

## Removal Rule

When a TODO meets the completion definition, delete it from this file in the same change that includes its tests and evidence.
