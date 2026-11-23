"""Tests for the execution transactions statements requirement module."""

from __future__ import annotations

import asyncio
import asynckb
import pytest
from tests.kes.support.config import KESConfig, drop_table, unique_object_name
import gc
from decimal import Decimal
import datetime


def _table_types(mode: str) -> tuple[str, str]:
    if mode == "oracle":
        return "NUMBER(10)", "VARCHAR2(400)"
    return "INT", "VARCHAR(400)"


def _sleep_query(mode: str, seconds: int = 10) -> str:
    suffix = " FROM dual" if mode == "oracle" else ""
    return f"SELECT pg_sleep({seconds}){suffix}"


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
    connection: asynckb.Connection,
    table: str,
    mode: str,
) -> None:
    await connection.execute(
        f"CREATE TABLE {table} ({_user_columns(mode)})"
    )


@pytest.mark.case_id("KB-EXEC-004")
@pytest.mark.integration
def test_prepared_single_result_and_cursor_iteration_contracts(
    kes_config: KESConfig,
) -> None:
    """测试点：预编译单值/单行和 Cursor 异步迭代、事务及预取边界正常。"""
    async def scenario() -> None:
        table = unique_object_name("cursor_contract", kes_config.mode)
        id_type, text_type = _table_types(kes_config.mode)
        connection = await asynckb.connect(**kes_config.connection_kwargs())
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
            with pytest.raises(asynckb.NoActiveSQLTransactionError):
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
                    asynckb.InterfaceError,
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


@pytest.mark.case_id("KB-EXEC-005")
@pytest.mark.integration
def test_active_query_close_and_terminate_report_distinct_failures(
    kes_config: KESConfig,
) -> None:
    """测试点：活动查询期间优雅关闭和强制终止返回明确且不同的异常。"""
    async def scenario() -> None:
        cases = (
            ("close", asynckb.QueryCanceledError),
            ("terminate", asynckb.ConnectionDoesNotExistError),
        )
        for action, error_type in cases:
            connection = await asynckb.connect(
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


@pytest.mark.case_id("KB-EXEC-006")
@pytest.mark.integration
def test_concurrent_connection_operation_is_rejected_then_connection_recovers(
    kes_config: KESConfig,
) -> None:
    """测试点：同一连接并发执行被拒绝，取消首个命令后连接仍可复用。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        query_task = asyncio.create_task(
            connection.fetchval(_sleep_query(kes_config.mode, 1))
        )
        try:
            await asyncio.sleep(0.05)
            with pytest.raises(
                asynckb.InterfaceError,
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


@pytest.mark.case_id("KB-EXEC-007")
@pytest.mark.integration
def test_executemany_server_error_is_atomic_and_connection_is_reusable(
    kes_config: KESConfig,
) -> None:
    """测试点：批处理中途约束失败会整体回滚，且同一连接可以继续使用。"""
    async def scenario() -> None:
        table = unique_object_name("executemany_atomic", kes_config.mode)
        id_type, text_type = _table_types(kes_config.mode)
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            await connection.execute(
                f"CREATE TABLE {table} ("
                f"id {id_type} PRIMARY KEY, label {text_type})"
            )
            with pytest.raises(asynckb.UniqueViolationError):
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


@pytest.mark.case_id("KB-EXEC-008")
@pytest.mark.integration
def test_executemany_client_iterator_failure_is_atomic(
    kes_config: KESConfig,
) -> None:
    """测试点：客户端批处理迭代器中途失败不会留下部分写入。"""
    async def scenario() -> None:
        table = unique_object_name("client_batch_atomic", kes_config.mode)
        id_type, _ = _table_types(kes_config.mode)
        connection = await asynckb.connect(**kes_config.connection_kwargs())

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


@pytest.mark.case_id("KB-EXEC-010")
@pytest.mark.integration
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
        limited = await asynckb.connect(
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

        disabled = await asynckb.connect(
            **kes_config.connection_kwargs(statement_cache_size=0)
        )
        try:
            assert await disabled.fetchval(short_query, 3) == 3
            assert len(disabled._stmt_cache) == 0
        finally:
            await disabled.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-013")
@pytest.mark.integration
def test_mysql_manual_deallocate_allows_reprepare(
    mysql_config: KESConfig,
) -> None:
    """测试点：DEALLOCATE 单条和 ALL 后旧对象失效、同名对象可重新准备。"""

    async def scenario() -> None:
        connection = await asynckb.connect(**mysql_config.connection_kwargs())
        try:
            statement = await connection.prepare(
                "SELECT 1", name="apg_mysql_manual_deallocate"
            )
            assert await statement.fetchval() == 1
            await connection.execute("DEALLOCATE apg_mysql_manual_deallocate")
            with pytest.raises(asynckb.InterfaceError):
                await statement.fetchval()
            statement = await connection.prepare(
                "SELECT 2", name="apg_mysql_manual_deallocate"
            )
            assert await statement.fetchval() == 2
            await connection.execute("DEALLOCATE ALL")
            statement = await connection.prepare(
                "SELECT 3", name="apg_mysql_manual_deallocate"
            )
            assert await statement.fetchval() == 3
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-014")
@pytest.mark.integration
def test_mysql_old_statement_gc_does_not_close_replacement(
    mysql_config: KESConfig,
) -> None:
    """测试点：旧 named statement 被 GC 时不能误关闭同名的新 statement。"""

    async def scenario() -> None:
        connection = await asynckb.connect(**mysql_config.connection_kwargs())
        try:
            old_statement = await connection.prepare(
                "SELECT 1", name="apg_mysql_gc_replacement"
            )
            await connection.execute("DEALLOCATE apg_mysql_gc_replacement")
            new_statement = await connection.prepare(
                "SELECT 2", name="apg_mysql_gc_replacement"
            )
            del old_statement
            gc.collect()
            await connection.fetchval("SELECT 10")
            assert await new_statement.fetchval() == 2
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-015")
@pytest.mark.integration
def test_duplicate_named_statement_is_rejected_without_replacing_original(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式重复名称必须报错，且原 statement 仍可执行。"""

    async def scenario() -> None:
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        suffix = " FROM dual" if kes_config.mode == "oracle" else ""
        name = f"apg_{kes_config.mode}_duplicate_named_statement"
        try:
            original = await connection.prepare(f"SELECT 1{suffix}", name=name)
            with pytest.raises(asynckb.DuplicatePreparedStatementError):
                await connection.prepare(f"SELECT 2{suffix}", name=name)
            assert await original.fetchval() == 1
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-016")
@pytest.mark.parametrize(
    "deallocate_variant",
    (
        "multi_statement",
        "trailing_comment",
        "deallocate_all_multi_statement",
    ),
    ids=("multi-statement", "trailing-comment", "deallocate-all"),
)
@pytest.mark.integration
def test_named_statement_recovers_when_deallocate_is_not_a_standalone_command(
    kes_config: KESConfig,
    deallocate_variant: str,
) -> None:
    """测试点：多语句或尾注释 DEALLOCATE 后，三模式同名重建和 GC 正常。"""

    async def scenario() -> None:
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        suffix = " FROM dual" if kes_config.mode == "oracle" else ""
        name = "apg_{}_hidden_deallocate_{}".format(
            kes_config.mode,
            deallocate_variant,
        )
        try:
            old_statement = await connection.prepare(
                f"SELECT 1{suffix}", name=name
            )
            cached_query = f"SELECT 10{suffix}"
            assert await connection.fetchval(cached_query) == 10
            if deallocate_variant == "multi_statement":
                await connection.execute(
                    f"DEALLOCATE {name}; SELECT 9{suffix}"
                )
            elif deallocate_variant == "deallocate_all_multi_statement":
                await connection.execute(f"DEALLOCATE ALL; SELECT 9{suffix}")
            else:
                await connection.execute(
                    f"DEALLOCATE {name}; -- released by integration test"
                )

            replacement = await connection.prepare(
                f"SELECT 2{suffix}", name=name
            )
            with pytest.raises(asynckb.InterfaceError):
                await old_statement.fetchval()

            del old_statement
            gc.collect()
            assert await connection.fetchval(cached_query) == 10
            assert await replacement.fetchval() == 2
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-017")
@pytest.mark.integration
def test_execute_script_error_preserves_mode_specific_ddl_atomicity(
    kes_config: KESConfig,
) -> None:
    """测试点：多语句错误保留 KES 模式自身的 DDL 原子性语义。"""
    async def scenario() -> None:
        table = unique_object_name("script_atomic", kes_config.mode)
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            with pytest.raises(asynckb.UndefinedTableError):
                await connection.execute(
                    f"CREATE TABLE {table} (id INT); "
                    "SELECT * FROM apg_missing_script_relation"
                )

            exists = await connection.fetchval(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name = $1",
                table,
            )
            expected = 1 if kes_config.mode == "sqlserver" else 0
            assert exists == expected
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-018")
@pytest.mark.integration
def test_parameterized_execute_rejects_multiple_commands_before_execution(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式带参数 execute 拒绝多命令且不执行前置 DDL。"""
    async def scenario() -> None:
        table = unique_object_name("script_params", kes_config.mode)
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            expected_error = (
                asynckb.UndefinedTableError
                if kes_config.mode == "sqlserver"
                else asynckb.PostgresSyntaxError
            )
            with pytest.raises(expected_error):
                await connection.execute(
                    f"CREATE TABLE {table} (id INT); "
                    f"INSERT INTO {table} VALUES ($1)",
                    1,
                )

            exists = await connection.fetchval(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name = $1",
                table,
            )
            assert exists == 0
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-020")
@pytest.mark.parametrize("cache_size", [0, 100])
@pytest.mark.integration
def test_kes_explicit_parameter_directions(
    kes_config: KESConfig, cache_size: int,
) -> None:
    """Direction flags must return OUT values without changing IN semantics."""
    async def scenario() -> None:
        mode = kes_config.mode
        procedure = unique_object_name("param_direction", mode)
        connection = await asynckb.connect(
            **kes_config.connection_kwargs(), statement_cache_size=cache_size,
        )
        if mode == "oracle":
            ddl = (
                f"CREATE PROCEDURE {procedure}(p_add IN INTEGER, "
                "p_total IN OUT INTEGER, p_text OUT VARCHAR2) AS BEGIN "
                "p_total := p_total + p_add; p_text := 'done'; END;"
            )
        elif mode == "mysql":
            ddl = (
                f"CREATE PROCEDURE {procedure}(IN p_add INT, "
                "INOUT p_total INT, OUT p_text VARCHAR(30)) BEGIN "
                "SET p_total = p_total + p_add; SET p_text = 'done'; END"
            )
        else:
            ddl = (
                f"CREATE PROCEDURE {procedure} @p_add INT, "
                "@p_total INT OUTPUT, @p_text VARCHAR(30) OUTPUT AS BEGIN "
                "SET @p_total = @p_total + @p_add; SET @p_text = 'done'; END"
            )
        try:
            await connection.execute(ddl)
            query = f"CALL {procedure}($1, $2, $3)"
            statement = await connection.prepare(
                query, parameter_modes=("in", "inout", "out"),
            )
            assert statement.get_query() == query
            for args, expected in [
                ((2, 5, None), (7, "done")),
                ((3, 10, None), (13, "done")),
                ((1, None, None), (None, "done")),
            ]:
                row = await statement.fetchrow(*args)
                if mode == "sqlserver":
                    assert row["_retval_"] == 0
                    assert tuple(row)[1:] == expected
                else:
                    assert tuple(row) == expected
            rows = await statement.fetchmany([(1, 20, None), (2, 30, None)])
            assert [tuple(row)[-2:] for row in rows] == [
                (21, "done"), (32, "done"),
            ]
            await statement.executemany([(1, 1, None)])
            if mode == "sqlserver":
                execute_statement = await connection.prepare(
                    f"EXEC {procedure} $1, $2, $3",
                    parameter_modes=("in", "inout", "out"),
                )
                assert tuple(await execute_statement.fetchrow(2, 5, None)) == (
                    0, 7, "done",
                )
            assert await connection.fetchval("SELECT 987") == 987
        finally:
            try:
                await connection.execute(f"DROP PROCEDURE {procedure}")
            finally:
                await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-022")
@pytest.mark.parametrize("modes", [
    "out", ("in",), ("in", "out", "out"), ("in", "invalid"),
    ("in", None), ("in", []),
])
@pytest.mark.integration
def test_kes_invalid_parameter_directions_do_not_execute(
    kes_config: KESConfig, modes,
) -> None:
    """Invalid declarations must fail before executing any DML."""
    async def scenario() -> None:
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        table = unique_object_name("invalid_direction", kes_config.mode)
        try:
            await connection.execute(
                f"CREATE TABLE {table}(id INT, value INT)"
            )
            with pytest.raises(asynckb.InterfaceError):
                await connection.prepare(
                    f"INSERT INTO {table} VALUES ($1, $2)",
                    parameter_modes=modes,
                )
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 0
            assert await connection.fetchval("SELECT 987") == 987
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-023")
@pytest.mark.parametrize("cache_size", [0, 100])
@pytest.mark.integration
def test_oracle_returning_into_temporal_numeric_and_zero_rows(
    oracle_config: KESConfig, cache_size: int,
) -> None:
    ("""Output bindings use normal codecs, including temporal and """
     """numeric NULLs.""")

    async def scenario() -> None:
        connection = await asynckb.connect(
            **oracle_config.connection_kwargs(),
            statement_cache_size=cache_size,
        )
        table = unique_object_name("output_codecs", "oracle")
        try:
            await connection.execute(
                f"CREATE TABLE {table}(id INT PRIMARY KEY, "
                "amount NUMBER(12,2), stamp TIMESTAMP)"
            )
            statement = await connection.prepare(
                f"BEGIN INSERT INTO {table} VALUES ($1, $2, $3) "
                "RETURNING amount, stamp INTO $4, $5; END;",
                parameter_modes=("in", "in", "in", "out", "out"),
            )
            stamp = datetime.datetime(2026, 11, 3, 12, 34, 56, 123456)
            assert tuple(await statement.fetchrow(
                1, Decimal("123.45"), stamp, None, None,
            )) == (Decimal("123.45"), stamp)
            assert tuple(await statement.fetchrow(
                2, None, None, None, None,
            )) == (None, None)
            update = await connection.prepare(
                f"BEGIN UPDATE {table} SET amount = $2 WHERE id = $1 "
                "RETURNING amount INTO $3; END;",
                parameter_modes=("in", "in", "out"),
            )
            with pytest.raises(asynckb.NoDataFoundError):
                await update.fetchrow(999, Decimal("9.99"), None)
            multirow = await connection.prepare(
                f"BEGIN UPDATE {table} SET amount = $2 WHERE id <= $1 "
                "RETURNING amount INTO $3; END;",
                parameter_modes=("in", "in", "out"),
            )
            transaction = connection.transaction()
            await transaction.start()
            with pytest.raises(asynckb.TooManyRowsError):
                await multirow.fetchrow(2, Decimal("9.99"), None)
            await transaction.rollback()
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 2
            assert await connection.fetchval(
                f"SELECT amount FROM {table} WHERE id = 1"
            ) == Decimal("123.45")
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-024")
@pytest.mark.integration
def test_oracle_standalone_returning_into_is_server_restriction(
    oracle_config: KESConfig,
) -> None:
    ("""Standalone INTO is rejected by KES, not silently """
     """rewritten by the driver.""")

    async def scenario() -> None:
        connection = await asynckb.connect(**oracle_config.connection_kwargs())
        table = unique_object_name("standalone_into", "oracle")
        try:
            await connection.execute(f"CREATE TABLE {table}(id INT)")
            with pytest.raises(asynckb.PostgresSyntaxError) as error:
                await connection.prepare(
                    f"INSERT INTO {table} VALUES ($1) RETURNING id INTO $2",
                    parameter_modes=("in", "out"),
                )
            assert error.value.sqlstate == "42601"
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 0
            assert await connection.fetchval(
                f"INSERT INTO {table} VALUES ($1) RETURNING id", 42,
            ) == 42
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-026")
@pytest.mark.parametrize("cache_size", [0, 100])
@pytest.mark.integration
def test_oracle_call_returns_out_and_inout_parameters(
    oracle_config: KESConfig,
    cache_size: int,
) -> None:
    """测试点：混合 IN/OUT/IN OUT 参数通过 fetch 和批量接口返回结果行。"""
    async def scenario() -> None:
        procedure = unique_object_name("call_out", "oracle")
        connection = await asynckb.connect(
            **oracle_config.connection_kwargs(),
            statement_cache_size=cache_size,
        )
        try:
            await connection.execute(
                f"CREATE PROCEDURE {procedure}(p_add IN NUMBER, "
                "p_total IN OUT NUMBER, p_label OUT VARCHAR2) AS "
                "BEGIN p_total := p_total + p_add; "
                "p_label := 'done'; END;"
            )
            query = f"-- output values\nCALL {procedure}($1, $2, $3)"
            assert tuple(await connection.fetchrow(query, 2, 5, None)) == (
                Decimal("7"), "done"
            )
            assert tuple(await connection.fetchrow(query, 3, 10, None)) == (
                Decimal("13"), "done"
            )
            statement = await connection.prepare(query)
            assert [parameter.name for parameter in
                    statement.get_parameters()] == [
                "numeric", "numeric", "varchar"
            ]
            assert tuple(await statement.fetchrow(4, 20, None)) == (
                Decimal("24"), "done"
            )
            assert [tuple(row) for row in await statement.fetchmany(
                [(1, 30, None), (2, 40, None)]
            )] == [(Decimal("31"), "done"), (Decimal("42"), "done")]
            assert [tuple(row) for row in await connection.fetchmany(
                query, [(3, 50, None), (4, 60, None)]
            )] == [(Decimal("53"), "done"), (Decimal("64"), "done")]
            assert tuple(await statement.fetchrow(1, None, None)) == (
                None, "done"
            )
            assert await connection.execute(query, 2, 5, None) == "CALL"
            assert await connection.fetchval("SELECT 1") == 1
        finally:
            try:
                await connection.execute(f"DROP PROCEDURE {procedure}")
            finally:
                await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-027")
@pytest.mark.integration
def test_oracle_call_pure_out_parameters_and_transaction_recovery(
    oracle_config: KESConfig,
) -> None:
    """测试点：纯 OUT 返回、命名语句、事务回滚及调用失败后的连接恢复。"""
    async def scenario() -> None:
        table = unique_object_name("call_tx", "oracle")
        procedure = f"{table}_out"
        connection = await asynckb.connect(
            **oracle_config.connection_kwargs()
        )
        try:
            await connection.execute(
                f"CREATE TABLE {table}(id NUMBER PRIMARY KEY)"
            )
            await connection.execute(
                f"CREATE PROCEDURE {procedure}(p_value OUT NUMBER, "
                "p_text OUT VARCHAR2) AS BEGIN "
                f"INSERT INTO {table} VALUES (1); "
                "p_value := 42; p_text := NULL; END;"
            )
            statement = await connection.prepare(
                f'CALL "{procedure}"($1, $2)',
                name="apg_oracle_call_out",
            )
            transaction = connection.transaction()
            await transaction.start()
            assert tuple(await statement.fetchrow(None, None)) == (
                Decimal("42"), None
            )
            await transaction.rollback()
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 0
            assert tuple(await statement.fetchrow(None, None)) == (
                Decimal("42"), None
            )
            with pytest.raises(asynckb.UniqueViolationError):
                await statement.fetchrow(None, None)
            assert await connection.fetchval("SELECT 1") == 1
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 1
        finally:
            try:
                await connection.execute(f"DROP PROCEDURE {procedure}")
            finally:
                await drop_table(connection, table)
                await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-028")
@pytest.mark.parametrize("cache_size", [0, 100])
@pytest.mark.integration
def test_oracle_call_returns_multiple_result_sets(
    oracle_config: KESConfig,
    cache_size: int,
) -> None:
    """测试点：多个结果集的行合并返回，各行保留列名，但不保留集合边界。"""
    async def scenario() -> None:
        procedure = unique_object_name("call_result_sets", "oracle")
        connection = await asynckb.connect(
            **oracle_config.connection_kwargs(),
            statement_cache_size=cache_size,
        )
        try:
            await connection.execute(
                f"CREATE PROCEDURE {procedure} AS "
                "first_cursor SYS_REFCURSOR; "
                "second_cursor SYS_REFCURSOR; BEGIN "
                "OPEN first_cursor FOR SELECT 201 AS first_id; "
                "DBMS_SQL.RETURN_RESULT(first_cursor); "
                "OPEN second_cursor FOR SELECT 'second' AS second_text; "
                "DBMS_SQL.RETURN_RESULT(second_cursor); "
                "OPEN first_cursor FOR SELECT 3.25::numeric AS amount; "
                "DBMS_SQL.RETURN_RESULT(first_cursor); END;"
            )

            rows = await connection.fetch(
                f"CALL {procedure}()"
            )

            expected = [(201,), ("second",), (Decimal("3.25"),)]
            assert [tuple(row) for row in rows] == expected
            assert [tuple(row.keys()) for row in rows] == [
                ("first_id",),
                ("second_text",),
                ("amount",),
            ]
            repeated_rows = await connection.fetch(
                f"CALL {procedure}()"
            )
            assert [tuple(row) for row in repeated_rows] == expected
            assert await connection.fetchval("SELECT 1") == 1
        finally:
            try:
                await connection.execute(f"DROP PROCEDURE {procedure}()")
            finally:
                await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-029")
@pytest.mark.integration
def test_oracle_refcursor_anonymous_portal_can_be_fetched(
    oracle_config: KESConfig,
) -> None:
    """测试点：OUT SYS_REFCURSOR 返回匿名 portal 名，可在事务内 FETCH。"""
    async def scenario() -> None:
        procedure = unique_object_name("refcursor", "oracle")
        connection = await asynckb.connect(
            **oracle_config.connection_kwargs()
        )
        try:
            await connection.execute(
                f"CREATE PROCEDURE {procedure}(p_cursor OUT SYS_REFCURSOR) "
                "AS BEGIN OPEN p_cursor FOR "
                "SELECT 101 AS id, 'ref-cursor-row' AS label; END;"
            )

            async with connection.transaction():
                cursor_name = (await connection.fetchrow(
                    f"CALL {procedure}($1)", None
                ))[0]
                quoted_name = '"' + cursor_name.replace('"', '""') + '"'
                rows = await connection.fetch(f"FETCH ALL FROM {quoted_name}")

            assert [tuple(row) for row in rows] == [(101, "ref-cursor-row")]
        finally:
            try:
                await connection.execute(
                    f"DROP PROCEDURE {procedure}(SYS_REFCURSOR)"
                )
            finally:
                await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-030")
@pytest.mark.parametrize("cache_size", [0, 100])
@pytest.mark.parametrize("command", ["CALL {name}($1)", "EXEC {name} $1"])
@pytest.mark.integration
def test_sqlserver_bound_nested_procedure_result_sets(
    sqlserver_config: KESConfig, cache_size: int, command: str,
) -> None:
    ("""Bound CALL/EXEC must retain every nested result set and """
     """argument value.""")

    async def scenario() -> None:
        inner = unique_object_name("bound_inner", "sqlserver")
        outer = unique_object_name("bound_outer", "sqlserver")
        connection = await asynckb.connect(
            **sqlserver_config.connection_kwargs(),
            statement_cache_size=cache_size,
        )
        try:
            await connection.execute(
                f"CREATE PROCEDURE {inner} @value INT AS BEGIN "
                "SELECT @value AS inner_id; "
                "SELECT 'inside' AS inner_text; END"
            )
            await connection.execute(
                f"CREATE PROCEDURE {outer} @value INT AS BEGIN "
                f"SELECT 1 AS before_id; EXEC {inner} @value; "
                "SELECT 3 AS after_id; END"
            )
            query = "/* nested procedure */ " + command.format(name=outer)
            for value in [7, 9, None]:
                results = await connection.fetch(query, value)
                assert [dict(row) for row in results] == [
                    {"before_id": 1}, {"inner_id": value},
                    {"inner_text": "inside"}, {"after_id": 3},
                ]
            statement = await connection.prepare(query)
            assert statement.get_parameters()[0].name == "int"
            assert [tuple(row) for row in await statement.fetch(11)] == [
                (1,), (11,), ("inside",), (3,),
            ]
            await statement.executemany([(12,), (13,)])
            await connection.executemany(query, [(14,), (15,)])
            assert await connection.execute(query, 16)
            async with connection.transaction():
                assert len(await connection.fetch(query, 17)) == 4
            assert await connection.fetchval("SELECT 987") == 987
        finally:
            try:
                await connection.execute(f"DROP PROCEDURE IF EXISTS {outer}")
                await connection.execute(f"DROP PROCEDURE IF EXISTS {inner}")
            finally:
                await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-031")
@pytest.mark.parametrize("cache_size", [0, 100])
@pytest.mark.parametrize("separator", ["; ", " "])
@pytest.mark.integration
def test_sqlserver_bound_multistatement_select(
    sqlserver_config: KESConfig, cache_size: int, separator: str,
) -> None:
    ("""The server, not Python value guessing, determines batch """
     """parameter types.""")

    async def scenario() -> None:
        connection = await asynckb.connect(
            **sqlserver_config.connection_kwargs(),
            statement_cache_size=cache_size,
        )
        query = separator.join([
            "SELECT CAST($1 AS INTEGER) AS id",
            "SELECT CAST($2 AS VARCHAR(80)) AS label",
        ])
        try:
            for value, label in [(7, "quote'; -- $9"), (None, None)]:
                results = await connection.fetch(query, value, label)
                assert [dict(row) for row in results] == [
                    {"id": value}, {"label": label},
                ]
            statement = await connection.prepare(query)
            assert [
                tuple(row) for row in await statement.fetch(8, "eight")
            ] == [
                (8,), ("eight",),
            ]
            assert [tuple(row) for row in await connection.fetch(
                query, 9, "nine"
            )] == [(9,), ("nine",)]
            assert [tuple(row) for row in await connection.fetchmany(
                query, [(10, "ten"), (11, "eleven")]
            )] == [(10,), ("ten",), (11,), ("eleven",)]
            async with connection.transaction():
                assert len(await connection.fetch(query, 12, "twelve")) == 2
            assert await connection.fetchval("SELECT 987") == 987
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-032")
@pytest.mark.parametrize("api", ["executemany", "fetchmany", "prepared"])
@pytest.mark.integration
def test_sqlserver_bound_multistatement_dml_and_rollback(
    sqlserver_config: KESConfig, api: str,
) -> None:
    ("""Bound batches preserve server-side typing, command status """
     """and atomicity.""")

    async def scenario() -> None:
        table = unique_object_name("bound_batch", "sqlserver")
        connection = await asynckb.connect(
            **sqlserver_config.connection_kwargs()
        )
        query = (f"INSERT INTO {table} VALUES ($1, $2); "
                 f"UPDATE {table} SET label=$3 WHERE id=$1")
        try:
            await connection.execute(
                f"CREATE TABLE {table}(id INT PRIMARY KEY, label VARCHAR(80))"
            )
            assert await connection.execute(
                query, 1, "first", "updated"
            ) == "ANONYMOUS BLOCK"
            await connection.executemany(
                query, [(2, "two", "second"), (3, "three", None)]
            )
            statement = await connection.prepare(query)
            await statement.executemany([(4, "four", "fourth")])
            with pytest.raises(RuntimeError, match="rollback batch"):
                async with connection.transaction():
                    await connection.execute(query, 5, "five", "fifth")
                    raise RuntimeError("rollback batch")
            with pytest.raises(asynckb.UniqueViolationError):
                arguments = [(6, "six", "sixth"), (1, "duplicate", "bad")]
                if api == "prepared":
                    await statement.executemany(arguments)
                else:
                    await getattr(connection, api)(query, arguments)
            assert [tuple(row) for row in await connection.fetch(
                f"SELECT id, label FROM {table} ORDER BY id"
            )] == [(1, "updated"), (2, "second"), (3, None), (4, "fourth")]
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-033")
@pytest.mark.parametrize("standard_strings", ["on", "off"])
@pytest.mark.integration
def test_sqlserver_bound_batch_ignores_placeholder_text_in_strings(
    sqlserver_config: KESConfig, standard_strings: str,
) -> None:
    async def scenario() -> None:
        connection = await asynckb.connect(
            **sqlserver_config.connection_kwargs(),
            server_settings={"standard_conforming_strings": standard_strings},
        )
        try:
            literal = (
                "E'quote\\\'$9'" if standard_strings == "on"
                else "'quote\\\'$9'"
            )
            query = (f"SELECT {literal} AS [$8]; /* $7 /* $6 */ */ "
                     "SELECT CAST($1 AS INT) AS id -- $5\n")
            assert [dict(row) for row in
                    await connection.fetch(query, 7)] == [
                {"$8": "quote'$9"}, {"id": 7},
            ]
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-034")
@pytest.mark.parametrize("api", ["executemany", "fetchmany", "prepared"])
@pytest.mark.parametrize("manual_transaction", [False, True])
@pytest.mark.integration
def test_sqlserver_batch_error_caught_inside_transaction_is_atomic(
    sqlserver_config: KESConfig, api: str, manual_transaction: bool,
) -> None:
    async def scenario():
        con = await asynckb.connect(**sqlserver_config.connection_kwargs())
        table = unique_object_name("batch_outer_transaction", "sqlserver")
        try:
            await con.execute(
                f"CREATE TABLE {table}(id INT PRIMARY KEY, label VARCHAR(30))"
            )
            await con.execute(f"INSERT INTO {table} VALUES(1, 'original')")
            query = (f"INSERT INTO {table} VALUES($1, $2); "
                     f"UPDATE {table} SET label=$3 WHERE id=$1")
            transaction = None if manual_transaction else con.transaction()
            if transaction is None:
                await con.execute("BEGIN TRANSACTION")
            else:
                await transaction.start()
            try:
                with pytest.raises(asynckb.UniqueViolationError):
                    args = [(2, "two", "second"), (1, "duplicate", "bad")]
                    if api == "prepared":
                        await (await con.prepare(query)).executemany(args)
                    else:
                        await getattr(con, api)(query, args)
            except BaseException:
                if transaction is None:
                    await con.execute("ROLLBACK")
                else:
                    await transaction.rollback()
                raise
            else:
                if transaction is None:
                    await con.execute("COMMIT")
                else:
                    await transaction.commit()
            assert [tuple(row) for row in await con.fetch(
                f"SELECT id, label FROM {table} ORDER BY id"
            )] == [(1, "original")]
        finally:
            await drop_table(con, table)
            await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-035")
@pytest.mark.integration
def test_mysql_prepared_statement_row_limit_does_not_corrupt_status(
    mysql_config: KESConfig,
) -> None:
    """测试点：prepared statement 的 fetchval/fetchrow 行限制调用保持状态正确。"""

    async def scenario() -> None:
        connection = await asynckb.connect(**mysql_config.connection_kwargs())
        try:
            statement = await connection.prepare(
                "SELECT generate_series(1, 6)"
            )
            assert await statement.fetchval() == 1
            assert statement.get_statusmsg() is None
            assert await statement.fetchrow() == (1,)
            assert statement.get_statusmsg() is None
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-036")
@pytest.mark.integration
def test_oracle_prepared_statement_cursor_and_returning_support(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle prepared INSERT RETURNING、fetchmany、游标和核心类型元数据。"""

    async def scenario() -> None:
        table = unique_object_name("oracle_core", oracle_config.mode)
        connection = await asynckb.connect(**oracle_config.connection_kwargs())
        try:
            await connection.execute(
                f"CREATE TABLE {table} (id INTEGER GENERATED BY DEFAULT "
                "AS IDENTITY PRIMARY KEY, amount NUMBER(10,2), "
                "payload BLOB, note VARCHAR2(40), "
                "duration INTERVAL DAY TO SECOND, ym INTERVAL YEAR TO MONTH)"
            )
            statement = await connection.prepare(
                f"INSERT INTO {table} (amount, payload, note, duration, ym) "
                "VALUES ($1, $2, $3, $4, $5) RETURNING id",
                name="apg_oracle_core_insert",
            )
            assert [
                parameter.name for parameter in statement.get_parameters()
            ] == [
                "numeric",
                "bytea",
                "varchar",
                "dsinterval",
                "yminterval",
            ]
            assert (
                await statement.fetchval(
                    "12.34",
                    b"abc",
                    "one",
                    datetime.timedelta(days=1, seconds=2),
                    "+02-03",
                )
                == 1
            )
            inserted = await connection.fetchmany(
                f"INSERT INTO {table} (amount, payload, note) "
                "VALUES ($1, $2, $3) RETURNING id",
                [("20.00", b"d", "two"), ("30.00", b"e", "three")],
            )
            assert [row["id"] for row in inserted] == [2, 3]
            query = await connection.prepare(
                "SELECT id, amount, payload, note, duration, ym "
                f"FROM {table} ORDER BY id"
            )
            rows = await query.fetch()
            assert rows[0]["amount"] == Decimal("12.34")
            assert rows[0]["payload"] == b"abc"
            assert rows[0]["duration"] == "+01 00:00:02.000000"
            assert rows[0]["ym"] == "+02-03"
            assert (await query.fetchrow())["id"] == 1
            assert await query.fetchval() == 1
            async with connection.transaction():
                cursor = await query.cursor()
                assert (await cursor.fetchrow())["id"] == 1
                assert [row["id"] for row in await cursor.fetch(1)] == [2]
                assert await cursor.forward(1) == 1
        finally:
            await drop_table(connection, table)
            await connection.close()

    import datetime

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-039")
@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_connection_crud_round_trip(
    kes_config: KESConfig,
) -> None:
    """测试点：异步单连接完整执行新增、查询、更新和删除并返回正确状态。"""
    table = unique_object_name("async_crud", kes_config.mode)
    connection = await asynckb.connect(**kes_config.connection_kwargs())
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


@pytest.mark.case_id("KB-EXEC-042")
@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_transaction_exception_rolls_back_and_recovers(
    kes_config: KESConfig,
) -> None:
    """测试点：异步事务中的业务异常自动回滚且同一连接可继续提交。"""
    table = unique_object_name("async_tx_error", kes_config.mode)
    connection = await asynckb.connect(**kes_config.connection_kwargs())
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


@pytest.mark.case_id("KB-EXEC-043")
@pytest.mark.integration
@pytest.mark.asyncio
async def test_cancelled_async_transaction_rolls_back_and_releases_pool_slot(
    kes_config: KESConfig,
) -> None:
    """测试点：取消异步事务任务会回滚数据并及时归还连接池槽位。"""
    table = unique_object_name("async_tx_cancel", kes_config.mode)
    cleanup = await asynckb.connect(**kes_config.connection_kwargs())
    pool = await asynckb.create_pool(
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


@pytest.mark.case_id("KB-EXEC-045")
@pytest.mark.integration
@pytest.mark.parametrize("isolation", [
    "read_uncommitted", "read_committed", "repeatable_read", "serializable",
])
@pytest.mark.parametrize("readonly", [False, True])
def test_transaction_options_are_scoped_to_the_pg_transaction(
    kes_config: KESConfig, isolation: str, readonly: bool,
) -> None:
    """测试点：三模式复用 PG 事务选项，且不改变下一事务的默认设置。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            query = (
                "SELECT current_setting('transaction_isolation'), "
                "current_setting('transaction_read_only'), "
                "current_setting('transaction_deferrable')"
            )
            defaults = tuple(await connection.fetchrow(query))
            async with connection.transaction(
                isolation=isolation, readonly=readonly, deferrable=True,
            ):
                assert connection.is_in_transaction()
                assert tuple(await connection.fetchrow(query)) == (
                    isolation.replace("_", " "),
                    "on" if readonly else "off", "on",
                )
            assert not connection.is_in_transaction()
            async with connection.transaction():
                assert tuple(await connection.fetchrow(query)) == defaults
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-046")
@pytest.mark.integration
def test_nested_transactions_reuse_pg_savepoint_commands(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式复用 PG 保存点，内层回滚和外层提交的数据正确。"""
    async def scenario() -> None:
        table = unique_object_name("pg_savepoints", kes_config.mode)
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        observer = await asynckb.connect(**kes_config.connection_kwargs())
        queries = []

        def log_query(record):
            queries.append(record.query)

        try:
            await connection.execute(f"CREATE TABLE {table} (id INTEGER)")
            with connection.query_logger(log_query):
                async with connection.transaction():
                    await connection.execute(f"INSERT INTO {table} VALUES (1)")
                    with pytest.raises(RuntimeError, match="undo inner"):
                        async with connection.transaction():
                            await connection.execute(
                                f"INSERT INTO {table} VALUES (2)"
                            )
                            async with connection.transaction():
                                await connection.execute(
                                    f"INSERT INTO {table} VALUES (3)"
                                )
                            raise RuntimeError("undo inner")
                    async with connection.transaction():
                        await connection.execute(
                            f"INSERT INTO {table} VALUES (4)"
                        )
                    assert [tuple(row) for row in await connection.fetch(
                        f"SELECT id FROM {table} ORDER BY id"
                    )] == [(1,), (4,)]
                    assert await observer.fetchval(
                        f"SELECT count(*) FROM {table}"
                    ) == 0
                await asyncio.sleep(0)
            assert [tuple(row) for row in await observer.fetch(
                f"SELECT id FROM {table} ORDER BY id"
            )] == [(1,), (4,)]
            start = (
                "BEGIN TRANSACTION;" if kes_config.mode == "sqlserver"
                else "BEGIN;"
            )
            assert queries[0] == start
            assert sum(query.startswith("SAVEPOINT ")
                       for query in queries) == 3
            assert sum(
                query.startswith("RELEASE SAVEPOINT ") for query in queries
            ) == 2
            assert sum(query.startswith("ROLLBACK TO ")
                       for query in queries) == 1
            with pytest.raises(RuntimeError, match="undo outer"):
                async with connection.transaction():
                    async with connection.transaction():
                        await connection.execute(
                            f"INSERT INTO {table} VALUES (5)"
                        )
                    raise RuntimeError("undo outer")
            assert [tuple(row) for row in await observer.fetch(
                f"SELECT id FROM {table} ORDER BY id"
            )] == [(1,), (4,)]
            assert not connection.is_in_transaction()
        finally:
            await observer.close()
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-047")
@pytest.mark.integration
@pytest.mark.parametrize("isolation, expected", [
    ("read_uncommitted", 2), ("read_committed", 2),
    ("repeatable_read", 1), ("serializable", 1),
])
def test_transaction_isolation_controls_visibility_of_concurrent_commits(
    kes_config: KESConfig, isolation: str, expected: int,
) -> None:
    """测试点：双连接并发提交后，读取结果符合指定的事务隔离级别。"""
    async def scenario() -> None:
        table = unique_object_name("pg_isolation", kes_config.mode)
        reader = await asynckb.connect(**kes_config.connection_kwargs())
        writer = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            await writer.execute(f"CREATE TABLE {table} (id INTEGER)")
            await writer.execute(f"INSERT INTO {table} VALUES (1)")
            async with reader.transaction(isolation=isolation):
                assert await reader.fetchval(f"SELECT id FROM {table}") == 1
                async with writer.transaction():
                    await writer.execute(f"UPDATE {table} SET id = 2")
                assert await reader.fetchval(
                    f"SELECT id FROM {table}"
                ) == expected
            assert await reader.fetchval(f"SELECT id FROM {table}") == 2
        finally:
            await drop_table(writer, table)
            await writer.close()
            await reader.close()

    asyncio.run(scenario())
