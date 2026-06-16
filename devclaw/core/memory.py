from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from devclaw.core.models import AcceptanceContract, FinalDeliveryReport, ProjectBrief


@dataclass
class ProjectMemory:
    project_root: str
    request_history: list[dict[str, Any]] = field(default_factory=list)
    acceptance_history: list[dict[str, Any]] = field(default_factory=list)
    delivery_history: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_memory(project_root: Path) -> ProjectMemory:
    path = _memory_path(project_root)
    if not path.exists():
        return ProjectMemory(project_root=str(project_root))
    data = json.loads(path.read_text(encoding="utf-8"))
    return ProjectMemory(
        project_root=data.get("project_root", str(project_root)),
        request_history=data.get("request_history", []),
        acceptance_history=data.get("acceptance_history", []),
        delivery_history=data.get("delivery_history", []),
        decisions=data.get("decisions", []),
    )


def save_memory(project_root: Path, memory: ProjectMemory) -> None:
    path = _memory_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def update_memory_after_run(
    project_root: Path,
    brief: ProjectBrief,
    contract: AcceptanceContract,
    final_report: FinalDeliveryReport,
) -> ProjectMemory:
    memory = load_memory(project_root)
    timestamp = datetime.now(timezone.utc).isoformat()
    memory.request_history.append(
        {
            "timestamp": timestamp,
            "project_id": brief.project_id,
            "intent": brief.intent,
            "goal": brief.goal,
        }
    )
    memory.acceptance_history.append(
        {
            "timestamp": timestamp,
            "project_id": contract.project_id,
            "blocking_items": [item.id for item in contract.blocking_items()],
        }
    )
    memory.delivery_history.append(
        {
            "timestamp": timestamp,
            "project_id": final_report.project_id,
            "status": final_report.delivery_status,
            "goal": final_report.goal,
        }
    )
    memory.decisions.append(
        {
            "timestamp": timestamp,
            "project_id": brief.project_id,
            "decision": "Use project-local DevClaw metadata under .devclaw/.",
            "reason": "Keep all user interactions scoped to the current project.",
        }
    )
    save_memory(project_root, memory)
    return memory


def _memory_path(project_root: Path) -> Path:
    return project_root / ".devclaw" / "memory" / "project.json"
