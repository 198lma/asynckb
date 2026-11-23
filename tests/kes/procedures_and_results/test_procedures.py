"""Supplemental routine scenarios; no new driver implementation."""

import asyncio

import asynckb
import pytest

from tests.kes.support.config import drop_table, unique_object_name


@pytest.mark.case_id("KB-EXEC-053")
@pytest.mark.parametrize("cache_size", [0, 100])
@pytest.mark.integration
def test_pure_out_parameters_without_query_result_sets(kes_config, cache_size):
    """测试点：三模式纯 OUT、NULL、重复执行和批量返回不依赖过程查询结果集。"""
    async def scenario():
        mode = kes_config.mode
        con = await asynckb.connect(
            **kes_config.connection_kwargs(), statement_cache_size=cache_size,
        )
        name = unique_object_name("pure_output", mode)
        if mode == "mysql":
            ddl = (f"CREATE PROCEDURE {name}(OUT p_value INT, OUT p_text VARCHAR(30)) "
                   "BEGIN SET p_value=42; SET p_text=NULL; END")
        elif mode == "oracle":
            ddl = (f"CREATE PROCEDURE {name}(p_value OUT INTEGER, p_text OUT VARCHAR2) "
                   "AS BEGIN p_value:=42; p_text:=NULL; END;")
        else:
            ddl = (f"CREATE PROCEDURE {name} @p_value INT OUTPUT, "
                   "@p_text VARCHAR(30) OUTPUT AS BEGIN "
                   "SET @p_value=42; SET @p_text=NULL; END")
        created = False
        try:
            await con.execute(ddl)
            created = True
            stmt = await con.prepare(
                f"CALL {name}($1,$2)", parameter_modes=("out", "out"),
            )
            expected = (0, 42, None) if mode == "sqlserver" else (42, None)
            assert tuple(await stmt.fetchrow(None, None)) == expected
            assert tuple(await stmt.fetchrow(None, None)) == expected
            assert [tuple(row) for row in await stmt.fetchmany(
                [(None, None), (None, None)],
            )] == [expected, expected]
            assert await con.fetchval("SELECT 987") == 987
        finally:
            try:
                if created:
                    await con.execute(f"DROP PROCEDURE {name}")
            finally:
                await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-054")
@pytest.mark.parametrize("operation", ["insert", "update", "delete"])
@pytest.mark.integration
def test_oracle_returning_into_output_and_table_state(oracle_config, operation):
    """测试点：普通 DML 在匿名块内输出绑定值，并核对真实表数据与回滚。"""
    async def scenario():
        con = await asynckb.connect(**oracle_config.connection_kwargs())
        table = unique_object_name("return_into", "oracle")
        try:
            await con.execute(f"CREATE TABLE {table}(id INT PRIMARY KEY, label VARCHAR2(30))")
            if operation != "insert":
                await con.execute(f"INSERT INTO {table} VALUES (1,'before')")
            statements = {
                "insert": f"INSERT INTO {table} VALUES ($1,'inserted')",
                "update": f"UPDATE {table} SET label='updated' WHERE id=$1",
                "delete": f"DELETE FROM {table} WHERE id=$1",
            }
            stmt = await con.prepare(
                f"BEGIN {statements[operation]} RETURNING id, label INTO $2,$3; END;",
                parameter_modes=("in", "out", "out"),
            )
            labels = {"insert": "inserted", "update": "updated", "delete": "before"}
            tx = con.transaction()
            await tx.start()
            assert tuple(await stmt.fetchrow(1, None, None)) == (1, labels[operation])
            expected = [] if operation == "delete" else [(1, labels[operation])]
            assert [tuple(row) for row in await con.fetch(f"SELECT * FROM {table}")] == expected
            await tx.rollback()
            expected = [] if operation == "insert" else [(1, "before")]
            assert [tuple(row) for row in await con.fetch(f"SELECT * FROM {table}")] == expected
        finally:
            await drop_table(con, table)
            await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-055")
@pytest.mark.parametrize("invocation", ["SELECT", "CALL", "CALL-explicit-IN"])
@pytest.mark.integration
def test_scalar_function_input_null_and_repeated_calls(kes_config, invocation, record_property):
    """测试点：区分三模式函数 SELECT/CALL 的绑定输入、返回值、NULL 与重复执行。"""
    async def scenario():
        con = await asynckb.connect(**kes_config.connection_kwargs())
        name = unique_object_name("scalar_fn", kes_config.mode)
        if kes_config.mode == "mysql":
            ddl = (f"CREATE FUNCTION {name}(p_value INT) RETURNS INT "
                   "RETURN p_value + 1")
        elif kes_config.mode == "oracle":
            ddl = (f"CREATE FUNCTION {name}(p_value IN INTEGER) RETURN INTEGER "
                   "AS BEGIN RETURN p_value + 1; END;")
        else:
            ddl = (f"CREATE FUNCTION {name}(@p_value INT) RETURNS INT "
                   "AS BEGIN RETURN @p_value + 1; END")
        created = False
        try:
            await con.execute(ddl)
            created = True
            query = (f"SELECT {name}($1) AS answer" if invocation == "SELECT"
                     else f"CALL {name}($1)")
            options = {"parameter_modes": ("in",)} if invocation == "CALL-explicit-IN" else {}
            stmt = await con.prepare(query, **options)
            for value, expected in [(41, 42), (7, 8), (None, None)]:
                if kes_config.mode == "sqlserver" and invocation != "SELECT":
                    # SQL Server CALL discards scalar function results even
                    # with literal arguments; SELECT must still return them.
                    assert await stmt.fetch(value) == []
                    literal = "NULL" if value is None else str(value)
                    assert await con.fetch(f"CALL {name}({literal})") == []
                    assert await con.fetchval(
                        f"SELECT {name}($1)", value) == expected
                    record_property("limitation", "CALL does not return a scalar; use SELECT")
                    continue
                actual = await stmt.fetchval(value)
                assert actual == expected
            assert await con.fetchval("SELECT 987") == 987
        finally:
            try:
                if created:
                    await con.execute(f"DROP FUNCTION {name}")
            finally:
                await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-056")
@pytest.mark.parametrize("cache_size", [0, 100])
@pytest.mark.integration
@pytest.mark.xfail(
    strict=True,
    raises=asynckb.ProtocolError,
    reason="OUT parameters combined with multiple result sets are not supported",
)
def test_output_parameters_together_with_multiple_result_rows(kes_config, cache_size):
    """测试点：同一次过程调用既返回多组查询行，也返回 INOUT 和 OUT 值。"""
    async def scenario():
        mode = kes_config.mode
        name = unique_object_name("mixed_output", mode)
        con = await asynckb.connect(
            **kes_config.connection_kwargs(), statement_cache_size=cache_size,
        )
        if mode == "mysql":
            ddl = (
                f"CREATE PROCEDURE {name}(IN p_add INT, INOUT p_total INT, "
                "OUT p_text VARCHAR(30)) BEGIN SELECT p_add AS first_value; "
                "SELECT 'inside' AS second_value; "
                "SET p_total = p_total + p_add; SET p_text = 'done'; END"
            )
        elif mode == "oracle":
            ddl = (
                f"CREATE PROCEDURE {name}(p_add IN INTEGER, "
                "p_total IN OUT INTEGER, p_text OUT VARCHAR2) AS "
                "c SYS_REFCURSOR; BEGIN "
                "OPEN c FOR SELECT p_add AS first_value; "
                "DBMS_SQL.RETURN_RESULT(c); "
                "OPEN c FOR SELECT 'inside' AS second_value; "
                "DBMS_SQL.RETURN_RESULT(c); "
                "p_total := p_total + p_add; p_text := 'done'; END;"
            )
        else:
            ddl = (
                f"CREATE PROCEDURE {name} @p_add INT, @p_total INT OUTPUT, "
                "@p_text VARCHAR(30) OUTPUT AS BEGIN "
                "SELECT @p_add AS first_value; SELECT 'inside' AS second_value; "
                "SET @p_total = @p_total + @p_add; SET @p_text = 'done'; END"
            )
        created = False
        try:
            await con.execute(ddl)
            created = True
            stmt = await con.prepare(
                f"CALL {name}($1, $2, $3)",
                parameter_modes=("in", "inout", "out"),
            )
            for args, total in [((2, 5, None), 7), ((3, 10, None), 13),
                                ((1, None, None), None)]:
                rows = await stmt.fetch(*args)
                queries = [row for row in rows if len(row) == 1]
                outputs = [row for row in rows if len(row) > 1]
                assert [tuple(row) for row in queries] == [(args[0],), ("inside",)]
                assert [tuple(row.keys()) for row in queries] == [
                    ("first_value",), ("second_value",),
                ]
                expected = (0, total, "done") if mode == "sqlserver" else (total, "done")
                assert [tuple(row) for row in outputs] == [expected]
                assert await con.fetchval("SELECT 987") == 987
        finally:
            try:
                if created:
                    await con.execute(f"DROP PROCEDURE {name}")
            finally:
                await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-057")
@pytest.mark.parametrize("cache_size", [0, 100])
@pytest.mark.integration
def test_mysql_nested_procedure_multiple_results(mysql_config, cache_size):
    """测试点：MySQL 内外层过程返回不同列数和类型时，行序与字段不丢失。"""
    async def scenario():
        con = await asynckb.connect(
            **mysql_config.connection_kwargs(), statement_cache_size=cache_size,
        )
        inner = unique_object_name("inner_proc", "mysql")
        outer = unique_object_name("outer_proc", "mysql")
        created = []
        try:
            await con.execute(
                f"CREATE PROCEDURE {inner}(IN p_value INT) BEGIN "
                "SELECT p_value AS id, 'inside' AS label; "
                "SELECT 99 AS omitted WHERE 1=0; END"
            )
            created.append(inner)
            await con.execute(
                f"CREATE PROCEDURE {outer}(IN p_value INT) BEGIN "
                f"SELECT 1 AS before_id; CALL {inner}(p_value); "
                "SELECT 3 AS after_id; END"
            )
            created.append(outer)
            stmt = await con.prepare(
                f"CALL {outer}($1)", parameter_modes=("in",),
            )
            for value in (7, None):
                rows = await stmt.fetch(value)
                assert [dict(row) for row in rows] == [
                    {"before_id": 1}, {"id": value, "label": "inside"},
                    {"after_id": 3},
                ]
                assert await con.fetchval("SELECT 987") == 987
        finally:
            try:
                for name in reversed(created):
                    await con.execute(f"DROP PROCEDURE {name}")
            finally:
                await con.close()

    asyncio.run(scenario())
