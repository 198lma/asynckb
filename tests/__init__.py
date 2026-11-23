# Copyright (C) 2016-present the asyncpg authors and contributors
# <see AUTHORS file>
#
# Released under the Apache 2.0 License.
# Modified for asynckb: replace the upstream test runner with the KES suite.

"""Entry point for the KingbaseES compatibility test suite."""

from pathlib import Path
import sys

import pytest


if __name__ == "__main__":
    kes_tests = Path(__file__).parent / "kes"
    raise SystemExit(pytest.main([str(kes_tests), *sys.argv[1:]]))
