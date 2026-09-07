"""Opt-in integration tests against real harness CLIs.

These tests are skipped by default. Enable with:

    METACODING_REAL_E2E=1 python3 -m pytest tests/metacoding/test_real_integrations.py -q

Optional knobs:
    METACODING_PLANNER_MODEL / METACODING_CODER_MODEL / METACODING_TESTER_MODEL
    METACODING_IDLE_TIMEOUT (seconds, default 600)

``test_real_full_loop`` exercises the complete
plan -> code -> test -> review -> deliver lifecycle with real Codex and Pi.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from metacoding.cli import EXIT_OK
from metacoding.config import HarnessConfig, load_config
from metacoding.harnesses.base import HarnessContext
from metacoding.harnesses.codex_planner import CodexPlanner
from metacoding.harnesses.codex_tester import CodexTester
from metacoding.harnesses.pi_coder import PiCoder
from metacoding.models import now_utc, validate_planner_plan
from metacoding.service import MetaCodingService

REAL_E2E = os.environ.get("METACODING_REAL_E2E") == "1"
IDLE_TIMEOUT = float(os.environ.get("METACODING_IDLE_TIMEOUT", "600"))
HAVE_CODEX = bool(shutil.which("codex"))
HAVE_PI = bool(shutil.which("pi"))

pytestmark = pytest.mark.skipif(not REAL_E2E, reason="real harness tests are opt-in")

REQUIREMENT = "Create a file named hello.txt in the project root containing exactly: hi"

PLAN_PAYLOAD = {
    "goal": "Create hello.txt with the content 'hi'",
    "scope": ["hello.txt"],
    "non_goals": ["anything else"],
    "architecture": {
        "approach": "write the single file directly",
        "modules": ["hello.txt"],
        "data_flow": ["operator -> metacoding -> file"],
        "risks": [],
    },
    "acceptance_criteria": [
        {
            "id": "F-001",
            "description": "hello.txt exists and contains exactly 'hi'",
            "priority": "blocking",
            "verification_method": "read hello.txt",
        }
    ],
    "coding_tasks": [
        {
            "id": "TASK-001",
            "description": "create hello.txt with content 'hi'",
            "expected_files": ["hello.txt"],
            "required_tests": [],
            "done_when": "hello.txt contains exactly 'hi'",
        }
    ],
    "change_policy": {
        "allowed_paths": ["hello.txt"],
        "protected_paths": [],
        "forbidden_actions": [],
    },
}


def context(tmp_path: Path, stage_dir: Path) -> HarnessContext:
    stage_dir.mkdir(parents=True, exist_ok=True)
    return HarnessContext(
        requirement=REQUIREMENT,
        run_id="real-run",
        round_number=1,
        attempt=1,
        idle_timeout_seconds=IDLE_TIMEOUT,
        project_root=tmp_path,
        docs_dir=tmp_path / "docs" / "metacoding",
        report_dir=stage_dir,
        plan=validate_planner_plan(PLAN_PAYLOAD),
    )


@pytest.mark.skipif(not HAVE_CODEX, reason="codex CLI not installed")
def test_real_codex_planner_produces_valid_plan(tmp_path: Path) -> None:
    model = os.environ.get("METACODING_PLANNER_MODEL", "")
    planner = CodexPlanner(
        HarnessConfig("planner", "codex", "codex", model, []), tmp_path
    )
    ctx = context(tmp_path, tmp_path / ".metacoding" / "real" / "plan")
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    plan = planner.plan(ctx)
    assert plan.goal
    assert plan.acceptance_criteria


@pytest.mark.skipif(not HAVE_PI, reason="pi CLI not installed")
def test_real_pi_coder_implements_plan(tmp_path: Path) -> None:
    model = os.environ.get("METACODING_CODER_MODEL", "")
    coder = PiCoder(HarnessConfig("coder", "pi", "pi", model, []), tmp_path)
    ctx = context(tmp_path, tmp_path / ".metacoding" / "real" / "code")
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    result = coder.code(ctx)
    assert result.status == "completed"
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8").strip() == "hi"


@pytest.mark.skipif(not HAVE_CODEX, reason="codex CLI not installed")
def test_real_codex_tester_reports_on_implementation(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hi\n", encoding="utf-8")
    # The tester prompt points at the contract documents: provide them so a
    # real run has the same context the orchestrator would render.
    docs = tmp_path / "docs" / "metacoding"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "PRD.md").write_text(
        "# PRD\n\nCreate hello.txt containing exactly: hi\n", encoding="utf-8"
    )
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n\nsingle file\n", encoding="utf-8")
    (docs / "IMPLEMENTATION_PLAN.md").write_text(
        "# Implementation Plan\n\n- TASK-001: create hello.txt\n", encoding="utf-8"
    )
    (docs / "ACCEPTANCE.md").write_text(
        "# Acceptance Criteria\n\n- F-001: hello.txt contains exactly hi\n",
        encoding="utf-8",
    )
    transcripts: list[tuple[str, object]] = []

    def sink(stage: str, result) -> None:
        transcripts.append((stage, result))

    model = os.environ.get("METACODING_TESTER_MODEL", "")
    tester = CodexTester(
        HarnessConfig("tester", "codex", "codex", model, []), tmp_path
    )
    ctx = context(tmp_path, tmp_path / ".metacoding" / "real" / "test")
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    ctx.test_commands = []
    ctx.transcript_sink = sink
    report = tester.test(ctx)
    assert report.status in ("pass", "fail")
    assert report.acceptance_results
    # transcripts (incl. stderr on failure) are preserved for diagnosis
    assert transcripts and transcripts[0][1].stderr is not None


@pytest.mark.skipif(not (HAVE_CODEX and HAVE_PI), reason="codex and pi CLIs required")
def test_real_full_loop(tmp_path: Path) -> None:
    """The complete plan -> code -> test -> review lifecycle with real harnesses."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=project, check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "T"], check=True)
    (project / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-q", "-m", "init"], check=True)

    config_lines = [
        "[limits]",
        "max_rounds = 3",
        "idle_timeout_seconds = 900",
        "",
    ]
    for name, model_env in (
        ("planner", "METACODING_PLANNER_MODEL"),
        ("coder", "METACODING_CODER_MODEL"),
        ("tester", "METACODING_TESTER_MODEL"),
    ):
        model = os.environ.get(model_env, "")
        config_lines += [
            f"[harness.{name}]",
            f'provider = "{"codex" if name != "coder" else "pi"}"',
            f'command = "{"codex" if name != "coder" else "pi"}"',
            f'model = "{model}"',
            "extra_args = []",
            "",
        ]
    config_lines += [
        "[policy]",
        "allow_network = false",
        "allow_destructive_commands = false",
        "tester_can_modify_source = false",
        "",
        "[github]",
        "enabled = true",
        "auto_push = false",
        "auto_create_pr = false",
        "",
    ]
    (project / ".metacoding").mkdir()
    (project / ".metacoding" / "config.toml").write_text(
        "\n".join(config_lines), encoding="utf-8"
    )

    config = load_config(project)
    assert config.harness["coder"].provider == "pi"

    service = MetaCodingService(project_root=project)
    outcome = service.run(REQUIREMENT)
    assert outcome.exit_code == EXIT_OK, outcome.message
    assert (project / "hello.txt").read_text(encoding="utf-8").strip() == "hi"

    run_dir = project / ".metacoding" / "runs" / outcome.run_id
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["outcome"] == "delivered"
    # the tester report must reference the real acceptance criterion
    tester_report = json.loads(
        (run_dir / "rounds" / "round-001" / "tester-report.json").read_text("utf-8")
    )
    assert tester_report["acceptance_results"]
    # delivery happened on a dedicated branch containing only owned files
    delivery = json.loads((run_dir / "git" / "delivery.json").read_text("utf-8"))
    assert delivery["branch"].startswith("metacoding/")
    assert "hello.txt" in delivery["committed_files"]
