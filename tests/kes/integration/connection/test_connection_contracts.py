"""Integration tests for asyncpg public connection contracts on KES."""

from __future__ import annotations

import asyncio

import asyncpg
import pytest

from tests.kes.support.config import KESConfig, drop_table, unique_object_name


pytestmark = pytest.mark.integration


def _table_types(mode: str) -> tuple[str, str]:
    if mode == "oracle":
        return "NUMBER(10)", "VARCHAR2(400)"
    return "INT", "VARCHAR(400)"


def _sleep_query(mode: str, seconds: int = 10) -> str:
    suffix = " FROM dual" if mode == "oracle" else ""
    return f"SELECT pg_sleep({seconds}){suffix}"


def test_invalid_login_and_database_are_rejected_then_valid_login_recovers(
    kes_config: KESConfig,
) -> None:
    """测试点：错误凭证和数据库被拒绝，随后正确配置仍可正常连接。"""
    async def scenario() -> None:
        invalid_credentials = (
            {"password": "definitely-wrong-password"},
            {"user": f"apg_missing_login_{kes_config.mode}"},
        )
        for credentials in invalid_credentials:
            with pytest.raises(asyncpg.InvalidPasswordError):
                await asyncpg.connect(
                    **kes_config.connection_kwargs(**credentials)
                )

        with pytest.raises(asyncpg.InvalidCatalogNameError):
            await asyncpg.connect(
                **kes_config.connection_kwargs(
                    database=f"apg_missing_database_{kes_config.mode}"
                )
            )

        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            assert connection.get_kes_mode() == kes_config.mode
            assert await connection.fetchval(kes_config.select_one) == 1
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_closed_connection_rejects_queries_and_close_is_idempotent(
    kes_config: KESConfig,
) -> None:
    """测试点：连接关闭可重复调用，关闭后的查询明确抛出 InterfaceError。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        await connection.close()
        await connection.close()

        assert connection.is_closed()
        with pytest.raises(
            asyncpg.InterfaceError, match="connection is closed"
        ):
            await connection.fetchval(kes_config.select_one)
        connection.terminate()

    asyncio.run(scenario())


def test_record_mapping_sequence_and_hash_contracts(
    kes_config: KESConfig,
) -> None:
    """测试点：Record 的名称、序列、映射、切片、比较和哈希接口保持兼容。"""
    async def scenario() -> None:
        suffix = " FROM dual" if kes_config.mode == "oracle" else ""
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            row = await connection.fetchrow(
                "SELECT 1 AS first_value, 'alpha' AS second_value" + suffix
            )
            assert row is not None
            assert len(row) == 2
            assert tuple(row) == (1, "alpha")
            assert row[0] == row["first_value"] == 1
            assert row[:] == (1, "alpha")
            assert row.get("missing", "fallback") == "fallback"
            assert list(row.keys()) == ["first_value", "second_value"]
            assert list(row.values()) == [1, "alpha"]
            assert list(row.items()) == [
                ("first_value", 1),
                ("second_value", "alpha"),
            ]
            assert dict(row) == {
                "first_value": 1,
                "second_value": "alpha",
            }
            assert "first_value" in row
            assert row == (1, "alpha")
            assert hash(row) == hash((1, "alpha"))
            with pytest.raises(KeyError, match="missing"):
                _ = row["missing"]
            with pytest.raises(IndexError, match="record index out of range"):
                _ = row[10]
            with pytest.raises(TypeError, match="does not support item"):
                row[0] = 2
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_prepared_single_result_and_cursor_iteration_contracts(
    kes_config: KESConfig,
) -> None:
    """测试点：预编译单值/单行和 Cursor 异步迭代、事务及预取边界正常。"""
    async def scenario() -> None:
        table = unique_object_name("cursor_contract", kes_config.mode)
        id_type, text_type = _table_types(kes_config.mode)
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            await connection.execute(
                f"CREATE TABLE {table} ("
                f"id {id_type} PRIMARY KEY, label {text_type})"
            )
            await connection.executemany(
                f"INSERT INTO {table} VALUES ($1, $2)",
                [(value, f"value-{value}") for value in range(1, 6)],
            )

            statement = await connection.prepare(
                f"SELECT id, label FROM {table} WHERE id = $1"
            )
            assert await statement.fetchval(2, column=1) == "value-2"
            assert tuple(await statement.fetchrow(3)) == (3, "value-3")
            assert await statement.fetchrow(99) is None
            plan = await statement.explain(2, analyze=True)
            assert plan and "Plan" in plan[0]
            assert not connection.is_in_transaction()

            empty_statement = await connection.prepare("")
            assert await empty_statement.fetch() == []
            assert await empty_statement.fetchval() is None
            assert await empty_statement.fetchrow() is None

            ordered_query = f"SELECT id FROM {table} ORDER BY id"
            with pytest.raises(asyncpg.NoActiveSQLTransactionError):
                async for _ in connection.cursor(
                    ordered_query, prefetch=2
                ):
                    pass

            async with connection.transaction():
                rows = [
                    row["id"]
                    async for row in connection.cursor(
                        ordered_query, prefetch=2
                    )
                ]
                assert rows == [1, 2, 3, 4, 5]

                with pytest.raises(
                    asyncpg.InterfaceError,
                    match="prefetch argument must be greater than zero",
                ):
                    async for _ in connection.cursor(
                        ordered_query, prefetch=0
                    ):
                        pass
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_active_query_close_and_terminate_report_distinct_failures(
    kes_config: KESConfig,
) -> None:
    """测试点：活动查询期间优雅关闭和强制终止返回明确且不同的异常。"""
    async def scenario() -> None:
        cases = (
            ("close", asyncpg.QueryCanceledError),
            ("terminate", asyncpg.ConnectionDoesNotExistError),
        )
        for action, error_type in cases:
            connection = await asyncpg.connect(
                **kes_config.connection_kwargs()
            )
            query_task = asyncio.create_task(
                connection.fetchval(_sleep_query(kes_config.mode))
            )
            await asyncio.sleep(0.05)
            if action == "close":
                await connection.close()
            else:
                connection.terminate()

            with pytest.raises(error_type):
                await query_task
            assert connection.is_closed()

    asyncio.run(scenario())


def test_concurrent_connection_operation_is_rejected_then_connection_recovers(
    kes_config: KESConfig,
) -> None:
    """测试点：同一连接并发执行被拒绝，取消首个命令后连接仍可复用。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        query_task = asyncio.create_task(
            connection.fetchval(_sleep_query(kes_config.mode, 1))
        )
        try:
            await asyncio.sleep(0.05)
            with pytest.raises(
                asyncpg.InterfaceError,
                match="another operation is in progress",
            ):
                await connection.fetchval(kes_config.select_one)

            query_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await query_task
            assert await connection.fetchval(kes_config.select_one) == 1
        finally:
            if not query_task.done():
                query_task.cancel()
                await asyncio.gather(query_task, return_exceptions=True)
            await connection.close()

    asyncio.run(scenario())


def test_executemany_server_error_is_atomic_and_connection_is_reusable(
    kes_config: KESConfig,
) -> None:
    """测试点：批处理中途约束失败会整体回滚，且同一连接可以继续使用。"""
    async def scenario() -> None:
        table = unique_object_name("executemany_atomic", kes_config.mode)
        id_type, text_type = _table_types(kes_config.mode)
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            await connection.execute(
                f"CREATE TABLE {table} ("
                f"id {id_type} PRIMARY KEY, label {text_type})"
            )
            with pytest.raises(asyncpg.UniqueViolationError):
                await connection.executemany(
                    f"INSERT INTO {table} VALUES ($1, $2)",
                    [(1, "one"), (2, "two"), (2, "duplicate")],
                )
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 0

            await connection.executemany(
                f"INSERT INTO {table} VALUES ($1, $2)",
                [(1, "one"), (2, "two")],
            )
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 2
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_executemany_client_iterator_failure_is_atomic(
    kes_config: KESConfig,
) -> None:
    """测试点：客户端批处理迭代器中途失败不会留下部分写入。"""
    async def scenario() -> None:
        table = unique_object_name("client_batch_atomic", kes_config.mode)
        id_type, _ = _table_types(kes_config.mode)
        connection = await asyncpg.connect(**kes_config.connection_kwargs())

        def broken_records():
            yield (1,)
            yield (2,)
            raise RuntimeError("simulated client iterator failure")

        try:
            await connection.execute(
                f"CREATE TABLE {table} (id {id_type} PRIMARY KEY)"
            )
            with pytest.raises(
                RuntimeError, match="simulated client iterator failure"
            ):
                await connection.executemany(
                    f"INSERT INTO {table} VALUES ($1)", broken_records()
                )
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 0
            assert await connection.fetchval(kes_config.select_one) == 1
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_transaction_state_machine_rejects_invalid_transitions(
    kes_config: KESConfig,
) -> None:
    """测试点：事务重复启动、重复提交和上下文内手动提交均被拒绝。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            transaction = connection.transaction()
            await transaction.start()
            with pytest.raises(
                asyncpg.InterfaceError, match="already started"
            ):
                await transaction.start()
            await transaction.commit()
            with pytest.raises(
                asyncpg.InterfaceError, match="already committed"
            ):
                await transaction.commit()

            context_transaction = connection.transaction()
            with pytest.raises(
                asyncpg.InterfaceError,
                match="cannot manually commit from within an `async with`",
            ):
                async with context_transaction:
                    await context_transaction.commit()

            assert not connection.is_in_transaction()
            assert await connection.fetchval(kes_config.select_one) == 1
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_statement_cache_disable_and_query_size_limit(
    kes_config: KESConfig,
) -> None:
    """测试点：statement cache 可关闭，且超长 SQL 不进入配置容量内的缓存。"""
    async def scenario() -> None:
        suffix = " FROM dual" if kes_config.mode == "oracle" else ""
        short_query = "SELECT CAST($1 AS INTEGER)" + suffix
        long_query = (
            "SELECT CAST($1 AS INTEGER) /* "
            + "x" * 100
            + " */"
            + suffix
        )
        limited = await asyncpg.connect(
            **kes_config.connection_kwargs(
                statement_cache_size=10,
                max_cacheable_statement_size=64,
            )
        )
        try:
            assert await limited.fetchval(short_query, 1) == 1
            assert await limited.fetchval(long_query, 2) == 2
            cached_queries = {
                statement.query
                for statement in limited._stmt_cache.iter_statements()
            }
            assert short_query in cached_queries
            assert long_query not in cached_queries
        finally:
            await limited.close()

        disabled = await asyncpg.connect(
            **kes_config.connection_kwargs(statement_cache_size=0)
        )
        try:
            assert await disabled.fetchval(short_query, 3) == 3
            assert len(disabled._stmt_cache) == 0
        finally:
            await disabled.close()

    asyncio.run(scenario())


def test_parameter_binding_treats_injection_payload_as_plain_data(
    kes_config: KESConfig,
) -> None:
    """测试点：参数绑定不会执行注入载荷，原值和目标表均保持完整。"""
    async def scenario() -> None:
        table = unique_object_name("bound_payload", kes_config.mode)
        id_type, text_type = _table_types(kes_config.mode)
        payload = f"value'); DROP TABLE {table}; --"
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            await connection.execute(
                f"CREATE TABLE {table} ("
                f"id {id_type} PRIMARY KEY, label {text_type})"
            )
            await connection.execute(
                f"INSERT INTO {table} VALUES ($1, $2)", 1, payload
            )
            assert await connection.fetchval(
                f"SELECT label FROM {table} WHERE id = $1", 1
            ) == payload
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 1
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())
