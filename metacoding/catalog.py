"""Model catalogs for the harness CLIs.

Enumerates the models a harness CLI can actually use, so operators pick
from a list instead of typing error-prone model names:

- codex: reads ``$CODEX_HOME/model-catalog.json`` (default ``~/.codex``)
  plus the configured default model from ``config.toml``.
- pi: runs ``pi --list-models`` and parses the table.
- fake: no models.

Model ids are stored exactly the way each CLI expects them: bare slugs
for codex, ``provider/model`` for pi.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

PI_LIST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class CatalogEntry:
    provider: str
    model: str
    label: str
    context: str = ""
    current: bool = False


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))


def codex_models(
    current_model: str = "", *, include_configured_default: bool = True
) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    catalog_path = _codex_home() / "model-catalog.json"
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
    models = payload.get("models") if isinstance(payload, dict) else None
    if isinstance(models, list):
        for item in models:
            if not isinstance(item, dict):
                continue
            if str(item.get("visibility", "list")).lower() == "hide":
                continue
            slug = str(item.get("slug") or item.get("id") or "").strip()
            if not slug:
                continue
            entries.append(
                CatalogEntry(
                    provider="codex",
                    model=slug,
                    label=str(item.get("display_name") or slug),
                    current=slug == current_model,
                )
            )
    if include_configured_default:
        # Surface the CLI's configured default model (from its config.toml)
        # even when the catalog file is missing.
        default = _codex_configured_default()
        if default and not any(entry.model == default for entry in entries):
            entries.append(
                CatalogEntry(
                    provider="codex",
                    model=default,
                    label=f"{default} (codex default)",
                    current=default == current_model,
                )
            )
    return entries


def _codex_configured_default() -> str:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        import tomli as tomllib

    try:
        with open(_codex_home() / "config.toml", "rb") as handle:
            data = tomllib.load(handle)
    except Exception:
        return ""
    value = data.get("model") if isinstance(data, dict) else None
    return str(value) if isinstance(value, str) and value else ""


def pi_models(command: str = "pi", current_model: str = "") -> list[CatalogEntry]:
    try:
        result = subprocess.run(
            [command, "--list-models"],
            capture_output=True,
            text=True,
            timeout=PI_LIST_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    entries: list[CatalogEntry] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0].lower() == "provider":
            continue
        provider, model_id = parts[0], parts[1]
        context = parts[2] if len(parts) > 2 else ""
        full = f"{provider}/{model_id}"
        entries.append(
            CatalogEntry(
                provider=provider,
                model=full,
                label=model_id,
                context=context,
                current=full == current_model or model_id == current_model,
            )
        )
    return entries


def list_models(harness_config, current_model: str = "") -> list[CatalogEntry]:
    """Models usable by one harness, in that CLI's own id format."""
    if harness_config.provider == "codex":
        return codex_models(current_model)
    if harness_config.provider == "pi":
        return pi_models(harness_config.command, current_model)
    return []


def model_exists(harness_config, model: str) -> bool | None:
    """True/False when the catalog is available; None when it could not be
    read (offline, missing files) — never block a set on that."""
    entries = list_models(harness_config, current_model=model)
    if not entries:
        return None
    return any(entry.current for entry in entries)
