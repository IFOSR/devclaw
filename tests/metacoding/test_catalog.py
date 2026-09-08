"""Model catalog enumeration and the interactive picker."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from metacoding.catalog import (
    CatalogEntry,
    codex_models,
    list_models,
    model_exists,
    pi_models,
)
from metacoding.cli import EXIT_OK, EXIT_USAGE, main as cli_main
from metacoding.config import HarnessConfig
from metacoding.service import MetaCodingService


@pytest.fixture()
def codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


def write_codex_catalog(home: Path, slugs: list[str], default: str | None = None) -> None:
    (home / "model-catalog.json").write_text(
        json.dumps(
            {
                "models": [
                    {"slug": slug, "display_name": slug.upper(), "visibility": "list"}
                    for slug in slugs
                ]
                + [
                    {
                        "slug": "hidden-model",
                        "display_name": "HIDDEN",
                        "visibility": "hide",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    if default:
        (home / "config.toml").write_text(f'model = "{default}"\n', encoding="utf-8")


class PickerTtyInput(io.StringIO):
    """Injected stdin that claims to be interactive for the picker."""

    def isatty(self) -> bool:
        return True


# --- codex catalog ---------------------------------------------------------------


def test_codex_models_from_catalog(codex_home: Path) -> None:
    write_codex_catalog(codex_home, ["gpt-5.6-sol", "gpt-5.5"], default="gpt-5.6-sol")
    entries = codex_models(current_model="gpt-5.6-sol")
    slugs = [entry.model for entry in entries]
    assert slugs == ["gpt-5.6-sol", "gpt-5.5"]  # hidden entries filtered
    assert entries[0].current is True and entries[0].label == "GPT-5.6-SOL"


def test_codex_models_without_catalog_keeps_default(codex_home: Path) -> None:
    (codex_home / "config.toml").write_text('model = "relay-default"\n', encoding="utf-8")
    entries = codex_models(current_model="relay-default")
    assert [entry.model for entry in entries] == ["relay-default"]
    assert entries[0].current


def test_codex_models_missing_everything(codex_home: Path) -> None:
    assert codex_models() == []


# --- pi catalog ------------------------------------------------------------------


def test_pi_models_parses_table(monkeypatch: pytest.MonkeyPatch) -> None:
    table = (
        "provider       model                    context  max-out  thinking  images\n"
        "anthropic      claude-sonnet-5          1M       64K      yes       yes\n"
        "zai-coding-cn  glm-5.3                  1M       131.1K   yes       no\n"
    )

    class Result:
        returncode = 0
        stdout = table

    monkeypatch.setattr(
        "metacoding.catalog.subprocess.run", lambda *a, **k: Result()
    )
    entries = pi_models(current_model="zai-coding-cn/glm-5.3")
    assert [entry.model for entry in entries] == [
        "anthropic/claude-sonnet-5",
        "zai-coding-cn/glm-5.3",
    ]
    assert entries[1].current is True
    assert entries[1].context == "1M"


def test_pi_models_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise OSError("no pi")

    monkeypatch.setattr("metacoding.catalog.subprocess.run", boom)
    assert pi_models() == []


def test_list_models_dispatches_by_provider(codex_home: Path) -> None:
    write_codex_catalog(codex_home, ["m1"])
    codex = HarnessConfig("planner", "codex", "codex", "m1", [])
    assert [e.model for e in list_models(codex, "m1")] == ["m1"]
    fake = HarnessConfig("coder", "fake", "python3", "", [])
    assert list_models(fake) == []
    assert model_exists(fake, "x") is None


# --- metacoding models command ------------------------------------------------------


def test_cli_models_lists_catalog_with_selection_marker(
    tmp_path: Path, codex_home: Path, capsys
) -> None:
    write_codex_catalog(codex_home, ["gpt-5.6-sol", "gpt-5.5"])
    service = MetaCodingService(project_root=tmp_path)
    service.config_set("planner.model", "gpt-5.5")
    capsys.readouterr()
    assert cli_main(["--project-root", str(tmp_path), "models", "planner"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "gpt-5.6-sol" in out and "gpt-5.5" in out
    assert out.count("← current") == 1


def test_cli_models_requires_harness_argument(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        cli_main(["--project-root", str(tmp_path), "models"])


# --- config set without value: interactive picker ------------------------------------


def test_config_set_model_without_value_non_tty_lists_models(tmp_path: Path, capsys):
    code = cli_main(
        ["--project-root", str(tmp_path), "config", "set", "coder.model"]
    )
    assert code == EXIT_USAGE
    out = capsys.readouterr().out
    assert "provide a value" in out or "non-interactive" in out


def test_pick_model_by_number(tmp_path: Path, codex_home: Path) -> None:
    write_codex_catalog(codex_home, ["alpha", "beta", "gamma"])
    service = MetaCodingService(project_root=tmp_path)
    outcome = service.pick_model("planner", stdin=PickerTtyInput("2\n"), stdout=io.StringIO())
    assert outcome.exit_code == EXIT_OK
    assert service.config_get("planner.model").message == "planner.model = beta"


def test_pick_model_zero_clears_to_default(tmp_path: Path, codex_home: Path) -> None:
    write_codex_catalog(codex_home, ["alpha", "beta"])
    service = MetaCodingService(project_root=tmp_path)
    service.config_set("planner.model", "alpha")
    outcome = service.pick_model("planner", stdin=PickerTtyInput("0\n"), stdout=io.StringIO())
    assert outcome.exit_code == EXIT_OK
    # cleared: empty model means "use the CLI default"
    assert "(cli default)" in service.config_get("planner.model").message


def test_pick_model_enter_keeps_current(tmp_path: Path, codex_home: Path) -> None:
    write_codex_catalog(codex_home, ["alpha", "beta"])
    service = MetaCodingService(project_root=tmp_path)
    service.config_set("planner.model", "beta")
    outcome = service.pick_model("planner", stdin=PickerTtyInput("\n"), stdout=io.StringIO())
    assert outcome.exit_code == EXIT_OK
    assert service.config_get("planner.model").message.endswith("beta")


def test_pick_model_retries_on_bad_input(tmp_path: Path, codex_home: Path) -> None:
    write_codex_catalog(codex_home, ["alpha", "beta"])
    service = MetaCodingService(project_root=tmp_path)
    outcome = service.pick_model(
        "planner", stdin=PickerTtyInput("99\nxyz\n1\n"), stdout=io.StringIO()
    )
    assert outcome.exit_code == EXIT_OK
    assert service.config_get("planner.model").message.endswith("alpha")


def test_pick_model_eof_cancels(tmp_path: Path, codex_home: Path) -> None:
    write_codex_catalog(codex_home, ["alpha"])
    service = MetaCodingService(project_root=tmp_path)
    outcome = service.pick_model("planner", stdin=PickerTtyInput(""), stdout=io.StringIO())
    assert outcome.exit_code == EXIT_USAGE


# --- set-time validation warning -------------------------------------------------------


def test_config_set_warns_for_model_outside_catalog(tmp_path: Path, codex_home: Path):
    write_codex_catalog(codex_home, ["good-model"])
    service = MetaCodingService(project_root=tmp_path)
    outcome = service.config_set("planner.model", "typo-moddel")
    assert outcome.exit_code == EXIT_OK  # still set (catalogs can be partial)
    assert any("not in the" in line and "list" in line for line in outcome.lines)


def test_config_set_no_warning_for_known_model(tmp_path: Path, codex_home: Path):
    write_codex_catalog(codex_home, ["good-model"])
    service = MetaCodingService(project_root=tmp_path)
    outcome = service.config_set("planner.model", "good-model")
    assert not any("not in the" in line for line in outcome.lines)
