"""Tests for the pool requirement module."""

from __future__ import annotations

import asyncio
import datetime
import asynckb
import pytest
from tests.kes.support.config import KESConfig, drop_table, unique_object_name

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

@pytest.mark.case_id("KB-POOL-005")
@pytest.mark.integration
def test_pool_release_rolls_back_transaction_and_reloads_kes_codecs(
    kes_config: KESConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """测试点：Pool 释放时回滚事务，过期重连后重新注册 KES codec。"""
    async def scenario() -> None:
        table = unique_object_name("pool_reset", kes_config.mode)
        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        pool = await asynckb.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
        )
        try:
            id_type = "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            await pool.execute(
                f"CREATE TABLE {table} (id {id_type} PRIMARY KEY)"
            )

            connection = await pool.acquire()
            transaction = connection.transaction()
            await transaction.start()
            await connection.execute(f"INSERT INTO {table} VALUES (1)")
            await pool.release(connection)
            assert any(
                "Resetting connection with an active transaction"
                in record.getMessage()
                for record in caplog.records
            )

            async with pool.acquire() as connection:
                assert not connection.is_in_transaction()
                assert await connection.fetchval(
                    f"SELECT count(*) FROM {table}"
                ) == 0
                first_pid = connection.get_server_pid()

            await pool.expire_connections()
            async with pool.acquire() as connection:
                assert connection.get_server_pid() != first_pid
                if kes_config.mode == "mysql":
                    assert await connection.fetchval(
                        "SELECT CAST('2025-01-02' AS DATE)"
                    ) == datetime.date(2025, 1, 2)
                elif kes_config.mode == "oracle":
                    assert await connection.fetchval(
                        "SELECT INTERVAL '1 02:03:04' DAY TO SECOND FROM dual"
                    ) == "+01 02:03:04.000000"
                else:
                    assert await connection.fetchval(
                        "SELECT CAST(0x00ff AS VARBINARY(2))"
                    ) == b"\x00\xff"
        finally:
            async with pool.acquire() as connection:
                await drop_table(connection, table)
            await pool.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-POOL-006")
@pytest.mark.integration
def test_pool_callbacks_run_in_order_and_preserve_kes_mode(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool init/setup/reset 生命周期顺序正确且连接保持 KES 模式。"""
    async def scenario() -> None:
        events: list[tuple[str, int]] = []

        async def init(connection: asynckb.Connection) -> None:
            assert connection.get_kes_mode() == kes_config.mode
            events.append(("init", connection.get_server_pid()))

        async def setup(connection: asynckb.Connection) -> None:
            assert connection.get_kes_mode() == kes_config.mode
            events.append(("setup", connection.get_server_pid()))

        async def reset(connection: asynckb.Connection) -> None:
            events.append(("reset", connection.get_server_pid()))
            await connection.reset()

        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        pool = await asynckb.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
            init=init,
            setup=setup,
            reset=reset,
        )
        try:
            pids = []
            for _ in range(2):
                async with pool.acquire() as connection:
                    pids.append(connection.get_server_pid())
                    assert await connection.fetchval(
                        kes_config.select_one
                    ) == 1
            assert pids[0] == pids[1]
            assert [event for event, _ in events] == [
                "init", "setup", "reset", "setup", "reset"
            ]
        finally:
            await pool.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-POOL-007")
@pytest.mark.integration
def test_pool_partial_initialization_failure_closes_kes_connections(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool 部分初始化失败时关闭所有已建立的 KES 连接。"""
    async def scenario() -> None:
        opened_connections: list[asynckb.Connection] = []
        connection_attempt = 0

        async def connect_then_fail(*args, **kwargs) -> asynckb.Connection:
            nonlocal connection_attempt
            connection_attempt += 1
            if connection_attempt == 2:
                await asyncio.sleep(0.05)
                raise RuntimeError("simulated pool initialization failure")

            connection = await asynckb.connect(*args, **kwargs)
            opened_connections.append(connection)
            return connection

        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        with pytest.raises(
            RuntimeError, match="simulated pool initialization failure"
        ):
            await asynckb.create_pool(
                **pool_options,
                min_size=3,
                max_size=3,
                connect=connect_then_fail,
            )

        assert opened_connections
        assert all(
            connection.is_closed() for connection in opened_connections
        )

    asyncio.run(scenario())
@pytest.mark.case_id("KB-POOL-009")
@pytest.mark.integration
def test_pool_setup_callback_failure_discards_connection_and_recovers(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool setup 回调失败后丢弃连接，下一次 acquire 可恢复。"""
    async def scenario() -> None:
        opened_connections: list[asynckb.Connection] = []
        setup_calls = 0

        async def tracked_connect(*args, **kwargs) -> asynckb.Connection:
            connection = await asynckb.connect(*args, **kwargs)
            opened_connections.append(connection)
            return connection

        async def fail_first_setup(connection: asynckb.Connection) -> None:
            nonlocal setup_calls
            setup_calls += 1
            if setup_calls == 1:
                raise RuntimeError("simulated pool setup failure")

        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        pool = await asynckb.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
            connect=tracked_connect,
            setup=fail_first_setup,
        )
        try:
            with pytest.raises(
                RuntimeError, match="simulated pool setup failure"
            ):
                await pool.acquire()

            assert opened_connections[0].is_closed()
            async with pool.acquire() as connection:
                assert await connection.fetchval(kes_config.select_one) == 1
            assert len(opened_connections) == 2
        finally:
            await pool.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-POOL-010")
@pytest.mark.integration
def test_pool_reset_callback_failure_discards_connection_and_recovers(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool reset 回调失败后终止连接，下一次 acquire 可恢复。"""
    async def scenario() -> None:
        opened_connections: list[asynckb.Connection] = []
        reset_calls = 0

        async def tracked_connect(*args, **kwargs) -> asynckb.Connection:
            connection = await asynckb.connect(*args, **kwargs)
            opened_connections.append(connection)
            return connection

        async def fail_first_reset(connection: asynckb.Connection) -> None:
            nonlocal reset_calls
            reset_calls += 1
            if reset_calls == 1:
                raise RuntimeError("simulated pool reset failure")
            await connection.reset()

        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        pool = await asynckb.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
            connect=tracked_connect,
            reset=fail_first_reset,
        )
        try:
            connection = await pool.acquire()
            with pytest.raises(
                RuntimeError, match="simulated pool reset failure"
            ):
                await pool.release(connection)

            assert opened_connections[0].is_closed()
            async with pool.acquire() as recovered_connection:
                assert await recovered_connection.fetchval(
                    kes_config.select_one
                ) == 1
            assert len(opened_connections) == 2
        finally:
            await pool.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-POOL-013")
@pytest.mark.integration
def test_pool_query_and_idle_recycling_reload_kes_codecs(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool 按查询数和空闲时间回收后，新连接重新注册 KES codec。"""
    async def codec_value(connection: asynckb.Connection):
        if kes_config.mode == "mysql":
            return await connection.fetchval(
                "SELECT CAST('2025-01-02' AS DATE)"
            )
        if kes_config.mode == "sqlserver":
            return await connection.fetchval(
                "SELECT CAST(0x00ff AS VARBINARY(2))"
            )
        return await connection.fetchval(
            "SELECT INTERVAL '1 00:00:00.123456' "
            "DAY TO SECOND FROM dual"
        )

    async def scenario() -> None:
        expected = (
            datetime.date(2025, 1, 2)
            if kes_config.mode == "mysql"
            else (
                b"\x00\xff"
                if kes_config.mode == "sqlserver"
                else "+01 00:00:00.123456"
            )
        )
        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")

        query_pool = await asynckb.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
            max_queries=1,
        )
        try:
            query_pids = []
            for _ in range(2):
                async with query_pool.acquire() as connection:
                    query_pids.append(connection.get_server_pid())
                    assert await codec_value(connection) == expected
            assert query_pids[0] != query_pids[1]
        finally:
            await query_pool.close()

        idle_pool = await asynckb.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
            max_inactive_connection_lifetime=0.05,
        )
        try:
            async with idle_pool.acquire() as connection:
                first_pid = connection.get_server_pid()
                assert await codec_value(connection) == expected
            await asyncio.sleep(0.1)
            async with idle_pool.acquire() as connection:
                assert connection.get_server_pid() != first_pid
                assert await codec_value(connection) == expected
        finally:
            await idle_pool.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-POOL-016")
@pytest.mark.integration
def test_pool_batch_capacity_timeout_and_shutdown_contracts(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool 批处理代理、容量统计、获取超时、并发排队和关闭状态正常。"""
    async def scenario() -> None:
        table = unique_object_name("pool_contract", kes_config.mode)
        id_type = "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
        text_type = (
            "VARCHAR2(30)" if kes_config.mode == "oracle"
            else "VARCHAR(30)"
        )
        options = kes_config.connection_kwargs()
        options.pop("timeout")
        pool = await asynckb.create_pool(
            **options, min_size=1, max_size=3
        )
        cleanup = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            assert pool.get_min_size() == 1
            assert pool.get_max_size() == 3
            assert pool.get_size() == 1
            assert pool.get_idle_size() == 1
            assert not pool.is_closing()

            await pool.execute(
                f"CREATE TABLE {table} "
                f"(id {id_type} PRIMARY KEY, label {text_type})"
            )
            assert await pool.executemany(
                f"INSERT INTO {table} VALUES ($1, $2)",
                [(1, "one"), (2, "two")],
            ) is None
            rows = await pool.fetchmany(
                f"SELECT label FROM {table} WHERE id = $1",
                [(1,), (2,)],
            )
            assert [row["label"] for row in rows] == ["one", "two"]

            held = await pool.acquire()
            try:
                second = await pool.acquire()
                third = await pool.acquire()
                try:
                    with pytest.raises(asyncio.TimeoutError):
                        await pool.acquire(timeout=0.01)
                finally:
                    await pool.release(third)
                    await pool.release(second)
            finally:
                await pool.release(held)

            async def worker(value: int) -> int:
                async with pool.acquire() as connection:
                    await asyncio.sleep(0.01)
                    return await connection.fetchval(
                        "SELECT CAST($1 AS INTEGER)" + (
                            " FROM dual" if kes_config.mode == "oracle"
                            else ""
                        ),
                        value,
                    )

            assert await asyncio.gather(
                *(worker(value) for value in range(12))
            ) == list(range(12))
            assert 1 <= pool.get_size() <= 3
            assert pool.get_idle_size() == pool.get_size()

            await pool.execute(f"DROP TABLE {table}")
            await pool.close()
            assert pool.is_closing()

            terminate_pool = await asynckb.create_pool(
                **options, min_size=1, max_size=1
            )
            assert not terminate_pool.is_closing()
            terminate_pool.terminate()
            assert terminate_pool.is_closing()
        finally:
            if not pool.is_closing():
                pool.terminate()
            await drop_table(cleanup, table)
            await cleanup.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-POOL-017")
@pytest.mark.integration
def test_cancelled_pool_waiter_does_not_consume_capacity(
    kes_config: KESConfig,
) -> None:
    """测试点：等待连接的任务被取消后不占用 holder，连接池容量可立即恢复。"""
    async def scenario() -> None:
        pool = await asynckb.create_pool(
            **_pool_options(kes_config), min_size=1, max_size=1
        )
        held = await pool.acquire()
        try:
            async def wait_for_connection() -> asynckb.Connection:
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
@pytest.mark.case_id("KB-POOL-019")
@pytest.mark.integration
def test_cancelled_pool_release_still_returns_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：release 调用被取消时，受保护的 reset 仍完成并归还连接。"""
    async def scenario() -> None:
        reset_started = asyncio.Event()
        allow_reset = asyncio.Event()

        async def controlled_reset(connection: asynckb.Connection) -> None:
            reset_started.set()
            await allow_reset.wait()
            await connection.reset()

        pool = await asynckb.create_pool(
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
@pytest.mark.case_id("KB-POOL-020")
@pytest.mark.integration
def test_pool_release_waits_for_query_cancellation_and_connection_recovers(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool 归还刚取消查询的连接时等待协议清理，随后可正常复用。"""
    async def scenario() -> None:
        pool = await asynckb.create_pool(
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
@pytest.mark.case_id("KB-POOL-021")
@pytest.mark.integration
def test_pool_close_waits_for_checked_out_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool.close 等待借出连接归还，关闭期间拒绝新的 acquire。"""
    async def scenario() -> None:
        pool = await asynckb.create_pool(
            **_pool_options(kes_config), min_size=1, max_size=1
        )
        connection = await pool.acquire()
        close_task = asyncio.create_task(pool.close())
        try:
            await asyncio.sleep(0.02)
            assert pool.is_closing()
            assert not close_task.done()
            with pytest.raises(
                asynckb.InterfaceError, match="pool is closing"
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
@pytest.mark.case_id("KB-POOL-023")
@pytest.mark.integration
def test_idle_pool_connection_terminated_by_server_is_replaced(
    kes_config: KESConfig,
) -> None:
    """测试点：空闲物理连接被服务端终止后，原生 Pool 自动建立新连接。"""
    async def scenario() -> None:
        pool = await asynckb.create_pool(
            **_pool_options(kes_config), min_size=1, max_size=1
        )
        killer = await asynckb.connect(**kes_config.connection_kwargs())
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
@pytest.mark.case_id("KB-POOL-025")
@pytest.mark.parametrize(
    ("options", "error_type", "message"),
    (
        (
            {"min_size": 0, "max_size": 0},
            ValueError,
            "max_size is expected to be greater than zero",
        ),
        (
            {"min_size": -1, "max_size": 1},
            ValueError,
            "min_size is expected to be greater or equal to zero",
        ),
        (
            {"min_size": 2, "max_size": 1},
            ValueError,
            "min_size is greater than max_size",
        ),
        (
            {"min_size": 0, "max_size": 1, "max_queries": 0},
            ValueError,
            "max_queries is expected to be greater than zero",
        ),
        (
            {
                "min_size": 0,
                "max_size": 1,
                "max_inactive_connection_lifetime": -1,
            },
            ValueError,
            "max_inactive_connection_lifetime is expected",
        ),
        (
            {"min_size": 0, "max_size": 1, "connection_class": object},
            TypeError,
            "connection_class is expected to be a subclass",
        ),
        (
            {"min_size": 0, "max_size": 1, "record_class": tuple},
            TypeError,
            "record_class is expected to be a subclass",
        ),
    ),
    ids=(
        "zero-max-size",
        "negative-min-size",
        "min-greater-than-max",
        "zero-max-queries",
        "negative-inactive-lifetime",
        "invalid-connection-class",
        "invalid-record-class",
    ),
)
@pytest.mark.unit
def test_pool_configuration_boundaries_fail_before_connecting(
    options: dict[str, object],
    error_type: type[Exception],
    message: str,
) -> None:
    """测试点：Pool 容量、生命周期及扩展类型非法边界在建连前失败。"""
    async def scenario() -> None:
        with pytest.raises(error_type, match=message):
            asynckb.create_pool(**options)

    asyncio.run(scenario())
