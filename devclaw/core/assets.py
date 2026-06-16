from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class AssetReport:
    status: str
    assets: list[dict[str, str]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_reusable_assets(project_root: Path, intent: str) -> AssetReport:
    assets_dir = project_root / ".devclaw" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    index_path = assets_dir / "index.json"
    index = _load_index(index_path)
    extracted: list[dict[str, str]] = []

    for source in _candidate_files(project_root):
        asset_id = _slug(f"{intent}-{source.name}")
        asset_path = assets_dir / f"{asset_id}.md"
        asset = {
            "id": asset_id,
            "intent": intent,
            "source": str(source.relative_to(project_root)),
            "path": asset_path.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        asset_path.write_text(
            "\n".join(
                [
                    f"# Reusable Asset: {intent}",
                    "",
                    f"Source: {asset['source']}",
                    "",
                    "```",
                    source.read_text(encoding="utf-8", errors="ignore")[:12000],
                    "```",
                ]
            ),
            encoding="utf-8",
        )
        extracted.append(asset)

    existing = {item["id"]: item for item in index}
    for item in extracted:
        existing[item["id"]] = item
    index_path.write_text(
        json.dumps(list(existing.values()), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    report = AssetReport("extracted" if extracted else "no_assets", extracted)
    report_path = project_root / ".devclaw" / "reports" / "assets-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def find_reusable_assets(project_root: Path, query: str) -> list[dict[str, str]]:
    index = _load_index(project_root / ".devclaw" / "assets" / "index.json")
    query_tokens = set(_tokens(query))
    scored: list[tuple[int, dict[str, str]]] = []
    for item in index:
        haystack = " ".join([item.get("intent", ""), item.get("source", "")])
        score = len(query_tokens & set(_tokens(haystack)))
        if score:
            scored.append((score, item))
    return [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)]


def _candidate_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(project_root.rglob("*")):
        relative = path.relative_to(project_root)
        if not path.is_file() or relative.parts[0] in {".devclaw", ".git", "__pycache__", ".pytest_cache"}:
            continue
        if path.suffix in {".py", ".md", ".js", ".ts", ".tsx", ".jsx"}:
            files.append(path)
    return files[:10]


def _load_index(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80]


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())
