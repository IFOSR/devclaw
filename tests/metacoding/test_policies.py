"""Deterministic policy gates, fingerprints, and stop conditions."""

from __future__ import annotations

from metacoding.models import validate_planner_plan, validate_tester_report
from metacoding.policies import (
    blocking_acceptance_gate,
    contamination_gate,
    deterministic_checks_gate,
    evaluate_acceptance,
    evidence_gate,
    failure_fingerprint,
    plan_gate,
    protected_path_gate,
    repeated_failure_reached,
    scope_gate,
    severity_gate,
)

PLAN = validate_planner_plan(
    {
        "goal": "audit log",
        "scope": [],
        "non_goals": [],
        "architecture": {
            "approach": "hook",
            "modules": [],
            "data_flow": [],
            "risks": [],
        },
        "acceptance_criteria": [
            {
                "id": "F-001",
                "description": "entries appended",
                "priority": "blocking",
                "verification_method": "tests",
            },
            {
                "id": "F-002",
                "description": "nice docs",
                "priority": "non_blocking",
                "verification_method": "read docs",
            },
        ],
        "coding_tasks": [
            {
                "id": "TASK-001",
                "description": "implement",
                "expected_files": ["src/audit.py"],
                "required_tests": [],
                "done_when": "tests pass",
            }
        ],
        "change_policy": {
            "allowed_paths": ["src/**", "tests/**", "docs/metacoding"],
            "protected_paths": ["docs/metacoding/PRD.md", ".metacoding/config.toml"],
            "forbidden_actions": ["force-push"],
        },
    }
)


def make_report(
    *,
    status: str = "pass",
    failing: list[str] | None = None,
    findings: list[dict] | None = None,
    command_exit: int = 0,
) -> object:
    failing = failing or []
    return validate_tester_report(
        {
            "status": status,
            "test_commands": [
                {"command": "python3 -m pytest -q", "exit_code": command_exit, "summary": "run"}
            ],
            "acceptance_results": [
                {
                    "id": "F-001",
                    "status": "fail" if "F-001" in failing else "pass",
                    "impact": "high",
                    "evidence": ["tests/test_audit.py"],
                },
                {
                    "id": "F-002",
                    "status": "fail" if "F-002" in failing else "pass",
                    "impact": "low",
                    "evidence": ["docs"],
                },
            ],
            "findings": findings or [],
            "prd_drift": [],
            "regression_risks": [],
            "missing_tests": [],
            "changed_files": [],
        }
    )


def finding(severity: str = "P1", title: str = "crash on empty input") -> dict:
    return {
        "id": f"BUG-{severity}",
        "type": "bug",
        "severity": severity,
        "title": title,
        "impact": "high",
        "reproduction": ["run x"],
        "evidence": ["traceback"],
        "recommended_fix": "guard",
    }


def test_plan_gate_requires_valid_plan() -> None:
    assert plan_gate(PLAN).passed
    assert not plan_gate(None).passed


def test_scope_gate_matches_allowed_patterns() -> None:
    policy = PLAN.change_policy
    assert scope_gate(["src/admin/audit.py", "tests/test_audit.py"], policy).passed
    assert scope_gate(["docs/metacoding/TEST_REPORT.md"], policy).passed  # prefix match
    result = scope_gate(["src/ok.py", "evil/pwned.py"], policy)
    assert not result.passed
    assert "evil/pwned.py" in result.details


def test_protected_path_gate_blocks_modifications() -> None:
    policy = PLAN.change_policy
    assert protected_path_gate(["src/app.py"], policy).passed
    result = protected_path_gate(["docs/metacoding/PRD.md"], policy)
    assert not result.passed
    assert "docs/metacoding/PRD.md" in result.details


def test_severity_gate_blocks_p0_and_p1() -> None:
    assert severity_gate(make_report()).passed
    assert not severity_gate(make_report(findings=[finding("P0")])).passed
    assert not severity_gate(make_report(findings=[finding("P1")])).passed
    assert severity_gate(make_report(findings=[finding("P2")])).passed


def test_deterministic_checks_gate_requires_passing_commands() -> None:
    assert deterministic_checks_gate(make_report()).passed
    assert not deterministic_checks_gate(make_report(command_exit=1)).passed


def test_blocking_acceptance_gate() -> None:
    assert blocking_acceptance_gate(PLAN, make_report()).passed
    assert not blocking_acceptance_gate(PLAN, make_report(failing=["F-001"])).passed
    assert blocking_acceptance_gate(PLAN, make_report(failing=["F-002"])).passed


def test_evidence_gate_requires_blocking_results() -> None:
    report = make_report()
    assert evidence_gate(PLAN, report).passed
    trimmed = validate_tester_report(
        {
            "status": "pass",
            "test_commands": [
                {"command": "python3 -m pytest -q", "exit_code": 0, "summary": "run"}
            ],
            "acceptance_results": [
                {
                    "id": "F-002",
                    "status": "pass",
                    "impact": "low",
                    "evidence": ["docs"],
                }
            ],
            "findings": [],
            "prd_drift": [],
            "regression_risks": [],
            "missing_tests": [],
            "changed_files": [],
        }
    )
    result = evidence_gate(PLAN, trimmed)
    assert not result.passed
    assert "F-001" in result.details


def test_contamination_gate_detects_tester_edits() -> None:
    pre = {"src/app.py", ".metacoding/runs/run-1/rounds/round-001/round.json"}
    post_ok = pre | {".metacoding/runs/run-1/rounds/round-001/tester-report.json",
                     "docs/metacoding/TEST_REPORT.md"}
    assert contamination_gate(pre, post_ok, tester_can_modify_source=False).passed

    post_bad = pre | {"src/app.py.edited"}
    result = contamination_gate({"src/app.py"}, post_bad, tester_can_modify_source=False)
    assert not result.passed
    assert "src/app.py.edited" in result.details
    assert contamination_gate({"src/app.py"}, post_bad, tester_can_modify_source=True).passed


def test_evaluate_acceptance_combines_all_gates() -> None:
    good = evaluate_acceptance(PLAN, make_report(), ["src/app.py"])
    assert all(gate.passed for gate in good)

    bad_report = make_report(failing=["F-001"], findings=[finding("P1")], command_exit=1)
    gates = evaluate_acceptance(PLAN, bad_report, ["evil/out.py"])
    names = {gate.name: gate.passed for gate in gates}
    assert names["severity"] is False
    assert names["deterministic_checks"] is False
    assert names["blocking_acceptance"] is False
    assert names["scope"] is False


def test_failure_fingerprint_is_stable_and_normalized() -> None:
    one = failure_fingerprint(make_report(failing=["F-001"], findings=[finding("P1")]))
    same = failure_fingerprint(make_report(failing=["F-001"], findings=[finding("P1")]))
    assert one == same

    title_noise = failure_fingerprint(
        make_report(findings=[finding("P1", title="Crash   On Empty Input")])
    )
    assert title_noise == failure_fingerprint(
        make_report(findings=[finding("P1", title="crash on empty input")])
    )
    different = failure_fingerprint(make_report(findings=[finding("P2")]))
    assert one != different
    passing = failure_fingerprint(make_report())
    assert passing == ""


def test_repeated_failure_detection_uses_consecutive_rounds() -> None:
    fingerprint = "abc"
    assert repeated_failure_reached([], fingerprint, limit=2) is False
    assert repeated_failure_reached([fingerprint], fingerprint, limit=2) is False
    assert repeated_failure_reached([fingerprint, fingerprint], fingerprint, limit=2) is True
    assert repeated_failure_reached(["x", fingerprint, fingerprint], fingerprint, limit=2) is True
    assert repeated_failure_reached([fingerprint, "other"], fingerprint, limit=2) is False


# --- host-fixed protections -------------------------------------------------------


def test_host_protected_paths_apply_even_when_planner_allows_everything() -> None:
    from metacoding.policies import is_host_protected

    permissive = validate_planner_plan(
        {
            "goal": "g",
            "scope": [],
            "non_goals": [],
            "architecture": {"approach": "a", "modules": [], "data_flow": [], "risks": []},
            "acceptance_criteria": [
                {
                    "id": "F-001",
                    "description": "d",
                    "priority": "blocking",
                    "verification_method": "v",
                }
            ],
            "coding_tasks": [
                {
                    "id": "TASK-001",
                    "description": "t",
                    "expected_files": [],
                    "required_tests": [],
                    "done_when": "w",
                }
            ],
            "change_policy": {
                "allowed_paths": ["**"],
                "protected_paths": [],
                "forbidden_actions": [],
            },
        }
    )
    hostile_changes = [".git/config", ".metacoding/config.toml", ".metacoding/state.json"]
    assert all(is_host_protected(path) for path in hostile_changes)
    assert not scope_gate(hostile_changes, permissive.change_policy).passed
    assert not protected_path_gate(hostile_changes, permissive.change_policy).passed
    # ordinary product files remain deliverable under "**"
    assert scope_gate(["src/app.py"], permissive.change_policy).passed


def test_deterministic_gate_uses_host_executed_results() -> None:
    lying_report = make_report()  # tester claims exit 0
    failed_host = [{"command": "python3 -m pytest -q", "exit_code": 1, "timed_out": False}]
    result = deterministic_checks_gate(lying_report, host_checks=failed_host)
    assert not result.passed
    assert any("host" in detail for detail in result.details)
    assert any("inconsistent" in detail.lower() or "host" in detail.lower() for detail in result.details)

    passing_host = [{"command": "python3 -m pytest -q", "exit_code": 0, "timed_out": False}]
    assert deterministic_checks_gate(lying_report, host_checks=passing_host).passed
    assert deterministic_checks_gate(lying_report, host_checks=[]).passed


def test_contamination_gate_honors_narrow_write_scope() -> None:
    pre = {"src/app.py": "a"}
    post = {
        "src/app.py": "a",
        ".metacoding/runs/run-9/rounds/round-001/tester-report.json": "new",
        ".metacoding/other-run/hack.json": "new",
    }
    narrow = (".metacoding/runs/run-9/",)
    result = contamination_gate(
        pre, post, tester_can_modify_source=False, allowed_prefixes=narrow
    )
    assert not result.passed
    assert result.details == (".metacoding/other-run/hack.json",)
    clean = contamination_gate(
        post,
        post,
        tester_can_modify_source=False,
        allowed_prefixes=narrow,
    )
    assert clean.passed
    allowed_new = contamination_gate(
        {k: v for k, v in post.items() if "tester-report" not in k},
        post,
        tester_can_modify_source=False,
        allowed_prefixes=narrow,
    )
    assert allowed_new.passed
