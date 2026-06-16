from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class FeedbackItem:
    id: int
    feedback_type: str
    description: str
    severity: str
    created_at: str

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


def add_feedback(project_root: Path, description: str) -> FeedbackItem:
    feedback_dir = project_root / ".devclaw" / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    next_id = len(list(feedback_dir.glob("*.json"))) + 1
    item = FeedbackItem(
        id=next_id,
        feedback_type=_classify(description),
        description=description,
        severity=_severity(description),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    (feedback_dir / f"{next_id:04d}.json").write_text(
        json.dumps(item.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return item


def list_feedback(project_root: Path) -> list[FeedbackItem]:
    feedback_dir = project_root / ".devclaw" / "feedback"
    if not feedback_dir.exists():
        return []
    items: list[FeedbackItem] = []
    for path in sorted(feedback_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        items.append(
            FeedbackItem(
                id=int(data["id"]),
                feedback_type=data["feedback_type"],
                description=data["description"],
                severity=data["severity"],
                created_at=data["created_at"],
            )
        )
    return items


def get_feedback(project_root: Path, feedback_id: int) -> FeedbackItem | None:
    for item in list_feedback(project_root):
        if item.id == feedback_id:
            return item
    return None


def _classify(description: str) -> str:
    lowered = description.lower()
    if "bug" in lowered or "fail" in lowered or "crash" in lowered or "broken" in lowered:
        return "bug"
    if "feature" in lowered or "add" in lowered or "support" in lowered:
        return "feature"
    if "slow" in lowered or "performance" in lowered:
        return "performance"
    if "doc" in lowered or "readme" in lowered:
        return "documentation"
    return "usability"


def _severity(description: str) -> str:
    lowered = description.lower()
    if "crash" in lowered or "data loss" in lowered or "security" in lowered:
        return "high"
    if "bug" in lowered or "fail" in lowered:
        return "medium"
    return "low"
