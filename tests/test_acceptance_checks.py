import json
from pathlib import Path

from devclaw.core.checks import generate_acceptance_checks
from devclaw.core.contracts import create_acceptance_contract, create_project_brief
from devclaw.core.quality import run_quality_checks


def test_generate_acceptance_checks_from_cli_print_goal(tmp_path: Path):
    brief = create_project_brief(
        "Create hello.py so running python3 hello.py prints exactly: acceptance ok"
    )
    contract = create_acceptance_contract(brief)

    path = generate_acceptance_checks(tmp_path, brief, contract)

    assert path == tmp_path / ".devclaw" / "checks" / "acceptance_checks.py"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "hello.py" in content
    assert "acceptance ok" in content


def test_quality_harness_runs_generated_acceptance_checks_and_blocks_failure(tmp_path: Path):
    brief = create_project_brief(
        "Create hello.py so running python3 hello.py prints exactly: acceptance ok"
    )
    contract = create_acceptance_contract(brief)
    generate_acceptance_checks(tmp_path, brief, contract)

    failed = run_quality_checks(tmp_path)

    assert failed.status == "fail"
    assert any(".devclaw/checks/acceptance_checks.py" in check["command"] for check in failed.checks)

    (tmp_path / "hello.py").write_text("print('acceptance ok')\n", encoding="utf-8")
    passed = run_quality_checks(tmp_path)

    assert passed.status == "pass"
    report = json.loads((tmp_path / ".devclaw" / "reports" / "quality-report.json").read_text())
    assert report["status"] == "pass"
