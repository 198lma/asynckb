"""Integration tests for prepared statements, scripts, and routines."""

from __future__ import annotations

import asyncio
import gc
from decimal import Decimal

import asyncpg
import pytest

from tests.kes.support.config import KESConfig, drop_table, unique_object_name

pytestmark = pytest.mark.integration


def test_mysql_named_statement_can_be_recreated_after_gc(
    mysql_config: KESConfig,
) -> None:
    """测试点：同名 MySQL prepared statement 释放后可重新创建。"""

    async def scenario() -> None:
        connection = await asyncpg.connect(**mysql_config.connection_kwargs())
        try:
            statement = await connection.prepare(
                "SELECT CAST($1 AS TINYINT)", name="apg_mysql_named_reuse"
            )
            assert await statement.fetchval(1) == 1
            del statement
            gc.collect()
            await connection.fetchval("SELECT 1")
            statement = await connection.prepare(
                "SELECT CAST($1 AS TINYINT)", name="apg_mysql_named_reuse"
            )
            assert await statement.fetchval(2) == 2
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_mysql_manual_deallocate_allows_reprepare(
    mysql_config: KESConfig,
) -> None:
    """测试点：DEALLOCATE 单条和 ALL 后旧对象失效、同名对象可重新准备。"""

    async def scenario() -> None:
        connection = await asyncpg.connect(**mysql_config.connection_kwargs())
        try:
            statement = await connection.prepare(
                "SELECT 1", name="apg_mysql_manual_deallocate"
            )
            assert await statement.fetchval() == 1
            await connection.execute("DEALLOCATE apg_mysql_manual_deallocate")
            with pytest.raises(asyncpg.InterfaceError):
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


def test_mysql_old_statement_gc_does_not_close_replacement(
    mysql_config: KESConfig,
) -> None:
    """测试点：旧 named statement 被 GC 时不能误关闭同名的新 statement。"""

    async def scenario() -> None:
        connection = await asyncpg.connect(**mysql_config.connection_kwargs())
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


def test_duplicate_named_statement_is_rejected_without_replacing_original(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式重复名称必须报错，且原 statement 仍可执行。"""

    async def scenario() -> None:
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        suffix = " FROM dual" if kes_config.mode == "oracle" else ""
        name = f"apg_{kes_config.mode}_duplicate_named_statement"
        try:
            original = await connection.prepare(f"SELECT 1{suffix}", name=name)
            with pytest.raises(asyncpg.DuplicatePreparedStatementError):
                await connection.prepare(f"SELECT 2{suffix}", name=name)
            assert await original.fetchval() == 1
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "deallocate_variant",
    (
        "multi_statement",
        "trailing_comment",
        "deallocate_all_multi_statement",
    ),
    ids=("multi-statement", "trailing-comment", "deallocate-all"),
)
def test_named_statement_recovers_when_deallocate_is_not_a_standalone_command(
    kes_config: KESConfig,
    deallocate_variant: str,
) -> None:
    """测试点：多语句或尾注释 DEALLOCATE 后，三模式同名重建和 GC 正常。"""

    async def scenario() -> None:
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
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
            with pytest.raises(asyncpg.InterfaceError):
                await old_statement.fetchval()

            del old_statement
            gc.collect()
            assert await connection.fetchval(cached_query) == 10
            assert await replacement.fetchval() == 2
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_execute_script_error_preserves_mode_specific_ddl_atomicity(
    kes_config: KESConfig,
) -> None:
    """测试点：多语句错误保留 KES 模式自身的 DDL 原子性语义。"""
    async def scenario() -> None:
        table = unique_object_name("script_atomic", kes_config.mode)
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            with pytest.raises(asyncpg.UndefinedTableError):
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


def test_parameterized_execute_rejects_multiple_commands_before_execution(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式带参数 execute 拒绝多命令且不执行前置 DDL。"""
    async def scenario() -> None:
        table = unique_object_name("script_params", kes_config.mode)
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            expected_error = (
                asyncpg.IndeterminateDatatypeError
                if kes_config.mode == "sqlserver"
                else asyncpg.PostgresSyntaxError
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


def test_mysql_stored_function_binding_and_no_argument_procedure(
    mysql_config: KESConfig,
) -> None:
    """测试点：MySQL 存储函数支持参数绑定，无参存储过程可执行。"""
    async def scenario() -> None:
        table = unique_object_name("mysql_routine", mysql_config.mode)
        procedure = f"{table}_touch"
        function = f"{table}_plus_one"
        connection = await asyncpg.connect(
            **mysql_config.connection_kwargs()
        )
        try:
            await connection.execute(
                f"CREATE TABLE {table} (id INT)"
            )
            await connection.execute(
                f"CREATE PROCEDURE {procedure}() "
                f"INSERT INTO {table} VALUES (1)"
            )
            await connection.execute(
                f"CREATE FUNCTION {function}(value INT) "
                "RETURNS INT RETURN value + 1"
            )

            assert await connection.execute(f"CALL {procedure}()") == "CALL"
            assert await connection.fetchval(
                f"SELECT {function}($1)", 41
            ) == 42
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 1
        finally:
            for statement in (
                f"DROP PROCEDURE IF EXISTS {procedure}",
                f"DROP FUNCTION IF EXISTS {function}",
            ):
                try:
                    await connection.execute(statement)
                except asyncpg.PostgresError:
                    pass
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_oracle_stored_procedure_call_and_parameter_binding_limit(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle CALL 可执行，并明确服务端不支持扩展协议参数绑定。"""
    async def scenario() -> None:
        table = unique_object_name("oracle_routine", oracle_config.mode)
        procedure = f"{table}_add"
        connection = await asyncpg.connect(
            **oracle_config.connection_kwargs()
        )
        try:
            await connection.execute(
                f"CREATE TABLE {table} (id NUMBER, label VARCHAR2(20))"
            )
            await connection.execute(
                f"CREATE OR REPLACE PROCEDURE {procedure}("
                "p_id IN NUMBER, p_label IN VARCHAR2) AS "
                f"BEGIN INSERT INTO {table} VALUES (p_id, p_label); END;"
            )

            with pytest.raises(
                asyncpg.PostgresError,
                match="INVALID MODE.*IN",
            ):
                await connection.execute(
                    f"CALL {procedure}($1, $2)", 8, "eight"
                )

            assert await connection.execute(
                f"CALL {procedure}(8, 'eight')"
            ) == "CALL"
            assert tuple(await connection.fetchrow(
                f"SELECT id, label FROM {table}"
            )) == (Decimal("8"), "eight")
        finally:
            try:
                await connection.execute(f"DROP PROCEDURE {procedure}")
            except asyncpg.PostgresError:
                pass
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_mysql_prepared_statement_row_limit_does_not_corrupt_status(
    mysql_config: KESConfig,
) -> None:
    """测试点：prepared statement 的 fetchval/fetchrow 行限制调用保持状态正确。"""

    async def scenario() -> None:
        connection = await asyncpg.connect(**mysql_config.connection_kwargs())
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


def test_oracle_prepared_statement_cursor_and_returning_support(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle prepared INSERT RETURNING、fetchmany、游标和核心类型元数据。"""

    async def scenario() -> None:
        table = unique_object_name("oracle_core", oracle_config.mode)
        connection = await asyncpg.connect(**oracle_config.connection_kwargs())
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


def test_oracle_pool_named_statement_lifecycle_is_reusable(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle 连接池中 named statement GC、替换和池级查询均正常。"""

    async def scenario() -> None:
        pool_options = oracle_config.connection_kwargs()
        pool_options.pop("timeout")
        pool = await asyncpg.create_pool(
            **pool_options, min_size=1, max_size=2
        )
        try:
            async with pool.acquire() as connection:
                statement = await connection.prepare(
                    "SELECT 44 FROM dual", name="apg_oracle_named_lifecycle"
                )
                assert await statement.fetchval() == 44
                del statement
                gc.collect()
                await connection.fetchval("SELECT 1 FROM dual")
                statement = await connection.prepare(
                    "SELECT 45 FROM dual", name="apg_oracle_named_lifecycle"
                )
                assert await statement.fetchval() == 45
            assert await pool.fetchval("SELECT 46 FROM dual") == 46
        finally:
            await pool.close()

    asyncio.run(scenario())
