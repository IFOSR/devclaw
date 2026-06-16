from pathlib import Path
import subprocess

from devclaw.core.sessions import SessionManager


def test_session_manager_records_changed_files_and_restores_snapshot(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text("# Original\n", encoding="utf-8")
    manager = SessionManager(tmp_path)

    session = manager.begin("Add feature")
    readme.write_text("# Changed\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("new\n", encoding="utf-8")
    completed = manager.complete(session)

    assert "README.md" in completed.changed_files
    assert "new.txt" in completed.changed_files
    assert completed.manifest_path.exists()

    manager.restore(completed.session_id)

    assert readme.read_text(encoding="utf-8") == "# Original\n"
    assert not (tmp_path / "new.txt").exists()


def test_session_manager_appends_transcripts(tmp_path: Path):
    manager = SessionManager(tmp_path)
    session = manager.begin("Run tool")

    path = manager.write_transcript(session.session_id, "codex", "hello")

    assert path.exists()
    assert "hello" in path.read_text()


def test_session_manager_records_git_base_revision_and_diff(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "devclaw@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "DevClaw"], cwd=tmp_path, check=True)
    readme = tmp_path / "README.md"
    readme.write_text("# Original\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    base_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    manager = SessionManager(tmp_path)
    session = manager.begin("Add feature")
    readme.write_text("# Changed\n", encoding="utf-8")
    (tmp_path / "feature.txt").write_text("feature\n", encoding="utf-8")
    completed = manager.complete(session)

    manifest = completed.manifest_path.read_text(encoding="utf-8")
    assert f'"base_revision": "{base_revision}"' in manifest
    assert '"git_isolation": "snapshot"' in manifest
    assert '"diff_stat":' in manifest
    assert '"diff":' in manifest
    assert "README.md" in manifest
    assert "feature.txt" in manifest
