from __future__ import annotations

import os
from pathlib import Path

import asyncpg
import pytest

from tests.kes.support.config import KESConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--kes-mode",
        action="store",
        choices=("mysql", "oracle", "sqlserver", "all"),
        default=os.environ.get("ASYNCPG_KES_MODE", "all"),
        help="KES compatibility mode to test (default: all)",
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "kes_mode" not in metafunc.fixturenames:
        return

    selected = metafunc.config.getoption("--kes-mode")
    modes = (
        ("mysql", "oracle", "sqlserver")
        if selected == "all"
        else (selected,)
    )
    metafunc.parametrize("kes_mode", modes, ids=modes)


def _config_for_mode(
    request: pytest.FixtureRequest,
    mode: str,
) -> KESConfig:
    selected = request.config.getoption("--kes-mode")
    if selected not in {"all", mode}:
        pytest.skip(f"{mode} test excluded by --kes-mode={selected}")
    if not os.environ.get("ASYNCPG_KES_PASSWORD"):
        pytest.skip("set ASYNCPG_KES_PASSWORD to run KES integration tests")
    return KESConfig.from_env(mode)


@pytest.fixture
def kes_config(
    request: pytest.FixtureRequest,
    kes_mode: str,
) -> KESConfig:
    return _config_for_mode(request, kes_mode)


@pytest.fixture
def mysql_config(request: pytest.FixtureRequest) -> KESConfig:
    return _config_for_mode(request, "mysql")


@pytest.fixture
def oracle_config(request: pytest.FixtureRequest) -> KESConfig:
    return _config_for_mode(request, "oracle")


@pytest.fixture
def sqlserver_config(request: pytest.FixtureRequest) -> KESConfig:
    return _config_for_mode(request, "sqlserver")


def pytest_report_header() -> list[str]:
    return [
        f"project root: {PROJECT_ROOT}",
        f"asyncpg source: {Path(asyncpg.__file__).resolve()}",
        f"asyncpg version: {asyncpg.__version__}",
    ]
