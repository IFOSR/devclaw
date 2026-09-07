"""Harness adapters: provider-specific command construction and parsing."""

from metacoding.harnesses.base import Harness, HarnessContext, HarnessTask
from metacoding.harnesses.codex_planner import CodexPlanner
from metacoding.harnesses.codex_tester import CodexTester
from metacoding.harnesses.pi_coder import PiCoder

__all__ = [
    "Harness",
    "HarnessContext",
    "HarnessTask",
    "CodexPlanner",
    "PiCoder",
    "CodexTester",
    "create_harness",
]


def create_harness(name: str, harness_config, project_root, scenario: dict | None = None):
    """Build the harness instance for ``name`` (planner/coder/tester)."""
    from metacoding.harnesses.fake import FakeCoder, FakePlanner, FakeTester

    factories = {
        ("planner", "codex"): lambda: CodexPlanner(harness_config, project_root),
        ("coder", "pi"): lambda: PiCoder(harness_config, project_root),
        ("tester", "codex"): lambda: CodexTester(harness_config, project_root),
        ("planner", "fake"): lambda: FakePlanner(harness_config, project_root, scenario),
        ("coder", "fake"): lambda: FakeCoder(harness_config, project_root, scenario),
        ("tester", "fake"): lambda: FakeTester(harness_config, project_root, scenario),
    }
    factory = factories.get((name, harness_config.provider))
    if factory is None:
        raise ValueError(
            f"no harness adapter for name={name!r} provider={harness_config.provider!r}"
        )
    return factory()
