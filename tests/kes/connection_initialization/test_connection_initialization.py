"""Tests for the connection initialization requirement module."""

from __future__ import annotations

import asyncio
from pathlib import Path
import asynckb
import pytest
from tests.kes.support.config import KESConfig
from asynckb import connect_utils
from asynckb import kes


@pytest.mark.case_id("KB-CONN-001")
@pytest.mark.integration
def test_connection_detects_kes_mode_without_explicit_option(
    kes_config: KESConfig,
) -> None:
    """测试点：不传 kes_mode 时驱动通过服务端属性自动识别兼容模式。"""
    async def scenario() -> None:
        options = kes_config.connection_kwargs()
        options.pop("kes_mode")
        connection = await asynckb.connect(**options)
        try:
            assert connection.get_kes_mode() == kes_config.mode
            assert await connection.fetchval(kes_config.select_one) == 1
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-CONN-002")
@pytest.mark.integration
def test_service_file_passfile_and_primary_target_connect(
    kes_config: KESConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试点：service file、passfile 和 primary 目标筛选可组合连接 KES。"""
    async def scenario() -> None:
        passfile = tmp_path / "pgpass"
        passfile.write_text(
            f"{kes_config.host}:{kes_config.port}:{kes_config.database}:"
            f"{kes_config.user}:{kes_config.password}\n",
            encoding="utf-8",
        )
        passfile.chmod(0o600)

        servicefile = tmp_path / "pg_service.conf"
        servicefile.write_text(
            "[kes]\n"
            f"host={kes_config.host}\n"
            f"port={kes_config.port}\n"
            f"user={kes_config.user}\n"
            f"dbname={kes_config.database}\n"
            "sslmode=disable\n"
            f"kes_mode={kes_config.mode}\n",
            encoding="utf-8",
        )

        connection = await asynckb.connect(
            service="kes",
            servicefile=servicefile,
            passfile=passfile,
            target_session_attrs="primary",
        )
        try:
            assert connection._addr == (kes_config.host, kes_config.port)
            assert connection.get_kes_mode() == kes_config.mode
            assert await connection.fetchval(kes_config.select_one) == 1
        finally:
            await connection.close()

        monkeypatch.setenv("PGSERVICE", "kes")
        monkeypatch.setenv("PGSERVICEFILE", str(servicefile))
        environment_connection = await asynckb.connect(
            passfile=passfile,
            target_session_attrs="primary",
        )
        try:
            assert environment_connection.get_kes_mode() == kes_config.mode
            assert await environment_connection.fetchval(
                kes_config.select_one
            ) == 1
        finally:
            await environment_connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-CONN-005")
@pytest.mark.unit
def test_mode_normalization_accepts_supported_names_and_rejects_unknown_names(
) -> None:
    """测试点：模式名称大小写归一化，且不允许 PostgreSQL 等非 KES 模式。"""
    assert kes.normalize_mode(None) is None
    assert kes.normalize_mode("MySQL") == "mysql"
    assert kes.normalize_mode("ORACLE") == "oracle"
    assert kes.normalize_mode("SQLSERVER") == "sqlserver"
    with pytest.raises(asynckb.ClientConfigurationError):
        kes.normalize_mode("postgres")


@pytest.mark.case_id("KB-CONN-006")
@pytest.mark.unit
def test_dsn_parser_extracts_encoded_kes_mode_and_preserves_other_settings(
) -> None:
    """测试点：DSN 解码 kes_mode、保留服务端参数并允许显式模式覆盖。"""
    dsn = (
        "postgresql://system:test-password@127.0.0.1:54321/test?"
        "%6b%65%73%5f%6d%6f%64%65=mysql&application_name=kes_test&"
        "sslmode=disable"
    )
    arguments = {
        "dsn": dsn,
        "host": None,
        "port": None,
        "user": None,
        "password": None,
        "passfile": None,
        "database": None,
        "command_timeout": None,
        "statement_cache_size": 100,
        "max_cached_statement_lifetime": 300,
        "max_cacheable_statement_size": 15360,
        "ssl": None,
        "direct_tls": None,
        "server_settings": None,
        "target_session_attrs": None,
        "krbsrvname": None,
        "gsslib": None,
        "service": None,
        "servicefile": None,
    }

    _, parameters, config = connect_utils._parse_connect_arguments(
        **arguments,
        kes_mode=None,
    )
    assert config.kes_mode == "mysql"
    assert parameters.server_settings == {"application_name": "kes_test"}

    _, parameters, config = connect_utils._parse_connect_arguments(
        **arguments,
        kes_mode="oracle",
    )
    assert config.kes_mode == "oracle"
    assert "kes_mode" not in parameters.server_settings


@pytest.mark.case_id("KB-CONN-007")
@pytest.mark.unit
def test_connect_timeout_aborts_stalled_protocol_handshake() -> None:
    """测试点：建连总超时会中止已建立 TCP 但不响应的协议握手。"""
    async def scenario() -> None:
        release_handlers = asyncio.Event()
        handler_tasks: set[asyncio.Task[None]] = set()

        async def stalled_server(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            task = asyncio.current_task()
            assert task is not None
            handler_tasks.add(task)
            try:
                await release_handlers.wait()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(
            stalled_server, "127.0.0.1", 0
        )
        port = server.sockets[0].getsockname()[1]
        started = asyncio.get_running_loop().time()
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asynckb.connect(
                    host="127.0.0.1",
                    port=port,
                    user="system",
                    password="unused",
                    database="test",
                    kes_mode="mysql",
                    ssl=False,
                    timeout=0.05,
                )
            elapsed = asyncio.get_running_loop().time() - started
            assert 0.04 <= elapsed < 1
        finally:
            release_handlers.set()
            server.close()
            await server.wait_closed()
            if handler_tasks:
                await asyncio.gather(*handler_tasks)

    asyncio.run(scenario())
