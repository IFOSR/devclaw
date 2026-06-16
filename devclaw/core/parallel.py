from __future__ import annotations

import concurrent.futures
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Subtask:
    task_id: str
    prompt: str
    can_run_parallel: bool = True


@dataclass(frozen=True)
class SubtaskDag:
    intent: str
    tasks: list[Subtask]

    def to_dict(self) -> dict[str, object]:
        return {"intent": self.intent, "tasks": [asdict(task) for task in self.tasks]}


@dataclass(frozen=True)
class ParallelRunReport:
    status: str
    integrated_files: list[str]
    transcripts: list[str]
    failed_tasks: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class PromptExecutor(Protocol):
    def execute_prompt(self, prompt: str, workspace: Path) -> str:
        ...


def create_subtask_dag(intent: str) -> SubtaskDag:
    parts = [part.strip(" .") for part in intent.split(" and ") if part.strip(" .")]
    if len(parts) < 2:
        parts = [f"Implementation subtask for: {intent}", f"Documentation/test subtask for: {intent}"]
    tasks = [
        Subtask(task_id=f"task-{index + 1}", prompt=part)
        for index, part in enumerate(parts)
    ]
    return SubtaskDag(intent=intent, tasks=tasks)


class ParallelCodexRunner:
    def __init__(self, executor: PromptExecutor, max_workers: int = 2):
        self.executor = executor
        self.max_workers = max_workers

    def run(self, dag: SubtaskDag, project_root: Path) -> ParallelRunReport:
        base_dir = project_root / ".devclaw" / "parallel"
        transcript_dir = project_root / ".devclaw" / "reports" / "tool-transcripts"
        base_dir.mkdir(parents=True, exist_ok=True)
        transcript_dir.mkdir(parents=True, exist_ok=True)
        (project_root / ".devclaw" / "tasks" / "subtask-dag.json").parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        (project_root / ".devclaw" / "tasks" / "subtask-dag.json").write_text(
            json.dumps(dag.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        transcripts: list[str] = []
        failed_tasks: list[str] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [
                pool.submit(self._run_one, task, project_root, base_dir, transcript_dir)
                for task in dag.tasks
                if task.can_run_parallel
            ]
            for future in concurrent.futures.as_completed(futures):
                transcript, error = future.result()
                transcripts.append(transcript)
                if error:
                    failed_tasks.append(error)

        integrated_files = _integrate_parallel_workspaces(base_dir, project_root)
        status = "pass" if integrated_files and len(transcripts) == len(dag.tasks) else "fail"
        report = ParallelRunReport(
            status=status,
            integrated_files=integrated_files,
            transcripts=sorted(transcripts),
            failed_tasks=failed_tasks,
        )
        report_path = project_root / ".devclaw" / "reports" / "parallel-run-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return report

    def _run_one(
        self,
        task: Subtask,
        project_root: Path,
        base_dir: Path,
        transcript_dir: Path,
    ) -> tuple[str, str | None]:
        workspace = base_dir / task.task_id / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        _copy_project(project_root, workspace)
        error: str | None = None
        try:
            output = self.executor.execute_prompt(task.prompt, workspace)
        except RuntimeError as exc:
            output = str(exc)
            error = f"{task.task_id}: {exc}"
        transcript = transcript_dir / f"parallel-{task.task_id}.txt"
        transcript.write_text(
            "\n".join(["# Prompt", task.prompt, "", "# Output", output]),
            encoding="utf-8",
        )
        return str(transcript.relative_to(project_root)), error


def _copy_project(source: Path, dest: Path) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if relative.parts and relative.parts[0] == ".devclaw":
            continue
        target = dest / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _integrate_parallel_workspaces(base_dir: Path, project_root: Path) -> list[str]:
    integrated: list[str] = []
    for workspace in sorted(base_dir.glob("*/workspace")):
        for path in workspace.rglob("*"):
            relative = path.relative_to(workspace)
            if not path.is_file() or relative.parts[0] in {".git", ".devclaw"}:
                continue
            target = project_root / relative
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            integrated.append(str(relative))
    return sorted(set(integrated))
