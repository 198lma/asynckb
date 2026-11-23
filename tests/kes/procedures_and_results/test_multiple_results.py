("""ZIP scenarios through existing asynckb APIs, including """
 """explicit limitations.""")

import asyncio

import asynckb
import pytest

from tests.kes.support.config import drop_table, unique_object_name


@pytest.mark.case_id("KB-EXEC-049")
@pytest.mark.parametrize("query", ["select 1; select 2;", "select 1 select 2"])
@pytest.mark.parametrize("api", ["execute", "fetch", "prepare"])
@pytest.mark.integration
def test_zip_original_two_select_forms(
        sqlserver_config, query, api, record_property):
    """测试点：ZIP 原始分号和空格两种多 SELECT 写法，经简单协议和 PBE 执行。"""
    async def scenario():
        con = await asynckb.connect(**sqlserver_config.connection_kwargs())
        try:
            if api == "execute":
                result = await con.execute(query)
                assert result == "SELECT 1"
            else:
                rows = (await con.fetch(query) if api == "fetch"
                        else await (await con.prepare(query)).fetch())
                result = [tuple(row) for row in rows]
                assert result == [(1,), (2,)]
            record_property("actual", repr(result))
            assert await con.fetchval("SELECT 987") == 987
        finally:
            await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-050")
@pytest.mark.parametrize("setting", ["on", "off"])
@pytest.mark.integration
def test_zip_original_nocount_syntax(
        sqlserver_config,
        setting,
        record_property):
    """测试点：原始 SET NOCOUNT ON/OFF 是否被当前 KES 语法接受。"""
    async def scenario():
        con = await asynckb.connect(**sqlserver_config.connection_kwargs())
        try:
            status = await con.execute(f"SET NOCOUNT {setting}")
            assert status == "SET"
            record_property("command_result", status)
            assert await con.fetchval("SELECT 987") == 987
        finally:
            await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-051")
@pytest.mark.parametrize("separator", ["; ", " "])
@pytest.mark.parametrize("nocount", ["on", "off"])
@pytest.mark.parametrize("api", ["execute", "fetch", "prepare"])
@pytest.mark.parametrize("bound", [False, True], ids=["literal", "bound"])
@pytest.mark.integration
def test_zip_dml_with_supported_nocount_setting(
    sqlserver_config, separator, nocount, api, bound, record_property,
):
    """测试点：NOCOUNT 的 KES 可用写法下，多 INSERT/UPDATE 的真实表数据和连接恢复。"""
    async def scenario():
        con = await asynckb.connect(**sqlserver_config.connection_kwargs())
        table = unique_object_name("zip_dml", "sqlserver")
        try:
            await con.execute(
                f"CREATE TABLE {table}(id INT PRIMARY KEY, label VARCHAR(30))"
            )
            await con.execute(f"SET nocount = {nocount}")
            assert (await con.fetchval("SHOW nocount")).lower() == nocount
            if bound:
                parts = [f"INSERT INTO {table} VALUES ($1, $2)",
                         f"INSERT INTO {table} VALUES (2, 'yy')",
                         f"UPDATE {table} SET label='updated' WHERE id=$1"]
                args = (1, "xx")
            else:
                parts = [f"INSERT INTO {table} VALUES (1, 'xx')",
                         f"INSERT INTO {table} VALUES (2, 'yy')",
                         f"UPDATE {table} SET label='updated' WHERE id=1"]
                args = ()
            query = separator.join(parts)
            if api == "prepare":
                result = await (await con.prepare(query)).fetch(*args)
                assert result == []
            else:
                result = await getattr(con, api)(query, *args)
                if api == "fetch":
                    assert result == []
                else:
                    assert isinstance(result, str) and result
            rows = [tuple(row) for row in await con.fetch(
                f"SELECT id, label FROM {table} ORDER BY id"
            )]
            assert rows == [(1, "updated"), (2, "yy")]
            record_property("command_result", repr(result))
            record_property("table_rows", repr(rows))
            assert await con.fetchval("SELECT 987") == 987
        finally:
            await drop_table(con, table)
            await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-EXEC-052")
@pytest.mark.parametrize("cache_size", [0, 100])
@pytest.mark.integration
def test_empty_result_boundary_is_not_exposed(sqlserver_config, cache_size):
    """测试点：fetch 合并返回行，不表示能保留空结果集或通过 nextset 遍历。"""
    async def scenario():
        con = await asynckb.connect(
            **sqlserver_config.connection_kwargs(),
            statement_cache_size=cache_size,
        )
        try:
            rows = await con.fetch(
                "SELECT 1 AS first_value; SELECT 2 AS empty_value WHERE 1=0; "
                "SELECT 'last' AS last_value"
            )
            assert [dict(row) for row in rows] == [
                {"first_value": 1}, {"last_value": "last"},
            ]
            assert await con.fetchval("SELECT 987") == 987
        finally:
            await con.close()

    asyncio.run(scenario())
