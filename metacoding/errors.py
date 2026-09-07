"""Error taxonomy for the MetaCoding host.

All host-raised errors derive from :class:`MetaCodingError` so callers can
map failures to operator-facing outcomes without catching bare exceptions.
"""

from __future__ import annotations

from typing import Any


class MetaCodingError(Exception):
    """Base class for all MetaCoding host errors."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class ConfigError(MetaCodingError):
    """Invalid, missing, or forbidden project configuration."""


class ProtocolError(MetaCodingError):
    """A structured payload is missing required fields or has bad values."""


class PersistenceError(MetaCodingError):
    """Run records are unreadable, corrupt, or cannot be written."""


class LockError(MetaCodingError):
    """Another MetaCoding process owns the project lock."""

    def __init__(
        self,
        message: str,
        *,
        lock_path: str = "",
        run_id: str = "",
        pid: int | None = None,
        host: str = "",
    ) -> None:
        super().__init__(message)
        self.lock_path = lock_path
        self.run_id = run_id
        self.pid = pid
        self.host = host


class HarnessError(MetaCodingError):
    """Base class for harness invocation failures."""


class HarnessCommandMissing(HarnessError):
    """The configured harness command is not installed."""


class HarnessTimeout(HarnessError):
    """The harness produced no output for longer than the idle timeout."""

    def __init__(self, message: str, *, command: list[str], idle_seconds: float) -> None:
        super().__init__(message, command=command, idle_seconds=idle_seconds)
        self.command = command
        self.idle_seconds = idle_seconds


class HarnessNonZeroExit(HarnessError):
    """The harness process exited with a non-zero status."""

    def __init__(self, message: str, *, command: list[str], exit_code: int) -> None:
        super().__init__(message, command=command, exit_code=exit_code)
        self.command = command
        self.exit_code = exit_code


class MalformedHarnessOutput(HarnessError):
    """Harness output could not be parsed as the required structure."""


class PolicyViolationError(MetaCodingError):
    """A deterministic host gate rejected the run."""


class GitDeliveryError(MetaCodingError):
    """Git or GitHub delivery failed its safety checks."""
