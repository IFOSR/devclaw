from __future__ import annotations

from pathlib import Path


def create_risk_report(project_root: Path) -> Path:
    path = project_root / ".devclaw" / "reports" / "risk-report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            "# Risk Review",
            "",
            "## Human Approval Required",
            "- Production deployment",
            "- Paid API usage",
            "- Irreversible data changes",
            "- Credential or secret handling",
            "",
            "## Current v0.x Guardrails",
            "- DevClaw stores metadata under .devclaw/.",
            "- Delivery docs should not overwrite project README.",
            "- Real Codex/Deepseek execution is explicit via adapter flags.",
        ]
    )
    path.write_text(content, encoding="utf-8")
    return path
