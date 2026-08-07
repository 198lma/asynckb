"""Integration tests for asyncpg pool lifecycle and resilience on KES."""

from __future__ import annotations

import asyncio

import asyncpg
import pytest

from tests.kes.support.config import KESConfig, drop_table, unique_object_name


pytestmark = pytest.mark.integration


def _pool_options(config: KESConfig) -> dict[str, object]:
    options = config.connection_kwargs()
    options.pop("timeout")
    return options


def _sleep_query(mode: str) -> str:
    suffix = " FROM dual" if mode == "oracle" else ""
    return f"SELECT pg_sleep(1){suffix}"


async def _wait_until(predicate, *, timeout: float = 2) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise asyncio.TimeoutError("condition did not become true")
        await asyncio.sleep(0.01)


def test_cancelled_pool_waiter_does_not_consume_capacity(
    kes_config: KESConfig,
) -> None:
    """测试点：等待连接的任务被取消后不占用 holder，连接池容量可立即恢复。"""
    async def scenario() -> None:
        pool = await asyncpg.create_pool(
            **_pool_options(kes_config), min_size=1, max_size=1
        )
        held = await pool.acquire()
        try:
            async def wait_for_connection() -> asyncpg.Connection:
                return await pool.acquire(timeout=5)

            waiter = asyncio.create_task(wait_for_connection())
            await asyncio.sleep(0.02)
            assert not waiter.done()
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter

            await pool.release(held)
            held = None
            async with pool.acquire(timeout=1) as connection:
                assert await connection.fetchval(kes_config.select_one) == 1
            assert pool.get_idle_size() == pool.get_size() == 1
        finally:
            if held is not None:
                await pool.release(held)
            await pool.close()

    asyncio.run(scenario())


def test_pool_acquire_context_exception_releases_and_invalidates_proxy(
    kes_config: KESConfig,
) -> None:
    """测试点：acquire 上下文异常退出会归还连接，并使逃逸代理立即失效。"""
    async def scenario() -> None:
        pool = await asyncpg.create_pool(
            **_pool_options(kes_config), min_size=1, max_size=1
        )
        escaped_connection = None
        try:
            with pytest.raises(RuntimeError, match="simulated business error"):
                async with pool.acquire() as connection:
                    escaped_connection = connection
                    raise RuntimeError("simulated business error")

            assert pool.get_idle_size() == 1
            with pytest.raises(
                asyncpg.InterfaceError,
                match="connection has been released back to the pool",
            ):
                await escaped_connection.fetchval(kes_config.select_one)

            async with pool.acquire(timeout=1) as connection:
                assert await connection.fetchval(kes_config.select_one) == 1
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_cancelled_pool_release_still_returns_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：release 调用被取消时，受保护的 reset 仍完成并归还连接。"""
    async def scenario() -> None:
        reset_started = asyncio.Event()
        allow_reset = asyncio.Event()

        async def controlled_reset(connection: asyncpg.Connection) -> None:
            reset_started.set()
            await allow_reset.wait()
            await connection.reset()

        pool = await asyncpg.create_pool(
            **_pool_options(kes_config),
            min_size=1,
            max_size=1,
            reset=controlled_reset,
        )
        connection = await pool.acquire()
        try:
            release_task = asyncio.create_task(pool.release(connection))
            await asyncio.wait_for(reset_started.wait(), timeout=1)
            release_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await release_task

            allow_reset.set()
            await _wait_until(lambda: pool.get_idle_size() == 1)
            async with pool.acquire(timeout=1) as recovered:
                assert await recovered.fetchval(kes_config.select_one) == 1
        finally:
            allow_reset.set()
            if pool.get_idle_size() == 0:
                await _wait_until(lambda: pool.get_idle_size() == 1)
            await pool.close()

    asyncio.run(scenario())


def test_pool_release_waits_for_query_cancellation_and_connection_recovers(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool 归还刚取消查询的连接时等待协议清理，随后可正常复用。"""
    async def scenario() -> None:
        pool = await asyncpg.create_pool(
            **_pool_options(kes_config), min_size=1, max_size=1
        )
        connection = await pool.acquire()
        query_task = asyncio.create_task(
            connection.fetchval(_sleep_query(kes_config.mode))
        )
        try:
            await asyncio.sleep(0.05)
            query_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await query_task

            await pool.release(connection, timeout=1)
            connection = None
            async with pool.acquire(timeout=1) as recovered:
                assert await recovered.fetchval(kes_config.select_one) == 1
            assert pool.get_idle_size() == pool.get_size() == 1
        finally:
            if not query_task.done():
                query_task.cancel()
                await asyncio.gather(query_task, return_exceptions=True)
            if connection is not None:
                await pool.release(connection)
            await pool.close()

    asyncio.run(scenario())


def test_pool_close_waits_for_checked_out_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool.close 等待借出连接归还，关闭期间拒绝新的 acquire。"""
    async def scenario() -> None:
        pool = await asyncpg.create_pool(
            **_pool_options(kes_config), min_size=1, max_size=1
        )
        connection = await pool.acquire()
        close_task = asyncio.create_task(pool.close())
        try:
            await asyncio.sleep(0.02)
            assert pool.is_closing()
            assert not close_task.done()
            with pytest.raises(
                asyncpg.InterfaceError, match="pool is closing"
            ):
                await pool.acquire()

            await pool.release(connection)
            connection = None
            await asyncio.wait_for(close_task, timeout=2)
            assert pool.is_closing()
            assert pool.get_size() == pool.get_idle_size() == 0
        finally:
            if connection is not None:
                await pool.release(connection)
            if not close_task.done():
                await asyncio.wait_for(close_task, timeout=2)

    asyncio.run(scenario())


def test_pool_context_manager_closes_pool_and_rejects_reuse(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool 自身上下文完成初始化和关闭，退出后所有操作均被拒绝。"""
    async def scenario() -> None:
        pool = None
        async with asyncpg.create_pool(
            **_pool_options(kes_config), min_size=1, max_size=1
        ) as pool:
            row = await pool.fetchrow(kes_config.select_one)
            assert row == (1,)
            assert not pool.is_closing()

        assert pool is not None
        assert pool.is_closing()
        with pytest.raises(asyncpg.InterfaceError, match="pool is closed"):
            await pool.acquire()

    asyncio.run(scenario())


def test_idle_pool_connection_terminated_by_server_is_replaced(
    kes_config: KESConfig,
) -> None:
    """测试点：空闲物理连接被服务端终止后，原生 Pool 自动建立新连接。"""
    async def scenario() -> None:
        pool = await asyncpg.create_pool(
            **_pool_options(kes_config), min_size=1, max_size=1
        )
        killer = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            async with pool.acquire() as connection:
                first_pid = connection.get_server_pid()

            assert await killer.fetchval(
                "SELECT pg_terminate_backend($1)", first_pid
            ) is True
            await _wait_until(lambda: pool.get_size() == 0)

            async with pool.acquire(timeout=1) as connection:
                assert connection.get_server_pid() != first_pid
                assert await connection.fetchval(kes_config.select_one) == 1
            assert pool.get_size() == pool.get_idle_size() == 1
        finally:
            await killer.close()
            await pool.close()

    asyncio.run(scenario())


def test_concurrent_pool_transactions_preserve_data_and_release_resources(
    kes_config: KESConfig,
) -> None:
    """测试点：并发事务写读结果一致，任务结束后所有 Pool 连接均归还。"""
    async def scenario() -> None:
        table = unique_object_name("pool_concurrent", kes_config.mode)
        id_type = "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
        text_type = (
            "VARCHAR2(100)" if kes_config.mode == "oracle"
            else "VARCHAR(100)"
        )
        pool = await asyncpg.create_pool(
            **_pool_options(kes_config), min_size=2, max_size=2
        )
        cleanup = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            await pool.execute(
                f"CREATE TABLE {table} ("
                f"id {id_type} PRIMARY KEY, label {text_type})"
            )

            async def worker(value: int) -> int:
                async with pool.acquire() as connection:
                    async with connection.transaction():
                        await connection.execute(
                            f"INSERT INTO {table} VALUES ($1, $2)",
                            value,
                            f"value-{value}",
                        )
                        return await connection.fetchval(
                            f"SELECT id FROM {table} WHERE id = $1", value
                        )

            expected = list(range(1, 25))
            assert await asyncio.gather(
                *(worker(value) for value in expected)
            ) == expected
            assert await pool.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == len(expected)
            assert pool.get_size() == 2
            assert pool.get_idle_size() == pool.get_size()
        finally:
            await drop_table(cleanup, table)
            await cleanup.close()
            await pool.close()

    asyncio.run(scenario())
