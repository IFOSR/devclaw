from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


IGNORED_DIRS = {".git", ".devclaw", "__pycache__", ".pytest_cache", "node_modules", ".venv"}


@dataclass(frozen=True)
class ProjectContext:
    project_root: Path
    primary_language: str
    frameworks: list[str]
    test_commands: list[str]
    lint_commands: list[str]
    build_commands: list[str]
    docs: list[str]
    files: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["project_root"] = str(self.project_root)
        return data

    def summary(self) -> str:
        return "\n".join(
            [
                "# Project Context",
                f"Root: {self.project_root}",
                f"Primary language: {self.primary_language}",
                f"Frameworks: {', '.join(self.frameworks) or 'unknown'}",
                f"Test commands: {', '.join(self.test_commands) or 'none detected'}",
                f"Docs: {', '.join(self.docs) or 'none detected'}",
                "Files:",
                *[f"- {item}" for item in self.files[:30]],
            ]
        )


def scan_project_context(project_root: Path) -> ProjectContext:
    root = project_root.resolve()
    files = _list_files(root)
    primary_language = _detect_language(files)
    frameworks = _detect_frameworks(files)
    test_commands = _detect_test_commands(files)
    lint_commands = _detect_lint_commands(files)
    build_commands = _detect_build_commands(files)
    docs = [item for item in files if Path(item).name.lower() in {"readme.md", "contributing.md"}]
    return ProjectContext(
        project_root=project_root,
        primary_language=primary_language,
        frameworks=frameworks,
        test_commands=test_commands,
        lint_commands=lint_commands,
        build_commands=build_commands,
        docs=docs,
        files=files,
    )


def _list_files(root: Path) -> list[str]:
    result: list[str] = []
    for path in sorted(root.rglob("*")):
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            result.append(str(path.relative_to(root)))
    return result


def _detect_language(files: list[str]) -> str:
    if any(item.endswith(".py") or item == "pyproject.toml" for item in files):
        return "python"
    if any(item.endswith((".ts", ".tsx", ".js", ".jsx")) or item == "package.json" for item in files):
        return "javascript"
    return "unknown"


def _detect_frameworks(files: list[str]) -> list[str]:
    frameworks: list[str] = []
    if "pyproject.toml" in files:
        frameworks.append("pyproject")
    if "package.json" in files:
        frameworks.append("node")
    if any(item.startswith("tests/") for item in files):
        frameworks.append("tests")
    return frameworks


def _detect_test_commands(files: list[str]) -> list[str]:
    commands: list[str] = []
    if "pyproject.toml" in files or any(item.startswith("tests/") and item.endswith(".py") for item in files):
        commands.append("python3 -m pytest -q")
    if "package.json" in files:
        commands.append("npm test")
    return commands


def _detect_lint_commands(files: list[str]) -> list[str]:
    commands: list[str] = []
    if "package.json" in files:
        commands.append("npm run lint")
    return commands


def _detect_build_commands(files: list[str]) -> list[str]:
    commands: list[str] = []
    if "package.json" in files:
        commands.append("npm run build")
    return commands
