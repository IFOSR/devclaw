from __future__ import annotations

import re
from pathlib import Path

from devclaw.core.models import AcceptanceContract, ProjectBrief


def generate_acceptance_checks(
    project_root: Path,
    brief: ProjectBrief,
    contract: AcceptanceContract,
    generated_script: str | None = None,
) -> Path:
    path = project_root / ".devclaw" / "checks" / "acceptance_checks.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    if generated_script and _looks_like_python_check(generated_script):
        content = generated_script
    else:
        script, expected = _extract_python_print_expectation(brief.goal)
        if script and expected:
            content = _python_cli_check(script, expected)
        else:
            content = _metadata_check(contract)
    path.write_text(content, encoding="utf-8")
    return path


def _looks_like_python_check(content: str) -> bool:
    return "def main" in content and "raise SystemExit(main())" in content


def _extract_python_print_expectation(goal: str) -> tuple[str | None, str | None]:
    match = re.search(
        r"running\s+python3\s+([^\s]+)\s+prints\s+exactly:?\s+(.+)$",
        goal,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None
    return match.group(1).strip(), match.group(2).strip()


def _python_cli_check(script: str, expected: str) -> str:
    return f'''import subprocess
import sys


def main() -> int:
    result = subprocess.run(
        [sys.executable, {script!r}],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr or result.stdout)
        return result.returncode
    actual = result.stdout.strip()
    if actual != {expected!r}:
        print(f"expected {{ {expected!r} }}, got {{actual!r}}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _metadata_check(contract: AcceptanceContract) -> str:
    required = [item.id for item in contract.blocking_items()]
    return f'''from pathlib import Path


def main() -> int:
    required = {required!r}
    if not required:
        return 0
    if not Path(".devclaw/acceptance-contract.json").exists():
        print("acceptance contract missing")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
