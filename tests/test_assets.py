from pathlib import Path
import os
import subprocess
import sys

from devclaw.core.assets import extract_reusable_assets, find_reusable_assets


def test_extract_reusable_assets_stores_asset_index_and_content(tmp_path: Path):
    (tmp_path / "agent.py").write_text("print('asset ok')\n", encoding="utf-8")

    report = extract_reusable_assets(tmp_path, "Build reusable feedback agent")

    assert report.status == "extracted"
    assert report.assets
    assert (tmp_path / ".devclaw" / "assets" / "index.json").exists()
    assert (tmp_path / ".devclaw" / "assets" / report.assets[0]["path"]).exists()


def test_find_reusable_assets_returns_similar_prior_asset(tmp_path: Path):
    (tmp_path / "feedback_agent.py").write_text("print('feedback triage')\n", encoding="utf-8")
    extract_reusable_assets(tmp_path, "Build feedback triage agent")

    results = find_reusable_assets(tmp_path, "feedback triage")

    assert results
    assert "feedback" in results[0]["intent"].lower()


def test_assets_cli_extract_and_search_are_user_usable(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    (tmp_path / "feedback_agent.py").write_text("print('feedback triage')\n", encoding="utf-8")

    extract = subprocess.run(
        [sys.executable, "-m", "devclaw", "/assets-extract", "Build feedback triage agent"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert extract.returncode == 0, extract.stderr + extract.stdout
    assert "Assets status: extracted" in extract.stdout

    search = subprocess.run(
        [sys.executable, "-m", "devclaw", "/assets-search", "feedback triage"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert search.returncode == 0, search.stderr + search.stdout
    assert "Build feedback triage agent" in search.stdout
