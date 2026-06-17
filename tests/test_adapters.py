from pathlib import Path
from types import SimpleNamespace

from devclaw.adapters.execution import (
    CodexCliExecutionAdapter,
    ToolExecutionResult,
)
from tests.fakes import TestExecutionAdapter, TestVerificationAdapter
from devclaw.adapters.verification import (
    DeepseekTuiVerificationAdapter,
    parse_deepseek_verification_output,
)
from devclaw.agents.engineering import EngineerAgent
from devclaw.agents.qa import QAAgent
from devclaw.core.contracts import create_acceptance_contract, create_project_brief
from devclaw.core.role_assignments import ROLE_ASSIGNMENTS


def _contract():
    brief = create_project_brief("Build a customer feedback triage Agent")
    return brief, create_acceptance_contract(brief)


def test_local_verification_fails_when_required_files_are_missing(tmp_path: Path):
    brief, contract = _contract()

    report = TestVerificationAdapter().verify(brief, contract, tmp_path)

    assert report.status == "fail"
    assert "F1" in report.failed_acceptance
    assert report.blocking_issues


def test_engineer_local_execution_writes_runnable_delivery_files(tmp_path: Path):
    brief, contract = _contract()
    output = EngineerAgent(TestExecutionAdapter()).run(brief, contract, tmp_path)

    assert output.agent == "Engineer Agent"
    assert output.path == "agent.py"
    assert (tmp_path / "agent.py").exists()
    assert (tmp_path / "USAGE.md").exists()


def test_local_verification_passes_after_engineer_output_exists(tmp_path: Path):
    brief, contract = _contract()
    EngineerAgent(TestExecutionAdapter()).run(brief, contract, tmp_path)

    report = QAAgent(TestVerificationAdapter()).run(brief, contract, tmp_path)

    assert report.status == "pass"
    assert report.failed_acceptance == []
    assert report.blocking_issues == []


def test_local_verification_runs_project_test_commands_when_present(tmp_path: Path):
    brief = create_project_brief(
        "Create hello.py so running python3 hello.py prints exactly: hello from DevClaw"
    )
    contract = create_acceptance_contract(brief)
    (tmp_path / "tests").mkdir()
    (tmp_path / "hello.py").write_text(
        "print('hello from DevClaw')\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_hello.py").write_text(
        "import subprocess\n"
        "import sys\n\n"
        "def test_hello_cli():\n"
        "    result = subprocess.run([sys.executable, 'hello.py'], text=True, capture_output=True, check=True)\n"
        "    assert result.stdout.strip() == 'hello from DevClaw'\n",
        encoding="utf-8",
    )

    report = TestVerificationAdapter().verify(brief, contract, tmp_path)

    assert report.status == "pass"
    assert report.failed_acceptance == []
    assert report.blocking_issues == []
    assert any("python3 -m pytest -q" in item for item in report.evidence)


def test_codex_cli_adapter_uses_non_interactive_exec(monkeypatch, tmp_path: Path):
    brief, contract = _contract()
    calls = []

    def fake_run_tool(cmd, cwd, idle_timeout_seconds, env=None, on_output=None, **kwargs):
        calls.append((cmd, {"cwd": cwd, "idle_timeout_seconds": idle_timeout_seconds, "env": env, "on_output": on_output}))
        return ToolExecutionResult(returncode=0, stdout="implemented", stderr="")

    monkeypatch.setattr("devclaw.adapters.execution.run_tool_with_idle_monitor", fake_run_tool)

    output = CodexCliExecutionAdapter(codex_bin="codex-test").execute(
        brief, contract, tmp_path
    )

    cmd, kwargs = calls[0]
    assert cmd[:2] == ["codex-test", "exec"]
    assert "-C" in cmd
    assert "--skip-git-repo-check" in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert "--ask-for-approval" not in cmd
    assert "Autonomous execution mode" in cmd[-1]
    assert kwargs["env"] is None or "CODEX_HOME" not in kwargs["env"]
    assert kwargs["on_output"] is not None
    assert output.artifact == "Codex CLI Execution"
    transcript = tmp_path / ".devclaw" / "reports" / "tool-transcripts" / "codex-execution.txt"
    assert transcript.exists()
    assert "implemented" in transcript.read_text()


def test_codex_cli_adapter_runs_role_task_with_skills_in_prompt(monkeypatch, tmp_path: Path):
    brief, contract = _contract()
    calls = []
    events: list[dict[str, str]] = []

    def fake_run_tool(cmd, cwd, idle_timeout_seconds, env=None, on_output=None, **kwargs):
        calls.append(cmd)
        on_output("stderr", "I’ll inspect the project structure first.")
        return ToolExecutionResult(returncode=0, stdout="# UX Research Report\n\nFindings", stderr="")

    monkeypatch.setattr("devclaw.adapters.execution.run_tool_with_idle_monitor", fake_run_tool)

    output = CodexCliExecutionAdapter(codex_bin="codex-test", progress=events.append).run_role(
        ROLE_ASSIGNMENTS["ux_research"],
        brief,
        contract,
        tmp_path,
        previous_outputs=[],
    )

    prompt = calls[0][-1]
    assert "Codex UX Research Agent" in prompt
    assert "Skills to use" in prompt
    assert "screenshot-analysis" in prompt
    assert "## Skills Used" in prompt
    assert output.agent == "Codex UX Research Agent"
    assert output.artifact == "UX Research Report"
    assert output.content.startswith("# UX Research Report")
    assert any(
        event["stage"] == "research" and event["agent"] == "Codex UX Research Agent"
        for event in events
        if event["status"] == "milestone"
    )


def test_codex_cli_adapter_emits_role_heartbeat(monkeypatch, tmp_path: Path):
    brief, contract = _contract()
    events: list[dict[str, str]] = []

    def fake_run_tool(cmd, cwd, idle_timeout_seconds, env=None, on_output=None, on_heartbeat=None, heartbeat_interval_seconds=None):
        assert heartbeat_interval_seconds == 60
        on_heartbeat(125.4)
        return ToolExecutionResult(returncode=0, stdout="# Technical Plan\n\nPlan", stderr="")

    monkeypatch.setattr("devclaw.adapters.execution.run_tool_with_idle_monitor", fake_run_tool)

    CodexCliExecutionAdapter(codex_bin="codex-test", progress=events.append).run_role(
        ROLE_ASSIGNMENTS["technical_plan"],
        brief,
        contract,
        tmp_path,
        previous_outputs=[],
    )

    heartbeat = next(event for event in events if event["status"] == "heartbeat")
    assert heartbeat["stage"] == "architecture"
    assert heartbeat["agent"] == "Codex Technical Plan Agent"
    assert heartbeat["elapsed_seconds"] == "125.4"


def test_codex_cli_prompt_execution_preserves_real_codex_home_for_skills(monkeypatch, tmp_path: Path):
    brief, contract = _contract()
    calls = []

    def fake_run_tool(cmd, cwd, idle_timeout_seconds, env=None, on_output=None, **kwargs):
        calls.append((cmd, {"cwd": cwd, "idle_timeout_seconds": idle_timeout_seconds, "env": env, "on_output": on_output}))
        return ToolExecutionResult(returncode=0, stdout="implemented", stderr="")

    monkeypatch.setattr("devclaw.adapters.execution.run_tool_with_idle_monitor", fake_run_tool)

    output = CodexCliExecutionAdapter(codex_bin="codex-test").execute_prompt(
        "Create a file", tmp_path
    )

    assert output == "implemented"
    env = calls[0][1]["env"]
    assert env is None or "CODEX_HOME" not in env
    assert calls[0][1]["on_output"] is not None


def test_codex_cli_adapter_rejects_confirmation_only_responses(monkeypatch, tmp_path: Path):
    brief, contract = _contract()

    def fake_run_tool(cmd, cwd, idle_timeout_seconds, env=None, on_output=None, **kwargs):
        return ToolExecutionResult(
            returncode=0,
            stdout="请确认实现范围：A. 静态站点 B. React/Vite C. 全栈服务",
            stderr="",
        )

    monkeypatch.setattr("devclaw.adapters.execution.run_tool_with_idle_monitor", fake_run_tool)

    try:
        CodexCliExecutionAdapter(codex_bin="codex-test").execute(
            brief, contract, tmp_path
        )
    except RuntimeError as error:
        assert "USER_CONFIRMATION_REQUIRED" in str(error)
    else:
        raise AssertionError("expected RuntimeError")


def test_codex_cli_adapter_summarizes_tool_output_as_milestones():
    events: list[dict[str, str]] = []
    adapter = CodexCliExecutionAdapter(codex_bin="codex-test", progress=events.append)

    adapter._on_tool_output(
        "stderr",
        "\n".join(
            [
                "I’ll inspect the project structure first.",
                "/bin/zsh -lc 'python3 -m pytest -q' in /tmp/project",
                "patch: completed",
                "I’m adding README and delivery documentation.",
            ]
        ),
    )

    milestones = [event["message"] for event in events if event["status"] == "milestone"]
    assert "Inspecting project structure and existing context." in milestones
    assert "Running implementation checks." in milestones
    assert "Applying code changes." in milestones
    assert "Preparing documentation and delivery notes." in milestones
    assert not any(event["status"] == "output" for event in events)


def test_deepseek_tui_adapter_summarizes_tool_output_as_milestones():
    events: list[dict[str, str]] = []
    adapter = DeepseekTuiVerificationAdapter(deepseek_bin="deepseek-test", progress=events.append)

    adapter._on_tool_output(
        "stderr",
        "\n".join(
            [
                "I will inspect .devclaw and run npm test.",
                "/bin/zsh -lc 'npm test' in /tmp/project",
                '{"status":"pass","failed_acceptance":[],"blocking_issues":[]}',
            ]
        ),
    )

    milestones = [event["message"] for event in events if event["status"] == "milestone"]
    assert "Inspecting delivered files and DevClaw artifacts." in milestones
    assert "Running QA checks." in milestones
    assert "Parsing QA verdict." in milestones
    assert not any(event["status"] == "output" for event in events)


def test_deepseek_tui_adapter_uses_non_interactive_exec(monkeypatch, tmp_path: Path):
    brief, contract = _contract()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_placeholder.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )
    calls = []

    def fake_run_tool(cmd, cwd, idle_timeout_seconds, on_output=None, **kwargs):
        calls.append((cmd, {"cwd": cwd, "idle_timeout_seconds": idle_timeout_seconds, "on_output": on_output}))
        return ToolExecutionResult(
            returncode=0,
            stdout='{"status":"pass","failed_acceptance":[],"blocking_issues":[],"non_blocking_issues":[],"evidence":["Looks pass"]}',
            stderr="",
        )

    monkeypatch.setattr("devclaw.adapters.verification.run_tool_with_idle_monitor", fake_run_tool)

    report = DeepseekTuiVerificationAdapter(deepseek_bin="deepseek-test").verify(
        brief, contract, tmp_path
    )

    cmd, kwargs = calls[0]
    assert cmd[:2] == ["deepseek-test", "exec"]
    assert "--auto" in cmd
    assert "--approval-policy" in cmd
    assert "never" in cmd
    assert "--sandbox-mode" in cmd
    assert "danger-full-access" in cmd
    assert ".devclaw/artifacts" in cmd[-1]
    assert "Do not fail because final delivery reports are absent before QA" in cmd[-1]
    assert "python3 -m pytest -q" in cmd[-1]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["on_output"] is not None
    assert report.status == "pass"
    transcript = tmp_path / ".devclaw" / "reports" / "tool-transcripts" / "deepseek-verification.txt"
    assert transcript.exists()
    assert "Looks pass" in transcript.read_text()


def test_deepseek_tui_adapter_runs_role_task_with_skills_in_prompt(monkeypatch, tmp_path: Path):
    brief, contract = _contract()
    calls = []
    events: list[dict[str, str]] = []

    def fake_run_tool(cmd, cwd, idle_timeout_seconds, on_output=None, **kwargs):
        calls.append(cmd)
        on_output("stderr", "I will inspect .devclaw and run npm test.")
        return ToolExecutionResult(returncode=0, stdout="# PRD\n\nScope", stderr="")

    monkeypatch.setattr("devclaw.adapters.verification.run_tool_with_idle_monitor", fake_run_tool)

    output = DeepseekTuiVerificationAdapter(deepseek_bin="deepseek-test", progress=events.append).run_role(
        ROLE_ASSIGNMENTS["prd"],
        brief,
        contract,
        tmp_path,
        previous_outputs=[],
    )

    prompt = calls[0][-1]
    assert "Deepseek PRD Agent" in prompt
    assert "Skills to use" in prompt
    assert "product-structuring" in prompt
    assert "## Skills Used" in prompt
    assert output.agent == "Deepseek PRD Agent"
    assert output.artifact == "PRD"
    assert output.content.startswith("# PRD")
    assert any(
        event["stage"] == "product" and event["agent"] == "Deepseek PRD Agent"
        for event in events
        if event["status"] == "milestone"
    )


def test_deepseek_tui_adapter_emits_role_heartbeat(monkeypatch, tmp_path: Path):
    brief, contract = _contract()
    events: list[dict[str, str]] = []

    def fake_run_tool(cmd, cwd, idle_timeout_seconds, on_output=None, on_heartbeat=None, heartbeat_interval_seconds=None):
        assert heartbeat_interval_seconds == 60
        on_heartbeat(61.2)
        return ToolExecutionResult(returncode=0, stdout="# Code Review Report\n\nLooks good", stderr="")

    monkeypatch.setattr("devclaw.adapters.verification.run_tool_with_idle_monitor", fake_run_tool)

    DeepseekTuiVerificationAdapter(deepseek_bin="deepseek-test", progress=events.append).run_role(
        ROLE_ASSIGNMENTS["code_review"],
        brief,
        contract,
        tmp_path,
        previous_outputs=[],
    )

    heartbeat = next(event for event in events if event["status"] == "heartbeat")
    assert heartbeat["stage"] == "review"
    assert heartbeat["agent"] == "Deepseek Code Review Agent"
    assert heartbeat["elapsed_seconds"] == "61.2"


def test_codex_cli_adapter_raises_clear_error_on_idle_timeout(monkeypatch, tmp_path: Path):
    brief, contract = _contract()

    def fake_run_tool(cmd, cwd, idle_timeout_seconds, env=None, on_output=None, **kwargs):
        raise TimeoutError("Tool produced no output for 1 seconds.")

    monkeypatch.setattr("devclaw.adapters.execution.run_tool_with_idle_monitor", fake_run_tool)

    try:
        CodexCliExecutionAdapter(codex_bin="codex-test", idle_timeout_seconds=1).execute(
            brief, contract, tmp_path
        )
    except RuntimeError as error:
        assert "no output" in str(error).lower()
        transcript = tmp_path / ".devclaw" / "reports" / "tool-transcripts" / "codex-execution.txt"
        assert transcript.exists()
        assert "no output" in transcript.read_text().lower()
    else:
        raise AssertionError("expected RuntimeError")


def test_codex_cli_adapter_classifies_concurrency_limit_as_retryable(monkeypatch, tmp_path: Path):
    brief, contract = _contract()

    def fake_run_tool(cmd, cwd, idle_timeout_seconds, env=None, on_output=None, **kwargs):
        return ToolExecutionResult(
            returncode=1,
            stdout="",
            stderr="ERROR: stream disconnected before completion: Concurrency limit exceeded for account, please retry later",
        )

    monkeypatch.setattr("devclaw.adapters.execution.run_tool_with_idle_monitor", fake_run_tool)

    try:
        CodexCliExecutionAdapter(codex_bin="codex-test").run_role(
            ROLE_ASSIGNMENTS["technical_plan"],
            brief,
            contract,
            tmp_path,
            previous_outputs=[],
        )
    except RuntimeError as error:
        message = str(error)
        assert "TOOL_RETRYABLE" in message
        assert "Concurrency limit exceeded" in message
    else:
        raise AssertionError("expected RuntimeError")


def test_deepseek_tui_adapter_reports_idle_timeout_as_failed_verification(monkeypatch, tmp_path: Path):
    brief, contract = _contract()

    def fake_run_tool(cmd, cwd, idle_timeout_seconds, on_output=None, **kwargs):
        raise TimeoutError("Tool produced no output for 1 seconds.")

    monkeypatch.setattr("devclaw.adapters.verification.run_tool_with_idle_monitor", fake_run_tool)

    report = DeepseekTuiVerificationAdapter(
        deepseek_bin="deepseek-test", idle_timeout_seconds=1
    ).verify(brief, contract, tmp_path)

    assert report.status == "fail"
    assert "no output" in report.blocking_issues[0].lower()
    transcript = tmp_path / ".devclaw" / "reports" / "tool-transcripts" / "deepseek-verification.txt"
    assert transcript.exists()
    assert "no output" in transcript.read_text().lower()


def test_deepseek_tui_adapter_parses_structured_report_from_tool_log_stderr(monkeypatch, tmp_path: Path):
    brief, contract = _contract()

    def fake_run_tool(cmd, cwd, idle_timeout_seconds, on_output=None, **kwargs):
        return ToolExecutionResult(
            returncode=0,
            stdout="QA completed. Final report was emitted by a tool call.",
            stderr='tool exec_shell completed\n--- stdout/stderr ---\n{"status":"pass","failed_acceptance":[],"blocking_issues":[],"non_blocking_issues":["minor"],"evidence":["pytest passed"]}\n---------------------',
        )

    monkeypatch.setattr("devclaw.adapters.verification.run_tool_with_idle_monitor", fake_run_tool)

    report = DeepseekTuiVerificationAdapter(deepseek_bin="deepseek-test").verify(
        brief, contract, tmp_path
    )

    assert report.status == "pass"
    assert report.non_blocking_issues == ["minor"]
    assert report.evidence == ["pytest passed"]


def test_parse_deepseek_verification_output_extracts_structured_json_report():
    report = parse_deepseek_verification_output(
        """
        Verification result:
        {
          "status": "fail",
          "failed_acceptance": ["F1", "Q1"],
          "blocking_issues": ["CLI output is wrong"],
          "non_blocking_issues": ["README could be clearer"],
          "evidence": ["pytest failed"]
        }
        """
    )

    assert report.status == "fail"
    assert report.failed_acceptance == ["F1", "Q1"]
    assert report.blocking_issues == ["CLI output is wrong"]
    assert report.non_blocking_issues == ["README could be clearer"]
    assert report.evidence == ["pytest failed"]


def test_parse_deepseek_verification_output_handles_malformed_output_as_blocking_failure():
    report = parse_deepseek_verification_output("I could not inspect the project.")

    assert report.status == "fail"
    assert report.failed_acceptance == ["QA_PARSE"]
    assert report.blocking_issues == ["Deepseek output did not contain a structured verification report."]
    assert report.evidence == ["I could not inspect the project."]
