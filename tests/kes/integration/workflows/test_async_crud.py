"""Readable asynchronous CRUD workflows shared by all KES modes."""

from __future__ import annotations

import asyncio

import asyncpg
import pytest

from tests.kes.support.config import KESConfig, drop_table, unique_object_name


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _pool_options(config: KESConfig) -> dict[str, object]:
    options = config.connection_kwargs()
    options.pop("timeout")
    return options


def _user_columns(mode: str) -> str:
    if mode == "oracle":
        return (
            "id NUMBER(10) PRIMARY KEY, "
            "username VARCHAR2(50) NOT NULL UNIQUE, "
            "age NUMBER(3)"
        )
    return (
        "id INT PRIMARY KEY, "
        "username VARCHAR(50) NOT NULL UNIQUE, "
        "age INT"
    )


async def _create_users_table(
    connection: asyncpg.Connection,
    table: str,
    mode: str,
) -> None:
    await connection.execute(
        f"CREATE TABLE {table} ({_user_columns(mode)})"
    )


async def test_async_connection_crud_round_trip(
    kes_config: KESConfig,
) -> None:
    """测试点：异步单连接完整执行新增、查询、更新和删除并返回正确状态。"""
    table = unique_object_name("async_crud", kes_config.mode)
    connection = await asyncpg.connect(**kes_config.connection_kwargs())
    try:
        await _create_users_table(connection, table, kes_config.mode)

        assert await connection.execute(
            f"INSERT INTO {table} (id, username, age) VALUES ($1, $2, $3)",
            1,
            "alice",
            24,
        ) == "INSERT 0 1"
        assert await connection.executemany(
            f"INSERT INTO {table} (id, username, age) VALUES ($1, $2, $3)",
            [(2, "bob", 30), (3, "carol", 36)],
        ) is None

        assert await connection.fetchval(
            f"SELECT count(*) FROM {table}"
        ) == 3
        alice = await connection.fetchrow(
            f"SELECT id, username, age FROM {table} WHERE id = $1", 1
        )
        assert dict(alice) == {"id": 1, "username": "alice", "age": 24}

        age_parameter = (
            "CAST($1 AS SIGNED)"
            if kes_config.mode == "mysql"
            else "$1"
        )
        rows = await connection.fetch(
            f"SELECT id, username FROM {table} "
            f"WHERE age >= {age_parameter} ORDER BY id",
            30,
        )
        assert [tuple(row) for row in rows] == [(2, "bob"), (3, "carol")]

        prepared = await connection.prepare(
            f"SELECT username FROM {table} WHERE id = $1"
        )
        assert await prepared.fetchval(2) == "bob"

        assert await connection.execute(
            f"UPDATE {table} SET age = $1 WHERE id = $2", 31, 2
        ) == "UPDATE 1"
        assert await connection.fetchval(
            f"SELECT age FROM {table} WHERE id = $1", 2
        ) == 31

        assert await connection.execute(
            f"DELETE FROM {table} WHERE id = $1", 3
        ) == "DELETE 1"
        assert await connection.fetchval(
            f"SELECT count(*) FROM {table}"
        ) == 2
    finally:
        await drop_table(connection, table)
        await connection.close()

    assert connection.is_closed()


async def test_async_crud_uses_test_database_default_schema(
    kes_config: KESConfig,
) -> None:
    """测试点：test 数据库不指定 schema 时可在默认 schema 完成异步 CRUD。"""
    table = unique_object_name("async_default_schema", kes_config.mode)
    connection = await asyncpg.connect(**kes_config.connection_kwargs())
    try:
        default_schema = await connection.fetchval("SELECT current_schema")
        assert isinstance(default_schema, str) and default_schema

        await _create_users_table(connection, table, kes_config.mode)
        await connection.execute(
            f"INSERT INTO {table} VALUES ($1, $2, $3)",
            1,
            f"{kes_config.mode}-default-schema",
            28,
        )
        assert await connection.fetchval(
            f"SELECT username FROM {table} WHERE id = $1", 1
        ) == f"{kes_config.mode}-default-schema"
        assert await connection.fetchval(
            f"SELECT count(*) FROM {table}"
        ) == 1
    finally:
        await drop_table(connection, table)
        await connection.close()


async def test_async_pool_runs_concurrent_crud_tasks(
    kes_config: KESConfig,
) -> None:
    """测试点：连接池并发调度异步 CRUD 任务且所有连接最终归还。"""
    table = unique_object_name("async_pool_crud", kes_config.mode)
    cleanup = await asyncpg.connect(**kes_config.connection_kwargs())
    pool = await asyncpg.create_pool(
        **_pool_options(kes_config), min_size=1, max_size=2
    )
    try:
        await _create_users_table(cleanup, table, kes_config.mode)

        async def create_and_read_user(user_id: int) -> tuple[int, str]:
            async with pool.acquire() as connection:
                async with connection.transaction():
                    username = f"user-{user_id}"
                    status = await connection.execute(
                        f"INSERT INTO {table} (id, username, age) "
                        "VALUES ($1, $2, $3)",
                        user_id,
                        username,
                        20 + user_id,
                    )
                    assert status == "INSERT 0 1"
                    await asyncio.sleep(0)
                    stored_name = await connection.fetchval(
                        f"SELECT username FROM {table} WHERE id = $1",
                        user_id,
                    )
                    return user_id, stored_name

        results = await asyncio.gather(
            *(create_and_read_user(user_id) for user_id in range(1, 13))
        )
        assert results == [
            (user_id, f"user-{user_id}") for user_id in range(1, 13)
        ]
        assert await pool.fetchval(f"SELECT count(*) FROM {table}") == 12
        assert pool.get_idle_size() == pool.get_size()
    finally:
        await pool.close()
        await drop_table(cleanup, table)
        await cleanup.close()

    assert pool.is_closing()


async def test_async_transaction_exception_rolls_back_and_recovers(
    kes_config: KESConfig,
) -> None:
    """测试点：异步事务中的业务异常自动回滚且同一连接可继续提交。"""
    table = unique_object_name("async_tx_error", kes_config.mode)
    connection = await asyncpg.connect(**kes_config.connection_kwargs())
    try:
        await _create_users_table(connection, table, kes_config.mode)

        with pytest.raises(RuntimeError, match="simulated async failure"):
            async with connection.transaction():
                await connection.execute(
                    f"INSERT INTO {table} VALUES ($1, $2, $3)",
                    1,
                    "rollback-user",
                    20,
                )
                await asyncio.sleep(0)
                raise RuntimeError("simulated async failure")

        assert await connection.fetchval(
            f"SELECT count(*) FROM {table}"
        ) == 0

        async with connection.transaction():
            await connection.execute(
                f"INSERT INTO {table} VALUES ($1, $2, $3)",
                2,
                "committed-user",
                21,
            )
        assert await connection.fetchval(
            f"SELECT username FROM {table} WHERE id = $1", 2
        ) == "committed-user"
    finally:
        await drop_table(connection, table)
        await connection.close()


async def test_cancelled_async_transaction_rolls_back_and_releases_pool_slot(
    kes_config: KESConfig,
) -> None:
    """测试点：取消异步事务任务会回滚数据并及时归还连接池槽位。"""
    table = unique_object_name("async_tx_cancel", kes_config.mode)
    cleanup = await asyncpg.connect(**kes_config.connection_kwargs())
    pool = await asyncpg.create_pool(
        **_pool_options(kes_config), min_size=1, max_size=1
    )
    write_started = asyncio.Event()

    async def cancellable_write() -> None:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    f"INSERT INTO {table} VALUES ($1, $2, $3)",
                    1,
                    "cancelled-user",
                    22,
                )
                write_started.set()
                await asyncio.Event().wait()

    try:
        await _create_users_table(cleanup, table, kes_config.mode)
        task = asyncio.create_task(cancellable_write())
        await asyncio.wait_for(write_started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async with pool.acquire(timeout=1) as connection:
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 0
        assert pool.get_idle_size() == 1
    finally:
        await pool.close()
        await drop_table(cleanup, table)
        await cleanup.close()
