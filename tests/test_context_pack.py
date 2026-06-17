import json
from pathlib import Path

from devclaw.core.context_pack import build_context_pack


def test_context_pack_reads_recent_sessions_memory_and_stage_indexes(tmp_path: Path):
    memory_dir = tmp_path / ".devclaw" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "project.json").write_text(
        json.dumps(
            {
                "project_root": str(tmp_path),
                "request_history": [
                    {
                        "timestamp": "2026-06-17T01:00:00+00:00",
                        "project_id": "project-alpha",
                        "intent": "Build initial workflow",
                        "goal": "Initial workflow",
                    }
                ],
                "acceptance_history": [],
                "delivery_history": [
                    {
                        "timestamp": "2026-06-17T01:10:00+00:00",
                        "project_id": "project-alpha",
                        "status": "delivered",
                        "goal": "Initial workflow",
                    }
                ],
                "decisions": [
                    {
                        "timestamp": "2026-06-17T01:11:00+00:00",
                        "project_id": "project-alpha",
                        "decision": "Default workflow is sequential.",
                        "reason": "Avoid user confusion.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    session_dir = tmp_path / ".devclaw" / "sessions" / "20260617010101000000"
    session_dir.mkdir(parents=True)
    (session_dir / "manifest.json").write_text(
        json.dumps(
            {
                "session_id": "20260617010101000000",
                "intent": "Build initial workflow",
                "changed_files": ["devclaw/cli.py"],
                "completed_at": "2026-06-17T01:12:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    stage_dir = tmp_path / ".devclaw" / "stages" / "project-alpha" / "20260617010101000000"
    stage_dir.mkdir(parents=True)
    (stage_dir / "index.md").write_text(
        "# DevClaw Stage Review Index\n\n- [workflow-plan.md](workflow-plan.md)\n",
        encoding="utf-8",
    )
    (stage_dir / "09-final").mkdir()
    (stage_dir / "09-final" / "final-delivery-report.md").write_text(
        "# Final Delivery Report\n\n## Delivery Status\n\ndelivered\n",
        encoding="utf-8",
    )

    pack = build_context_pack(tmp_path, "Refine the workflow display", max_sessions=3)

    assert pack.path == tmp_path / ".devclaw" / "context" / "current-context-pack.md"
    content = pack.markdown
    assert "Refine the workflow display" in content
    assert "Build initial workflow" in content
    assert "devclaw/cli.py" in content
    assert "Default workflow is sequential." in content
    assert ".devclaw/stages/project-alpha/20260617010101000000/index.md" in content
    assert pack.path.exists()
