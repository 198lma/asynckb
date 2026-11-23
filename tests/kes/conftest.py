from __future__ import annotations

import json
import os
from pathlib import Path

import asynckb
import pytest

from tests.kes.support.config import KESConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    manifest_path = Path(__file__).with_name("case_manifest.json")
    cases = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in cases}
    targets = {case["nodeid"] for case in cases}
    if len(by_id) != len(cases) or len(targets) != len(cases):
        raise pytest.UsageError(
            "case_id manifest contains duplicate IDs or targets"
        )

    for item in items:
        relative = item.path.relative_to(PROJECT_ROOT).as_posix()
        if not relative.startswith("tests/kes/"):
            continue
        target = f"{relative}::{item.originalname or item.name}"
        markers = list(item.iter_markers("case_id"))
        if len(markers) != 1 or len(markers[0].args) != 1:
            raise pytest.UsageError(f"case_id: expected one ID for {target}")
        case_id = markers[0].args[0]
        if not isinstance(case_id, str) or case_id not in by_id:
            raise pytest.UsageError(
                f"case_id: unknown ID {case_id!r}: {target}"
            )
        case = by_id[case_id]
        if case["nodeid"] != target:
            raise pytest.UsageError(
                f"case_id: {case_id} belongs to {case['nodeid']}, not {target}"
            )
        item.extra_keyword_matches.add(case_id)
        item.user_properties.extend([
            ("case_id", case_id),
            ("case_title", case["title"]),
            ("case_source", target),
        ])


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--kes-auth-configure-server", action="store_true", default=False,
        help=("Temporarily create local test roles/HBA rules; "
              "restore on exit"),
    )
    parser.addoption(
        "--kes-auth-isolated", action="store_true", default=False,
        help=("Create disposable local KES instances for "
              "external authentication"),
    )
    parser.addoption(
        "--kes-mode",
        action="store",
        choices=("mysql", "oracle", "sqlserver", "all"),
        default=os.environ.get("ASYNCKB_KES_MODE", "all"),
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
    if not os.environ.get("ASYNCKB_KES_PASSWORD"):
        pytest.skip("set ASYNCKB_KES_PASSWORD to run KES integration tests")
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
        f"asynckb source: {Path(asynckb.__file__).resolve()}",
        f"asynckb version: {asynckb.__version__}",
    ]
