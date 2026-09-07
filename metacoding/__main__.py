"""Module entry point for ``python3 -m metacoding``."""

from __future__ import annotations

import sys

from metacoding.cli import main

if __name__ == "__main__":
    sys.exit(main())
