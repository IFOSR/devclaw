"""Configuration loading, precedence, and validation behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from metacoding.cli import build_parser
from metacoding.config import (
    CliOverrides,
    HarnessConfig,
    default_config,
    load_config,
)
from metacoding.errors import ConfigError


def write_config(root: Path, text: str) -> Path:
    config_dir = root / ".metacoding"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_without_config_file(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.schema_version == 1
    assert config.limits.max_rounds == 6
    assert config.limits.same_failure_limit == 2
    assert config.limits.idle_timeout_seconds == 900
    assert config.harness["planner"].provider == "codex"
    assert config.harness["coder"].provider == "pi"
    assert config.harness["tester"].provider == "codex"
    assert config.harness["planner"].command == "codex"
    assert config.harness["coder"].command == "pi"
    assert config.harness["tester"].command == "codex"
    assert config.policy.allow_network is False
    assert config.policy.tester_can_modify_source is False
    assert config.github.enabled is False


def test_toml_file_overrides_defaults(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        """
[limits]
max_rounds = 3
idle_timeout_seconds = 60

[harness.coder]
model = "coder-model-x"
extra_args = ["--flag"]
""",
    )
    config = load_config(tmp_path)
    assert config.limits.max_rounds == 3
    assert config.limits.idle_timeout_seconds == 60
    assert config.limits.same_failure_limit == 2
    assert config.harness["coder"].model == "coder-model-x"
    assert config.harness["coder"].extra_args == ["--flag"]


def test_per_harness_models_are_independent(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        """
[harness.planner]
provider = "codex"
model = "planner-model-a"

[harness.coder]
provider = "pi"
model = "coder-model-b"

[harness.tester]
provider = "codex"
model = "tester-model-c"
""",
    )
    config = load_config(tmp_path)
    planner, coder, tester = (
        config.harness["planner"],
        config.harness["coder"],
        config.harness["tester"],
    )
    assert (planner.model, coder.model, tester.model) == (
        "planner-model-a",
        "coder-model-b",
        "tester-model-c",
    )
    assert planner.provider == tester.provider == "codex"
    assert planner is not tester
    assert planner.model != tester.model


def test_cli_overrides_apply_without_persisting(tmp_path: Path) -> None:
    config_path = write_config(tmp_path, '[harness.planner]\nmodel = "file-model"\n')
    before = config_path.read_text(encoding="utf-8")
    overrides = CliOverrides(
        planner_model="cli-model",
        tester_command="/opt/codex",
        max_rounds=2,
    )
    config = load_config(tmp_path, overrides)
    assert config.harness["planner"].model == "cli-model"
    assert config.harness["tester"].command == "/opt/codex"
    assert config.limits.max_rounds == 2
    assert config_path.read_text(encoding="utf-8") == before


def test_cli_overrides_from_argparse_namespace() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--planner-model",
            "p1",
            "--coder-model",
            "c1",
            "run",
            "req",
            "--tester-model",
            "t1",
            "--max-rounds",
            "4",
        ]
    )
    overrides = CliOverrides.from_args(args)
    assert overrides.planner_model == "p1"
    assert overrides.coder_model == "c1"
    assert overrides.tester_model == "t1"
    assert overrides.max_rounds == 4


def test_invalid_provider_rejected(tmp_path: Path) -> None:
    write_config(tmp_path, '[harness.planner]\nprovider = "deepseek"\n')
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_invalid_limits_rejected(tmp_path: Path) -> None:
    write_config(tmp_path, "[limits]\nmax_rounds = 0\n")
    with pytest.raises(ConfigError):
        load_config(tmp_path)
    write_config(tmp_path, "[limits]\nidle_timeout_seconds = -5\n")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_secret_fields_rejected(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        """
[harness.planner]
provider = "codex"
model = "m"
api_key = "sk-secret"

[harness.tester]
token = "abc"
""",
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path)
    assert "api_key" in str(excinfo.value)


def test_github_section_loaded_and_validated(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        """
[github]
enabled = true
remote = "upstream"
auto_push = true
wait_for_checks = true
""",
    )
    config = load_config(tmp_path)
    assert config.github.enabled is True
    assert config.github.remote == "upstream"
    assert config.github.auto_push is True

    write_config(tmp_path, '[github]\nmode = "force-push-everything"\n')
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_malformed_toml_rejected(tmp_path: Path) -> None:
    write_config(tmp_path, "not [valid toml")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_default_config_snapshot_round_trips(tmp_path: Path) -> None:
    config = default_config()
    snapshot = config.to_dict()
    assert snapshot["harness"]["planner"]["provider"] == "codex"
    assert snapshot["harness"]["coder"]["provider"] == "pi"
    assert snapshot["harness"]["tester"]["provider"] == "codex"
    assert set(snapshot["harness"]) == {"planner", "coder", "tester"}
    default = default_config()
    harness = HarnessConfig(
        name="planner",
        provider=default.harness["planner"].provider,
        command=default.harness["planner"].command,
        model=default.harness["planner"].model,
        extra_args=default.harness["planner"].extra_args,
    )
    assert harness in [
        HarnessConfig(
            name=key,
            provider=value["provider"],
            command=value["command"],
            model=value["model"],
            extra_args=value["extra_args"],
        )
        for key, value in snapshot["harness"].items()
    ]
