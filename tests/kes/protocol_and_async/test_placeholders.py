"""Mode placeholders must retain Bind semantics and protected SQL text."""

import asyncio

import asynckb
from asynckb import kes
import pytest

from tests.kes.support.config import drop_table, unique_object_name


@pytest.mark.case_id("KB-PROTO-001")
@pytest.mark.unit
@pytest.mark.parametrize("mode,query,expected", [
    ("oracle", "/* x */ CALL demo($2, $1, NULL)",
     ("CALL", None, "demo", (2, 1, None))),
    ("sqlserver", 'EXEC "My Schema".[My Proc] $1, $2',
     ("EXEC", "My Schema", "My Proc", (1, 2))),
    ("sqlserver", "SELECT public.demo($1) AS answer",
     ("SELECT", "public", "demo", (1,))),
    ("sqlserver", 'select public.demo($1) as "Answer";',
     ("SELECT", "public", "demo", (1,))),
    ("oracle", "CALL demo($1 + 1)", None),
    ("sqlserver", "SELECT 1; EXEC demo $1", None),
    ("sqlserver", "CALL demo($1); SELECT 1", None),
    ("mysql", "SELECT 'CALL demo($1)'", None),
    ("oracle", "CALL demo($0)", None),
])
def test_routine_bindings_only_identify_single_simple_invocations(
        mode, query, expected):
    assert kes.routine_bindings(query, mode) == expected


@pytest.mark.case_id("KB-PROTO-002")
@pytest.mark.unit
@pytest.mark.parametrize("mode,query,expected", [
    ("mysql", "SELECT ?, ?", "SELECT $1, $2"),
    ("oracle", "SELECT :2, :1, :2", "SELECT $2, $1, $2"),
    ("oracle", "SELECT :label, :LABEL, :other", "SELECT $1, $1, $2"),
    (
        "oracle", "SELECT :name, :1, $2, :NAME, :next",
        "SELECT $3, $1, $2, $3, $4",
    ),
    ("sqlserver", "SELECT @name, @name, @Name", "SELECT $1, $1, $2"),
    ("sqlserver", "SELECT @value, $1, @other", "SELECT $2, $1, $3"),
    (None, "SELECT ?, :name, @name, $1", "SELECT ?, :name, @name, $1"),
    ("oracle", "SELECT $1::int, :value, x := 1", "SELECT $1::int, $2, x := 1"),
    (
        "mysql", "SELECT data ?? 'key', data ?| array['a'], ?",
        "SELECT data ? 'key', data ?| array['a'], $1",
    ),
    ("oracle", "SELECT foo$1, :name, :2, :NAME", "SELECT foo$1, $1, $2, $1"),
    (
        "sqlserver", "DECLARE @x INT=@input; SELECT @X, @input",
        "DECLARE @x INT=$1; SELECT @X, $1",
    ),
    (
        "sqlserver", "DECLARE @ret INT; EXEC @ret=demo @formal=@value",
        "DECLARE @ret INT; EXEC @ret=demo @formal=$1",
    ),
])
def test_placeholder_numbering(mode, query, expected):
    assert kes.rewrite_query(query, mode) == expected


@pytest.mark.case_id("KB-PROTO-003")
@pytest.mark.unit
@pytest.mark.parametrize(
    "mode,marker",
    [("mysql", "?"), ("oracle", ":value"), ("sqlserver", "@value")],
)
def test_literals_identifiers_and_comments_are_not_parameters(mode, marker):
    protected = (
        f"'{marker}''{marker}', \"{marker}\", "
        f"$tag${marker}$tag$, $$ {marker} $$ "
        f"/* {marker} /* {marker} */ {marker} */ -- {marker}\n"
    )
    assert kes.rewrite_query(
        "SELECT " + protected + marker,
        mode) == "SELECT " + protected + "$1"


@pytest.mark.case_id("KB-PROTO-004")
@pytest.mark.unit
def test_mode_specific_quoted_regions_and_escape_strings():
    assert kes.rewrite_query(
        "SELECT `?``?`, ? # ?\n, ?",
        "mysql") == "SELECT `?``?`, $1 # ?\n, $2"
    assert kes.rewrite_query(
        "SELECT q'[a :x ' :x]', :x",
        "oracle") == "SELECT q'[a :x ' :x]', $1"
    assert kes.rewrite_query(
        "SELECT q'!a :x ' :x!', :x",
        "oracle") == "SELECT q'!a :x ' :x!', $1"
    assert kes.rewrite_query(
        "SELECT [@x]]@x], @@ROWCOUNT, @x",
        "sqlserver") == "SELECT [@x]]@x], @@ROWCOUNT, $1"
    assert kes.rewrite_query(
        r"SELECT E'it\'s :x', :x",
        "oracle") == r"SELECT E'it\'s :x', $1"
    assert kes.rewrite_query(
        r"SELECT 'it\'s ?', ?",
        "mysql",
        standard_conforming_strings=False) == r"SELECT 'it\'s ?', $1"


@pytest.mark.case_id("KB-PROTO-006")
@pytest.mark.unit
def test_sqlserver_locals_and_exec_labels_are_not_bind_slots():
    query = (
        "DECLARE @local INT=1, @other DECIMAL(10,2); "
        "SET @local=@input; SELECT @local, @other, @input"
    )
    expected = (
        "DECLARE @local INT=1, @other DECIMAL(10,2); "
        "SET @local=$1; SELECT @local, @other, $1"
    )
    assert kes.rewrite_query(query, "sqlserver") == expected
    assert kes.rewrite_query(
        "EXEC demo @formal=@value, @second=@value",
        "sqlserver") == "EXEC demo @formal=$1, @second=$1"


@pytest.mark.case_id("KB-PROTO-008")
@pytest.mark.unit
@pytest.mark.parametrize("query", [
    "SET @missing=1",
    "SELECT @missing=1",
    "SET @missing+=1",
    "EXEC @ret=demo @formal=@value",
    "CREATE PROCEDURE demo @arg INT AS SELECT @arg",
    "ALTER FUNCTION demo(@arg INT) RETURNS INT AS BEGIN RETURN @arg END",
])
def test_sqlserver_ambiguous_assignments_and_routine_definitions_rejected(
        query):
    with pytest.raises(asynckb.InterfaceError):
        kes.rewrite_query(query, "sqlserver")


@pytest.mark.case_id("KB-PROTO-009")
@pytest.mark.unit
@pytest.mark.parametrize("mode,query",
                         [("mysql",
                           "SELECT ?, $1"),
                          ("oracle",
                           "SELECT :0"),
                             ("oracle",
                              "SELECT :32768"),
                             ("sqlserver",
                              "SELECT $32768, @x")])
def test_invalid_or_ambiguous_parameter_numbers_rejected(mode, query):
    with pytest.raises(asynckb.InterfaceError):
        kes.rewrite_query(query, mode)


def marker(mode, number=1):
    return {
        "mysql": "?",
        "oracle": f":{number}",
        "sqlserver": f"@p{number}"}[mode]


@pytest.mark.case_id("KB-PROTO-010")
@pytest.mark.integration
@pytest.mark.parametrize("cache_size", [0, 100])
def test_mode_placeholders_query_prepare_batch_cursor_and_recovery(
        kes_config, cache_size):
    async def scenario():
        con = await asynckb.connect(
            **kes_config.connection_kwargs(), statement_cache_size=cache_size,
        )
        table = unique_object_name("placeholders", kes_config.mode)
        p1, p2 = marker(kes_config.mode), marker(kes_config.mode, 2)
        try:
            await con.execute(
                f"CREATE TABLE {table}(id INT PRIMARY KEY, label VARCHAR(80))"
            )
            insert = f"INSERT INTO {table} VALUES ({p1}, {p2})"
            await con.execute(insert, 1, "one")
            await con.executemany(insert, [(2, "two"), (3, "three")])
            query = f"SELECT label FROM {table} WHERE id={p1}"
            assert await con.fetchval(query, 1) == "one"
            assert tuple(await con.fetchrow(query, 2)) == ("two",)
            assert [tuple(r) for r in await con.fetch(query, 3)] == [
                ("three",)
            ]
            assert [tuple(r) for r in await con.fetchmany(
                query, [(1,), (2,)]
            )] == [("one",), ("two",)]
            stmt = await con.prepare(query)
            assert stmt.get_query() == query
            assert await stmt.fetchval(1) == "one"
            assert await stmt.fetchval(2) == "two"
            assert [tuple(r) for r in await stmt.fetchmany(
                [(1,), (3,)]
            )] == [("one",), ("three",)]
            await (await con.prepare(insert)).executemany([(4, "four")])
            with pytest.raises(asynckb.InterfaceError):
                await stmt.fetchval(1, 2)
            with pytest.raises(asynckb.InterfaceError):
                await con.fetchval(query)
            assert await stmt.fetchval(3) == "three"
            async with con.transaction():
                cursor = con.cursor(
                    f"SELECT id FROM {table} WHERE id>=CAST({p1} AS INT) "
                    "ORDER BY id", 2)
                assert [r[0] async for r in cursor] == [2, 3, 4]
            text = "quote'; -- ? :value @value $9"
            update_args = (
                1, text) if kes_config.mode == "oracle" else (
                text, 1)
            await con.execute(
                f"UPDATE {table} SET label={p2} WHERE id={p1}",
                *update_args,
            )
            assert await con.fetchval(query, 1) == text
            assert await con.fetchval(f"SELECT count(*) FROM {table}") == 4
            assert await con.fetchval("SELECT CAST($1 AS INT)", 987) == 987
        finally:
            await drop_table(con, table)
            await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-011")
@pytest.mark.integration
def test_placeholder_literals_comments_and_zero_argument_execute(kes_config):
    async def scenario():
        mode = kes_config.mode
        con = await asynckb.connect(**kes_config.connection_kwargs())
        p = marker(mode)
        try:
            row = await con.fetchrow(
                f"SELECT CAST({p} AS INT) AS value, "
                "'? :name @name $9' AS literal "
                f"/* {p} */ -- {p}\n", 42,
            )
            assert tuple(row) == (42, "? :name @name $9")
            assert await con.execute("SELECT '? :name @name $9'") == "SELECT 1"
            stmt = await con.prepare(f"SELECT CAST({p} AS INT)")
            expected_type = "int" if mode == "sqlserver" else "int4"
            assert [p.name for p in stmt.get_parameters()] == [expected_type]
            with pytest.raises(asynckb.DataError):
                await stmt.fetchval("not-an-integer")
            assert await stmt.fetchval(42) == 42
            assert await stmt.fetchval(None) is None
            if mode == "sqlserver":
                assert await con.fetchval(
                    "SELECT 1 WHERE @value=42", 42) == 1
                assert await con.fetchval(
                    "SELECT CASE WHEN @value=42 THEN 1 ELSE 0 END", 42) == 1
        finally:
            await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-012")
@pytest.mark.integration
def test_sqlserver_local_and_named_exec_server_restrictions(sqlserver_config):
    async def scenario():
        con = await asynckb.connect(**sqlserver_config.connection_kwargs())
        proc = unique_object_name("placeholder_exec", "sqlserver")
        created = False
        try:
            for placeholder in ("@input", "$1"):
                with pytest.raises(asynckb.UndefinedParameterError) as error:
                    await con.fetch(
                        "DECLARE @local INT; "
                        f"SET @local={placeholder}; "
                        "SELECT @local AS value", 42,
                    )
                assert error.value.sqlstate == "42P02"
            await con.execute(
                f"CREATE PROCEDURE {proc} @formal INT AS BEGIN "
                "SELECT @formal AS value; END"
            )
            created = True
            for placeholder in ("@input", "$1"):
                with pytest.raises(asynckb.PostgresSyntaxError) as error:
                    await con.fetch(f"EXEC {proc} @formal={placeholder}", 42)
                assert error.value.sqlstate == "42601"
            statement = await con.prepare(f"EXEC {proc} @input")
            parameter = statement.get_parameters()[0]
            assert (parameter.schema, parameter.name) == ("sys", "int")
            rows = await statement.fetch(42)
            assert [dict(row) for row in rows] == [{"value": 42}]
            assert type(rows[0][0]) is int
            with pytest.raises(asynckb.InterfaceError):
                await con.fetch("SET @missing=@input; SELECT @missing", 1)
            assert await con.fetchval("SELECT CAST(@input AS INT)", 987) == 987
        finally:
            try:
                if created:
                    await con.execute(f"DROP PROCEDURE {proc}")
            finally:
                await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-013")
@pytest.mark.integration
def test_named_placeholders_reuse_and_reserved_numbers(kes_config):
    async def scenario():
        con = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            if kes_config.mode == "oracle":
                query = (
                    "SELECT CAST(:name AS INT)+CAST(:NAME AS INT)+"
                    "CAST(:1 AS INT)+CAST($2 AS INT)"
                )
                assert await con.fetchval(query, 1, 2, 10) == 23
            elif kes_config.mode == "sqlserver":
                query = (
                    "SELECT CAST(@x AS INT)+CAST(@x AS INT)+"
                    "CAST(@X AS INT)+CAST($1 AS INT)"
                )
                assert await con.fetchval(query, 1, 10, 2) == 23
            else:
                assert tuple(await con.fetchrow(
                    "SELECT CAST(? AS INT), '?'", 10
                )) == (10, "?")
        finally:
            await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-014")
@pytest.mark.integration
def test_cursor_cleanup_preserves_cached_rewritten_statement(kes_config):
    async def scenario():
        con = await asynckb.connect(**kes_config.connection_kwargs())
        query = f"SELECT CAST({marker(kes_config.mode)} AS INT) AS value"

        async def prepared_names():
            return {row["name"] for row in await con.fetch(
                "SELECT name FROM pg_catalog.pg_prepared_statements "
                "WHERE statement=$1", "SELECT CAST($1 AS INT) AS value")}

        try:
            assert await con.fetchval(query, 42) == 42
            names_before = await prepared_names()
            assert len(names_before) == 1
            async with con.transaction():
                assert [row[0] async for row in con.cursor(query, 7)] == [7]
            assert await con.fetchval(query, 99) == 99
            assert await prepared_names() == names_before
        finally:
            await con.close()

    asyncio.run(scenario())
