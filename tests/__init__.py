"""Entry point for the KingbaseES compatibility test suite."""

from pathlib import Path
import sys

import pytest


if __name__ == "__main__":
    kes_tests = Path(__file__).parent / "kes"
    raise SystemExit(pytest.main([str(kes_tests), *sys.argv[1:]]))
