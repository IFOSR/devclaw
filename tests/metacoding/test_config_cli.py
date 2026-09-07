"""`metacoding config` subcommand: persistent key/value management."""

from __future__ import annotations

from pathlib import Path

import pytest

from metacoding.cli import EXIT_OK, EXIT_USAGE, main as cli_main
from metacoding.config import set_config_value
from metacoding.errors import ConfigError
from metacoding.service import MetaCodingService


def config_path(root: Path) -> Path:
    return root / ".metacoding" / "config.toml"


def read_config(root: Path) -> str:
    return config_path(root).read_text(encoding="utf-8")


# --- set -----------------------------------------------------------------------


def test_set_model_creates_config_file_with_section(tmp_path: Path) -> None:
    service = MetaCodingService(project_root=tmp_path)
    outcome = service.config_set("coder.model", "code-cli/gpt-5.6-sol")
    assert outcome.exit_code == EXIT_OK
    text = read_config(tmp_path)
    assert "[harness.coder]" in text
    assert 'model = "code-cli/gpt-5.6-sol"' in text
    # effective config sees it
    assert service.config_get("coder.model").message == "coder.model = code-cli/gpt-5.6-sol"


def test_set_updates_existing_key_and_preserves_the_rest(tmp_path: Path) -> None:
    config_path(tmp_path).parent.mkdir(parents=True)
    config_path(tmp_path).write_text(
        "# my project config\n"
        "[limits]\n"
        "max_rounds = 3\n"
        "\n"
        "[harness.coder]\n"
        "provider = \"pi\"\n"
        "model = \"old-model\"\n",
        encoding="utf-8",
    )
    service = MetaCodingService(project_root=tmp_path)
    outcome = service.config_set("coder.model", "new-model")
    assert outcome.exit_code == EXIT_OK
    text = read_config(tmp_path)
    assert "# my project config" in text          # comments preserved
    assert "max_rounds = 3" in text               # other sections preserved
    assert 'model = "new-model"' in text
    assert "old-model" not in text
    assert 'provider = "pi"' in text


def test_set_supports_all_three_harness_models_independently(tmp_path: Path) -> None:
    service = MetaCodingService(project_root=tmp_path)
    for key, value in (
        ("planner.model", "planner-m"),
        ("coder.model", "coder-m"),
        ("tester.model", "tester-m"),
    ):
        assert service.config_set(key, value).exit_code == EXIT_OK
    text = read_config(tmp_path)
    assert "[harness.planner]" in text and "[harness.tester]" in text
    assert service.config_get("planner.model").message.endswith("planner-m")
    assert service.config_get("tester.model").message.endswith("tester-m")
    assert "tester-m" not in service.config_get("planner.model").message


def test_set_coerces_scalars_and_lists(tmp_path: Path) -> None:
    service = MetaCodingService(project_root=tmp_path)
    assert service.config_set("limits.max_rounds", "4").exit_code == EXIT_OK
    assert service.config_set("github.enabled", "true").exit_code == EXIT_OK
    assert service.config_set("github.remote", '"upstream"').exit_code == EXIT_OK
    assert service.config_set("tester.extra_args", "[--flag-a, --flag-b]").exit_code == EXIT_OK

    assert service.config_get("limits.max_rounds").message == "limits.max_rounds = 4"
    assert service.config_get("github.enabled").message == "github.enabled = true"
    assert service.config_get("github.remote").message == "github.remote = upstream"
    listing = "\n".join(service.config_list().lines)
    assert "--flag-a, --flag-b" in listing
    assert any(line.split()[0] == "harness.tester.extra_args" for line in listing.splitlines())


def test_set_rejects_unknown_keys_without_touching_file(tmp_path: Path) -> None:
    config_path(tmp_path).parent.mkdir(parents=True)
    config_path(tmp_path).write_text("[limits]\nmax_rounds = 2\n", encoding="utf-8")
    before = read_config(tmp_path)
    service = MetaCodingService(project_root=tmp_path)
    outcome = service.config_set("harness.evil.model", "x")
    assert outcome.exit_code == EXIT_USAGE
    outcome = service.config_set("schema_version", "2")
    assert outcome.exit_code == EXIT_USAGE
    assert read_config(tmp_path) == before


def test_set_invalid_value_rolls_back_the_file(tmp_path: Path) -> None:
    service = MetaCodingService(project_root=tmp_path)
    assert service.config_set("planner.provider", "codex").exit_code == EXIT_OK
    before = read_config(tmp_path)
    # provider must be one of the allowed set; the write must be rolled back
    outcome = service.config_set("planner.provider", "deepseek")
    assert outcome.exit_code == EXIT_USAGE
    assert read_config(tmp_path) == before


# --- get / list ------------------------------------------------------------------


def test_get_reports_defaults_for_unset_keys(tmp_path: Path) -> None:
    service = MetaCodingService(project_root=tmp_path)
    outcome = service.config_get("limits.max_rounds")
    assert outcome.exit_code == EXIT_OK
    assert outcome.message == "limits.max_rounds = 6"
    assert "default" in outcome.lines[0]


def test_get_marks_file_overrides(tmp_path: Path) -> None:
    service = MetaCodingService(project_root=tmp_path)
    service.config_set("coder.model", "coder-m")
    outcome = service.config_get("coder.model")
    assert "config.toml" in outcome.lines[0]


def test_list_shows_all_effective_settings(tmp_path: Path) -> None:
    service = MetaCodingService(project_root=tmp_path)
    service.config_set("planner.model", "planner-m")
    listing = "\n".join(service.config_list().lines)
    for expected in (
        "harness.planner.model",
        "harness.coder.model",
        "harness.tester.model",
        "limits.max_rounds",
        "policy.tester_can_modify_source",
        "github.auto_push",
    ):
        assert expected in listing


def test_get_unknown_key_is_usage_error(tmp_path: Path) -> None:
    service = MetaCodingService(project_root=tmp_path)
    assert service.config_get("nope.model").exit_code == EXIT_USAGE


# --- CLI dispatch ------------------------------------------------------------------


def test_cli_config_set_then_get(tmp_path: Path, capsys) -> None:
    assert cli_main(
        ["--project-root", str(tmp_path), "config", "set", "coder.model", "cli-model"]
    ) == EXIT_OK
    assert 'model = "cli-model"' in read_config(tmp_path)
    assert cli_main(
        ["--project-root", str(tmp_path), "config", "get", "coder.model"]
    ) == EXIT_OK
    assert "coder.model = cli-model" in capsys.readouterr().out
    assert cli_main(["--project-root", str(tmp_path), "config", "list"]) == EXIT_OK
    assert "harness.tester.model" in capsys.readouterr().out


def test_cli_config_set_invalid_key_exits_nonzero(tmp_path: Path, capsys) -> None:
    code = cli_main(
        ["--project-root", str(tmp_path), "config", "set", "bogus.key", "x"]
    )
    assert code == EXIT_USAGE
    assert not config_path(tmp_path).exists()


def test_set_config_value_function_round_trip(tmp_path: Path) -> None:
    from metacoding.config import load_config

    set_config_value(tmp_path, "limits.idle_timeout_seconds", "42")
    config = load_config(tmp_path)
    assert config.limits.idle_timeout_seconds == 42
    with pytest.raises(ConfigError):
        set_config_value(tmp_path, "limits.max_rounds", "0")
    # rollback: previous valid value intact
    assert load_config(tmp_path).limits.max_rounds == 6
