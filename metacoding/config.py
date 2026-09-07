"""Project-local configuration loading and validation.

Configuration precedence is: built-in defaults -> ``.metacoding/config.toml``
-> command-line overrides. Overrides apply to the current invocation only
and are never written back to the project file. Secrets are rejected.
"""

from __future__ import annotations

import argparse

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from metacoding.errors import ConfigError

SCHEMA_VERSION = 1
VALID_PROVIDERS = ("codex", "pi", "fake")
VALID_GITHUB_MODES = ("pull-request", "branch", "none")

#: Keys that must never appear in the project config.
SECRET_FIELD_NAMES = {"token", "api_key", "apikey", "secret", "password", "client_secret"}


@dataclass(frozen=True)
class HarnessConfig:
    """Provider settings for one of the three harnesses."""

    name: str
    provider: str
    command: str
    model: str
    extra_args: list[str]

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "command": self.command,
            "model": self.model,
            "extra_args": list(self.extra_args),
        }


@dataclass(frozen=True)
class LimitsConfig:
    max_rounds: int
    same_failure_limit: int
    idle_timeout_seconds: int

    def to_dict(self) -> dict:
        return {
            "max_rounds": self.max_rounds,
            "same_failure_limit": self.same_failure_limit,
            "idle_timeout_seconds": self.idle_timeout_seconds,
        }


@dataclass(frozen=True)
class PolicyConfig:
    allow_network: bool
    allow_destructive_commands: bool
    tester_can_modify_source: bool

    def to_dict(self) -> dict:
        return {
            "allow_network": self.allow_network,
            "allow_destructive_commands": self.allow_destructive_commands,
            "tester_can_modify_source": self.tester_can_modify_source,
        }


@dataclass(frozen=True)
class GithubConfig:
    enabled: bool
    remote: str
    mode: str
    branch_prefix: str
    auto_commit: bool
    auto_push: bool
    auto_create_pr: bool
    wait_for_checks: bool

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "remote": self.remote,
            "mode": self.mode,
            "branch_prefix": self.branch_prefix,
            "auto_commit": self.auto_commit,
            "auto_push": self.auto_push,
            "auto_create_pr": self.auto_create_pr,
            "wait_for_checks": self.wait_for_checks,
        }


@dataclass(frozen=True)
class ProjectConfig:
    """Fully resolved configuration for one MetaCoding invocation."""

    schema_version: int
    limits: LimitsConfig
    harness: dict[str, HarnessConfig]
    policy: PolicyConfig
    github: GithubConfig
    source_path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "limits": self.limits.to_dict(),
            "harness": {name: cfg.to_dict() for name, cfg in self.harness.items()},
            "policy": self.policy.to_dict(),
            "github": self.github.to_dict(),
        }


def default_config() -> ProjectConfig:
    return ProjectConfig(
        schema_version=SCHEMA_VERSION,
        limits=LimitsConfig(max_rounds=6, same_failure_limit=2, idle_timeout_seconds=900),
        harness={
            "planner": HarnessConfig(
                name="planner", provider="codex", command="codex", model="", extra_args=[]
            ),
            "coder": HarnessConfig(
                name="coder", provider="pi", command="pi", model="", extra_args=[]
            ),
            "tester": HarnessConfig(
                name="tester", provider="codex", command="codex", model="", extra_args=[]
            ),
        },
        policy=PolicyConfig(
            allow_network=False,
            allow_destructive_commands=False,
            tester_can_modify_source=False,
        ),
        github=GithubConfig(
            enabled=False,
            remote="origin",
            mode="pull-request",
            branch_prefix="metacoding/",
            auto_commit=True,
            auto_push=False,
            auto_create_pr=False,
            wait_for_checks=True,
        ),
    )


@dataclass(frozen=True)
class CliOverrides:
    """Per-invocation overrides; never persisted to the project config."""

    planner_model: str | None = None
    coder_model: str | None = None
    tester_model: str | None = None
    planner_command: str | None = None
    coder_command: str | None = None
    tester_command: str | None = None
    max_rounds: int | None = None

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "CliOverrides":
        def opt(name: str) -> Any:
            return getattr(args, name, None)

        return cls(
            planner_model=opt("planner_model"),
            coder_model=opt("coder_model"),
            tester_model=opt("tester_model"),
            planner_command=opt("planner_command"),
            coder_command=opt("coder_command"),
            tester_command=opt("tester_command"),
            max_rounds=opt("max_rounds"),
        )


def _check_secrets(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_name = str(key).strip().lower().replace("-", "_")
            location = f"{path}.{key}" if path else str(key)
            if key_name in SECRET_FIELD_NAMES:
                raise ConfigError(
                    f"secret field '{location}' is not allowed in config.toml; "
                    "harness authentication must come from the environment"
                )
            _check_secrets(item, location)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_secrets(item, f"{path}[{index}]")


def _merge_harness(base: dict[str, HarnessConfig], data: Any) -> dict[str, HarnessConfig]:
    raw = data if isinstance(data, dict) else {}
    merged = dict(base)
    for name, current in list(merged.items()):
        section = raw.get(name)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise ConfigError(f"[harness.{name}] must be a table")
        provider = section.get("provider", current.provider)
        if provider not in VALID_PROVIDERS:
            raise ConfigError(
                f"[harness.{name}] provider must be one of {VALID_PROVIDERS}, got {provider!r}"
            )
        command = section.get("command", current.command)
        if not isinstance(command, str) or not command.strip():
            raise ConfigError(f"[harness.{name}] command must be a non-empty string")
        model = section.get("model", current.model)
        if not isinstance(model, str):
            raise ConfigError(f"[harness.{name}] model must be a string")
        extra_args = section.get("extra_args", current.extra_args)
        if not isinstance(extra_args, list) or any(
            not isinstance(arg, str) for arg in extra_args
        ):
            raise ConfigError(f"[harness.{name}] extra_args must be a list of strings")
        merged[name] = HarnessConfig(
            name=name,
            provider=provider,
            command=command,
            model=model,
            extra_args=list(extra_args),
        )
    unknown = set(raw) - set(base)
    if unknown:
        raise ConfigError(
            f"unknown harness section(s) {sorted(unknown)}; "
            f"expected one of {sorted(base)}"
        )
    return merged


def _merge_limits(base: LimitsConfig, data: Any) -> LimitsConfig:
    raw = data if isinstance(data, dict) else {}

    def positive_int(key: str, current: int, minimum: int) -> int:
        value = raw.get(key, current)
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ConfigError(f"[limits] {key} must be an integer >= {minimum}")
        return value

    return LimitsConfig(
        max_rounds=positive_int("max_rounds", base.max_rounds, 1),
        same_failure_limit=positive_int("same_failure_limit", base.same_failure_limit, 1),
        idle_timeout_seconds=positive_int("idle_timeout_seconds", base.idle_timeout_seconds, 1),
    )


def _merge_policy(base: PolicyConfig, data: Any) -> PolicyConfig:
    raw = data if isinstance(data, dict) else {}

    def flag(key: str, current: bool) -> bool:
        value = raw.get(key, current)
        if not isinstance(value, bool):
            raise ConfigError(f"[policy] {key} must be a boolean")
        return value

    return PolicyConfig(
        allow_network=flag("allow_network", base.allow_network),
        allow_destructive_commands=flag(
            "allow_destructive_commands", base.allow_destructive_commands
        ),
        tester_can_modify_source=flag("tester_can_modify_source", base.tester_can_modify_source),
    )


def _merge_github(base: GithubConfig, data: Any) -> GithubConfig:
    raw = data if isinstance(data, dict) else {}

    def string(key: str, current: str) -> str:
        value = raw.get(key, current)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"[github] {key} must be a non-empty string")
        return value

    def boolean(key: str, current: bool) -> bool:
        value = raw.get(key, current)
        if not isinstance(value, bool):
            raise ConfigError(f"[github] {key} must be a boolean")
        return value

    mode = string("mode", base.mode)
    if mode not in VALID_GITHUB_MODES:
        raise ConfigError(f"[github] mode must be one of {VALID_GITHUB_MODES}, got {mode!r}")
    return GithubConfig(
        enabled=boolean("enabled", base.enabled),
        remote=string("remote", base.remote),
        mode=mode,
        branch_prefix=string("branch_prefix", base.branch_prefix),
        auto_commit=boolean("auto_commit", base.auto_commit),
        auto_push=boolean("auto_push", base.auto_push),
        auto_create_pr=boolean("auto_create_pr", base.auto_create_pr),
        wait_for_checks=boolean("wait_for_checks", base.wait_for_checks),
    )


def _apply_overrides(config: ProjectConfig, overrides: CliOverrides) -> ProjectConfig:
    harness = dict(config.harness)
    model_overrides = {
        "planner": overrides.planner_model,
        "coder": overrides.coder_model,
        "tester": overrides.tester_model,
    }
    command_overrides = {
        "planner": overrides.planner_command,
        "coder": overrides.coder_command,
        "tester": overrides.tester_command,
    }
    for name, harness_config in harness.items():
        updates: dict[str, Any] = {}
        if model_overrides.get(name):
            updates["model"] = model_overrides[name]
        if command_overrides.get(name):
            updates["command"] = command_overrides[name]
        if updates:
            harness[name] = replace(harness_config, **updates)
    limits = config.limits
    if overrides.max_rounds is not None:
        if overrides.max_rounds < 1:
            raise ConfigError("--max-rounds must be an integer >= 1")
        limits = replace(limits, max_rounds=overrides.max_rounds)
    return replace(config, harness=harness, limits=limits)


def load_config(
    project_root: Path, overrides: CliOverrides | None = None
) -> ProjectConfig:
    """Load the effective configuration for ``project_root``."""
    base = default_config()
    data: dict = {}
    config_path = Path(project_root) / ".metacoding" / "config.toml"
    if config_path.is_file():
        try:
            with open(config_path, "rb") as handle:
                data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"invalid TOML in {config_path}: {exc}") from exc
    _check_secrets(data)

    schema_version = data.get("project", {}).get("schema_version", base.schema_version)
    if not isinstance(schema_version, int) or schema_version != SCHEMA_VERSION:
        raise ConfigError(f"unsupported schema_version {schema_version!r}; expected {SCHEMA_VERSION}")

    config = ProjectConfig(
        schema_version=schema_version,
        limits=_merge_limits(base.limits, data.get("limits")),
        harness=_merge_harness(base.harness, data.get("harness")),
        policy=_merge_policy(base.policy, data.get("policy")),
        github=_merge_github(base.github, data.get("github")),
        source_path=config_path if config_path.is_file() else None,
    )
    if overrides is not None:
        config = _apply_overrides(config, overrides)
    return config
