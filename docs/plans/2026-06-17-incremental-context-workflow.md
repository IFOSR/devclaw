# Incremental Context Workflow Implementation Plan

**Goal:** Add cross-session context packs and workflow routing so small follow-up changes reuse prior stage outputs instead of rerunning the full R&D workflow.

**Architecture:** Introduce a context pack builder that reads project memory, session manifests, and recent stage indexes. Add a workflow router that classifies requests into full or incremental modes. DevClawLead will use the route to decide which role assignments run and will write reuse notes for skipped stages.

**Tech Stack:** Python, pytest, Markdown artifacts under `.devclaw/`.

---

## Tasks

1. Add failing tests for context pack generation from prior sessions and stage documents.
2. Add failing tests for targeted-change routing that skips early research/product/design/architecture roles while writing reuse notes.
3. Implement `devclaw/core/context_pack.py`.
4. Implement `devclaw/core/workflow_router.py`.
5. Integrate routing and context pack generation into `DevClawLead`.
6. Update CLI progress output and README.
7. Run targeted and deterministic test suites.
