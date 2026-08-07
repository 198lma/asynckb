"""Integration tests for asyncpg connection configuration against KES."""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg
import pytest

from tests.kes.support.config import KESConfig, unique_object_name


pytestmark = pytest.mark.integration


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

        connection = await asyncpg.connect(
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
        environment_connection = await asyncpg.connect(
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


def test_password_callbacks_command_timeout_and_terminate(
    kes_config: KESConfig,
) -> None:
    """测试点：同步/异步密码回调、默认查询超时和强制终止均保持兼容。"""
    async def scenario() -> None:
        callback_calls: list[str] = []

        def sync_password() -> str:
            callback_calls.append("sync")
            return kes_config.password

        async def async_password() -> str:
            callback_calls.append("async")
            return kes_config.password

        for password_callback in (sync_password, async_password):
            connection = await asyncpg.connect(
                **kes_config.connection_kwargs(
                    password=password_callback,
                    command_timeout=0.01,
                )
            )
            try:
                with pytest.raises(asyncio.TimeoutError):
                    await connection.fetchval("SELECT pg_sleep(1)")
                assert await connection.fetchval(
                    kes_config.select_one,
                    timeout=1,
                ) == 1
            finally:
                connection.terminate()
            assert connection.is_closed()

        assert callback_calls == ["sync", "async"]

    asyncio.run(scenario())


def test_prefer_standby_closes_unchosen_kes_connection_candidates(
    kes_config: KESConfig,
) -> None:
    """测试点：prefer_standby 多候选连接只保留被选 KES 会话。"""
    async def scenario() -> None:
        application_name = unique_object_name(
            "prefer_standby", kes_config.mode
        )
        connection = await asyncpg.connect(
            **kes_config.connection_kwargs(
                host=[kes_config.host, kes_config.host],
                port=[kes_config.port, kes_config.port],
                target_session_attrs="prefer-standby",
                server_settings={"application_name": application_name},
            )
        )
        try:
            await asyncio.sleep(0.1)
            assert await connection.fetchval(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE application_name = $1",
                application_name,
            ) == 1
            assert await connection.fetchval(kes_config.select_one) == 1
        finally:
            await connection.close()

    asyncio.run(scenario())
