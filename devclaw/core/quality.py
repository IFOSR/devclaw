from __future__ import annotations

import json
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from devclaw.adapters.tool_runner import run_tool_with_idle_monitor
from devclaw.core.context import scan_project_context


@dataclass(frozen=True)
class QualityReport:
    status: str
    checks: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_quality_checks(project_root: Path) -> QualityReport:
    context = scan_project_context(project_root)
    checks: list[dict[str, Any]] = []
    commands = [
        *context.test_commands,
        *[
            f"python3 {path.as_posix()}"
            for path in sorted((project_root / ".devclaw" / "checks").glob("*.py"))
        ],
    ]
    for command in commands:
        result = run_tool_with_idle_monitor(
            shlex.split(command),
            cwd=project_root,
            idle_timeout_seconds=900,
        )
        checks.append(
            {
                "type": "test",
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
                "status": "pass" if result.returncode == 0 else "fail",
            }
        )
    status = "pass" if checks and all(item["status"] == "pass" for item in checks) else "fail"
    if not checks:
        status = "no_checks"
    report = QualityReport(status=status, checks=checks)
    report_path = project_root / ".devclaw" / "reports" / "quality-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return report
