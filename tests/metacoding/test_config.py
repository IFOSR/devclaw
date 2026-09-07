"""Configuration loading, precedence, and validation behavior."""

from __future__ import annotations

from pathlib import Path

import json
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


# --- harness extra_args hardening ----------------------------------------------------


@pytest.mark.parametrize(
    "token", ["-s", "--sandbox", "--danger-full-access", "--yolo", "--full-auto", "-c", "--config", "--profile"]
)
def test_dangerous_extra_args_rejected(tmp_path: Path, token: str) -> None:
    write_config(tmp_path, f'[harness.planner]\nextra_args = ["{token}"]\n')
    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path)
    assert "extra_args" in str(excinfo.value)


def test_benign_extra_args_accepted(tmp_path: Path) -> None:
    write_config(tmp_path, '[harness.coder]\nextra_args = ["--thinking", "high"]\n')
    config = load_config(tmp_path)
    assert config.harness["coder"].extra_args == ["--thinking", "high"]


# --- snapshot-based resume configuration ----------------------------------------------


def test_project_config_from_dict_round_trips_for_resume(tmp_path: Path) -> None:
    from metacoding.config import ProjectConfig

    write_config(
        tmp_path,
        """
[harness.planner]
model = "planner-m"

[github]
enabled = true
check_timeout_seconds = 120
check_poll_seconds = 5
""",
    )
    config = load_config(tmp_path)
    restored = ProjectConfig.from_dict(config.to_dict())
    assert restored == config or restored.to_dict() == config.to_dict()
    assert restored.harness["planner"].model == "planner-m"
    assert restored.github.check_timeout_seconds == 120
    # a snapshot survives a later config file change
    (tmp_path / ".metacoding" / "config.toml").write_text(
        '[harness.planner]\nmodel = "changed-after-start"\n', encoding="utf-8"
    )
    again = ProjectConfig.from_dict(config.to_dict())
    assert again.harness["planner"].model == "planner-m"


def test_github_check_timing_settings_validated(tmp_path: Path) -> None:
    write_config(tmp_path, "[github]\ncheck_timeout_seconds = 0\n")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


# --- extra_args hardening: prefixed forms ---------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "--sandbox=danger-full-access",
        '--config=sandbox_mode="danger-full-access"',
        "--add-dir=/",
        "--add-dir",
        "--profile=untrusted",
    ],
)
def test_prefixed_dangerous_extra_args_rejected(tmp_path: Path, token: str) -> None:
    write_config(tmp_path, f'[harness.tester]\nextra_args = ["{token}"]\n')
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_snapshot_validation_rejects_tampered_configs() -> None:
    from metacoding.config import ProjectConfig

    base = default_config().to_dict()
    tampered = json.loads(json.dumps(base))
    tampered["harness"]["planner"]["provider"] = "deepseek"
    with pytest.raises(ConfigError):
        ProjectConfig.from_dict(tampered)

    tampered = json.loads(json.dumps(base))
    tampered["harness"]["coder"]["extra_args"] = ["--sandbox=read-only"]
    with pytest.raises(ConfigError):
        ProjectConfig.from_dict(tampered)

    tampered = json.loads(json.dumps(base))
    tampered["limits"]["max_rounds"] = 0
    with pytest.raises(ConfigError):
        ProjectConfig.from_dict(tampered)

    tampered = json.loads(json.dumps(base))
    tampered["github"]["mode"] = "force-push"
    with pytest.raises(ConfigError):
        ProjectConfig.from_dict(tampered)


def test_max_execution_seconds_configured_and_validated(tmp_path: Path) -> None:
    write_config(tmp_path, "[limits]\nmax_execution_seconds = 120\n")
    config = load_config(tmp_path)
    assert config.limits.max_execution_seconds == 120
    write_config(tmp_path, "[limits]\nmax_execution_seconds = 0\n")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


# --- snapshot strictness: missing fields are corruption -------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["harness"].pop("coder"),
        lambda s: s["harness"]["tester"].pop("model"),
        lambda s: s["limits"].pop("max_execution_seconds"),
        lambda s: s["github"].pop("enabled"),
        lambda s: s["policy"].pop("tester_can_modify_source"),
        lambda s: s.pop("limits"),
    ],
)
def test_snapshot_missing_fields_are_rejected(mutate) -> None:
    from metacoding.config import ProjectConfig

    snapshot = json.loads(json.dumps(default_config().to_dict()))
    mutate(snapshot)
    with pytest.raises(ConfigError) as excinfo:
        ProjectConfig.from_dict(snapshot)
    assert "missing" in str(excinfo.value)
