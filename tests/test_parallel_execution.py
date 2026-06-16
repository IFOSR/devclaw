from pathlib import Path

from devclaw.core.parallel import ParallelCodexRunner, create_subtask_dag


class RecordingExecutor:
    def __init__(self):
        self.workspaces: list[Path] = []

    def execute_prompt(self, prompt: str, workspace: Path):
        self.workspaces.append(workspace)
        name = "alpha.py" if "alpha" in prompt.lower() else "beta.py"
        (workspace / name).write_text(f"print('{name}')\n", encoding="utf-8")
        return f"created {name}"


def test_create_subtask_dag_splits_requirement_into_parallel_tasks():
    dag = create_subtask_dag("Create alpha.py and beta.py")

    assert len(dag.tasks) >= 2
    assert all(task.can_run_parallel for task in dag.tasks)
    assert dag.tasks[0].task_id != dag.tasks[1].task_id


def test_parallel_codex_runner_uses_isolated_workspaces_and_persists_transcripts(tmp_path: Path):
    executor = RecordingExecutor()
    runner = ParallelCodexRunner(executor=executor, max_workers=2)
    dag = create_subtask_dag("Create alpha.py and beta.py")

    report = runner.run(dag, tmp_path)

    assert report.status == "pass"
    assert len(executor.workspaces) >= 2
    assert len({workspace for workspace in executor.workspaces}) == len(executor.workspaces)
    assert all(".devclaw/parallel" in str(workspace) for workspace in executor.workspaces)
    assert (tmp_path / "alpha.py").exists()
    assert (tmp_path / "beta.py").exists()
    assert len(list((tmp_path / ".devclaw" / "reports" / "tool-transcripts").glob("parallel-*.txt"))) >= 2
