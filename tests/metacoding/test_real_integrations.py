"""Opt-in integration tests against real harness CLIs.

These tests are skipped by default. Enable with:

    METACODING_REAL_E2E=1 python3 -m pytest tests/metacoding/test_real_integrations.py -q

Optional knobs:
    METACODING_PLANNER_MODEL / METACODING_CODER_MODEL / METACODING_TESTER_MODEL
    METACODING_IDLE_TIMEOUT (seconds, default 600)
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from metacoding.config import HarnessConfig
from metacoding.harnesses.base import HarnessContext
from metacoding.harnesses.codex_planner import CodexPlanner
from metacoding.harnesses.codex_tester import CodexTester
from metacoding.harnesses.pi_coder import PiCoder
from metacoding.models import now_utc, validate_planner_plan

REAL_E2E = os.environ.get("METACODING_REAL_E2E") == "1"
IDLE_TIMEOUT = float(os.environ.get("METACODING_IDLE_TIMEOUT", "600"))

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

pytestmark = [
    pytest.mark.skipif(not REAL_E2E, reason="real harness tests are opt-in"),
    pytest.mark.skipif(not shutil.which("codex"), reason="codex CLI not installed"),
]


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


def test_real_pi_coder_implements_plan(tmp_path: Path) -> None:
    pytest.importorskip("shutil")
    if not shutil.which("pi"):
        pytest.skip("pi CLI not installed")
    model = os.environ.get("METACODING_CODER_MODEL", "")
    coder = PiCoder(HarnessConfig("coder", "pi", "pi", model, []), tmp_path)
    ctx = context(tmp_path, tmp_path / ".metacoding" / "real" / "code")
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    result = coder.code(ctx)
    assert result.status == "completed"
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8").strip() == "hi"


def test_real_codex_tester_reports_on_implementation(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hi\n", encoding="utf-8")
    model = os.environ.get("METACODING_TESTER_MODEL", "")
    tester = CodexTester(
        HarnessConfig("tester", "codex", "codex", model, []), tmp_path
    )
    ctx = context(tmp_path, tmp_path / ".metacoding" / "real" / "test")
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    ctx.test_commands = []
    report = tester.test(ctx)
    assert report.status in ("pass", "fail")
    assert report.acceptance_results
