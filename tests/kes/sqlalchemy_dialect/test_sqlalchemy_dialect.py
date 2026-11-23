"""Tests for the sqlalchemy dialect requirement module."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from urllib.parse import quote
import asynckb
import pytest
from tests.kes.support.config import KESConfig, drop_table, unique_object_name
from tests.kes.support.sqlalchemy_support import register_kes_dialects

sqlalchemy = pytest.importorskip("sqlalchemy")


@pytest.mark.case_id("KB-SA-001")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlserver_native_column_types_reflect_from_catalog(
    sqlserver_config: KESConfig,
) -> None:
    ("""Column reflection must not depend on removed """
     """information_schema fields.""")

    async def scenario() -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        engine = create_async_engine(sqlserver_config.sqlalchemy_dsn())
        table = unique_object_name("native_reflection", "sqlserver")
        try:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(
                    f"CREATE TABLE {table}(id INT, amount NUMERIC(20,4), "
                    "label NVARCHAR(30), event_date DATE, "
                    "event_time DATETIME2(3))"
                )
                columns = await connection.run_sync(
                    lambda sync: sqlalchemy.inspect(sync).get_columns(table))
                assert [column["name"] for column in columns] == [
                    "id", "amount", "label", "event_date", "event_time",
                ]
                assert isinstance(columns[0]["type"], sqlalchemy.Integer)
                assert isinstance(columns[1]["type"], sqlalchemy.Numeric)
                assert columns[1]["type"].precision == 20
                assert columns[1]["type"].scale == 4
                assert isinstance(columns[2]["type"], sqlalchemy.Unicode)
                assert columns[2]["type"].length == 30
                assert isinstance(columns[3]["type"], sqlalchemy.Date)
                assert columns[4]["type"].precision == 3
        finally:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(
                    f"DROP TABLE IF EXISTS {table}"
                )
            await engine.dispose()

    asyncio.run(scenario())


def _sqlalchemy_url(config: KESConfig, query: str) -> str:
    user = quote(config.user, safe="")
    password = quote(config.password, safe="")
    database = quote(config.database, safe="")
    return (
        f"kingbase+asynckb://{user}:{password}@"
        f"{config.host}:{config.port}/{database}?{query}"
    )


pytest.importorskip("alembic")
pytest.importorskip("sqlalchemy")


@pytest.mark.case_id("KB-SA-002")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_unified_url_detects_and_loads_mode_dialect(
    kes_config: KESConfig,
) -> None:
    """测试点：统一 URL 自动加载模式方言并使用 asynckb 参数绑定。"""
    async def scenario() -> None:
        from sqlalchemy import bindparam, select
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        engine = create_async_engine(
            _sqlalchemy_url(kes_config, "sslmode=disable"),
            pool_size=1,
            max_overflow=0,
        )
        expected_classes = {
            "mysql": "KESMySQLDialect_asynckb",
            "oracle": "KESOracleDialect_asynckb",
            "sqlserver": "KESSQLServerDialect_asynckb",
        }
        try:
            async with engine.connect() as connection:
                raw = await connection.get_raw_connection()
                assert (
                    raw.driver_connection.get_kes_mode()
                    == kes_config.mode
                )
                assert type(connection.dialect).__name__ == expected_classes[
                    kes_config.mode
                ]
                statement = select(
                    bindparam("value", type_=sqlalchemy.Integer)
                )
                if kes_config.mode == "oracle":
                    statement = statement.select_from(sqlalchemy.text("dual"))
                compiled = str(statement.compile(dialect=connection.dialect))
                assert "CAST($1 AS INTEGER)" in compiled
                assert (
                    await connection.scalar(statement, {"value": 9})
                ) == 9
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-004")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_url_options_connect_in_all_kes_modes(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式 async engine 支持 URL 中的 SSL、缓存和超时连接参数。"""

    async def scenario() -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        query = (
            "sslmode=disable&prepared_statement_cache_size=0&"
            "statement_cache_size=2&max_cached_statement_lifetime=1.5&"
            "max_cacheable_statement_size=2048&command_timeout=5&timeout=5"
        )
        for config in (kes_config,):
            engine = create_async_engine(_sqlalchemy_url(config, query))
            try:
                async with engine.connect() as connection:
                    raw = await connection.get_raw_connection()
                    driver_connection = raw.driver_connection
                    assert driver_connection.get_kes_mode() == config.mode
                    assert driver_connection._config.statement_cache_size == 2
                    assert driver_connection._config.command_timeout == 5.0
                    result = await connection.exec_driver_sql(
                        config.select_one
                    )
                    assert result.scalar_one() == 1
            finally:
                await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-006")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_autocommit_detection_in_all_kes_modes(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式方言在 AUTOCOMMIT 下可跳过无效的连接归还回滚。"""

    async def scenario() -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        for config in (kes_config,):
            engine = create_async_engine(
                _sqlalchemy_url(config, "sslmode=disable"),
                isolation_level="AUTOCOMMIT",
                skip_autocommit_rollback=True,
            )
            try:
                async with engine.connect() as connection:
                    result = await connection.exec_driver_sql(
                        config.select_one
                    )
                    assert result.scalar_one() == 1
            finally:
                await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-008")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_reports_server_session_isolation_level(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式 get_isolation_level 返回 KES 会话实际隔离级别。"""

    async def scenario() -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        for config in (kes_config,):
            engine = create_async_engine(
                _sqlalchemy_url(config, "sslmode=disable")
            )
            try:
                async with engine.connect() as connection:
                    await connection.exec_driver_sql(
                        "SET SESSION CHARACTERISTICS AS TRANSACTION "
                        "ISOLATION LEVEL SERIALIZABLE"
                    )
                    await connection.commit()
                    assert await connection.get_isolation_level() == (
                        "SERIALIZABLE"
                    )
            finally:
                await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-009")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_pool_pre_ping_replaces_terminated_connections(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式连接被服务端终止后 pool_pre_ping 自动建立新连接。"""

    async def scenario() -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        for config in (kes_config,):
            engine = create_async_engine(
                _sqlalchemy_url(config, "sslmode=disable"),
                pool_pre_ping=True,
                pool_size=1,
                max_overflow=0,
            )
            killer = await asynckb.connect(**config.connection_kwargs())
            try:
                async with engine.connect() as connection:
                    raw = await connection.get_raw_connection()
                    first_pid = raw.driver_connection.get_server_pid()

                assert (
                    await killer.fetchval(
                        "SELECT pg_terminate_backend($1)", first_pid
                    )
                    is True
                )

                async with engine.connect() as connection:
                    raw = await connection.get_raw_connection()
                    second_pid = raw.driver_connection.get_server_pid()
                    assert second_pid != first_pid
                    result = await connection.exec_driver_sql(
                        config.select_one
                    )
                    assert result.scalar_one() == 1
            finally:
                await killer.close()
                await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-010")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_deallocate_all_invalidates_both_statement_caches(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式 DEALLOCATE ALL 后 SQLAlchemy 和 asynckb 缓存同步重建。"""

    async def scenario() -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        for config in (kes_config,):
            engine = create_async_engine(
                _sqlalchemy_url(config, "sslmode=disable"),
                pool_size=1,
                max_overflow=0,
            )
            try:
                async with engine.connect() as connection:
                    for expected in (41, 42):
                        query = (
                            f"SELECT {expected} FROM dual"
                            if config.mode == "oracle"
                            else f"SELECT {expected}"
                        )
                        result = await connection.exec_driver_sql(query)
                        assert result.scalar_one() == expected

                    await connection.exec_driver_sql("DEALLOCATE ALL")

                    for expected in (41, 42):
                        query = (
                            f"SELECT {expected} FROM dual"
                            if config.mode == "oracle"
                            else f"SELECT {expected}"
                        )
                        result = await connection.exec_driver_sql(query)
                        assert result.scalar_one() == expected
            finally:
                await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-011")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_views_and_multi_reflection_in_all_kes_modes(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式方言支持视图发现、定义、查询和 SQLAlchemy 2 批量反射。"""

    async def scenario() -> None:
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        for config in (kes_config,):
            table_name = unique_object_name("sa_view_table", config.mode)
            view_name = unique_object_name("sa_view", config.mode)
            engine = create_async_engine(
                _sqlalchemy_url(config, "sslmode=disable")
            )
            try:
                async with engine.begin() as connection:
                    await connection.exec_driver_sql(
                        f"CREATE TABLE {table_name} ("
                        "id INTEGER PRIMARY KEY, name VARCHAR(20))"
                    )
                    await connection.exec_driver_sql(
                        f"INSERT INTO {table_name} VALUES (1, 'view-row')"
                    )
                    await connection.exec_driver_sql(
                        f"CREATE VIEW {view_name} AS "
                        f"SELECT id, name FROM {table_name}"
                    )

                async with engine.connect() as connection:

                    def reflect(sync_connection):
                        inspector = inspect(sync_connection)
                        return (
                            inspector.get_view_names(),
                            inspector.get_view_definition(view_name),
                            inspector.has_table(view_name),
                            inspector.get_multi_columns(
                                filter_names=[table_name]
                            ),
                            inspector.get_multi_pk_constraint(
                                filter_names=[table_name]
                            ),
                        )

                    views, definition, has_view, columns, primary_keys = (
                        await connection.run_sync(reflect)
                    )
                    assert view_name in views
                    assert table_name.lower() in definition.lower()
                    assert has_view is True
                    assert [
                        column["name"]
                        for column in columns[(None, table_name)]
                    ] == ["id", "name"]
                    assert primary_keys[(None, table_name)][
                        "constrained_columns"
                    ] == ["id"]
                    result = await connection.exec_driver_sql(
                        f"SELECT id, name FROM {view_name}"
                    )
                    assert result.one() == (1, "view-row")
            finally:
                async with engine.begin() as connection:
                    await connection.exec_driver_sql(
                        f"DROP VIEW IF EXISTS {view_name}"
                    )
                    await connection.exec_driver_sql(
                        f"DROP TABLE IF EXISTS {table_name}"
                    )
                await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-012")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_quoted_identifiers_and_nested_transactions(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式 quoted 标识符完整反射且 SQLAlchemy 保存点可提交回滚。"""

    async def scenario() -> None:
        from sqlalchemy import Column, Index, Integer, MetaData, Sequence
        from sqlalchemy import String, Table, inspect, select
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.sql import quoted_name

        register_kes_dialects()
        token = uuid.uuid4().hex[:6]
        table_name = quoted_name(f"ApgQTable{token}", True)
        view_name = quoted_name(f"ApgQView{token}", True)
        index_name = quoted_name(f"ApgQIndex{token}", True)
        sequence_name = quoted_name(f"ApgQSeq{token}", True)
        metadata = MetaData()
        table = Table(
            table_name,
            metadata,
            Column(
                quoted_name("select", True),
                Integer,
                primary_key=True,
                comment="reserved column",
            ),
            Column(
                quoted_name("MixedValue", True),
                String(30),
                nullable=False,
                comment="mixed column",
            ),
            comment="quoted table",
        )
        Index(index_name, table.c.MixedValue)
        sequence = Sequence(sequence_name)
        engine = create_async_engine(
            _sqlalchemy_url(kes_config, "sslmode=disable")
        )

        try:
            async with engine.begin() as connection:
                await connection.run_sync(metadata.drop_all, checkfirst=True)
                if kes_config.mode == "oracle":
                    await connection.run_sync(
                        lambda sync: sequence.drop(sync, checkfirst=True)
                    )
                    await connection.run_sync(sequence.create)
                await connection.run_sync(metadata.create_all)

                preparer = connection.dialect.identifier_preparer
                quoted_table = preparer.quote_identifier(str(table_name))
                quoted_view = preparer.quote_identifier(str(view_name))
                quoted_reserved = preparer.quote_identifier("select")
                quoted_mixed = preparer.quote_identifier("MixedValue")
                await connection.exec_driver_sql(
                    f"CREATE VIEW {quoted_view} AS SELECT "
                    f"{quoted_reserved}, {quoted_mixed} FROM {quoted_table}"
                )

            async with engine.connect() as connection:
                outer = await connection.begin()
                nested = await connection.begin_nested()
                await connection.execute(
                    table.insert().values(
                        {
                            "select": 1,
                            "MixedValue": "rollback",
                        }
                    )
                )
                await nested.rollback()

                nested = await connection.begin_nested()
                await connection.execute(
                    table.insert().values(
                        {
                            "select": 2,
                            "MixedValue": "commit",
                        }
                    )
                )
                await nested.commit()
                await outer.commit()

                def reflect(sync_connection):
                    inspector = inspect(sync_connection)
                    reflected = Table(
                        table_name,
                        MetaData(),
                        autoload_with=sync_connection,
                    )
                    return (
                        inspector.has_table(table_name),
                        inspector.get_table_names(),
                        inspector.get_columns(table_name),
                        inspector.get_pk_constraint(table_name),
                        inspector.get_indexes(table_name),
                        inspector.get_table_comment(table_name),
                        inspector.get_view_names(),
                        inspector.get_view_definition(view_name),
                        (
                            inspector.has_sequence(sequence_name)
                            if kes_config.mode == "oracle"
                            else None
                        ),
                        reflected,
                    )

                reflected_data = await connection.run_sync(reflect)
                (
                    has_table,
                    table_names,
                    columns,
                    primary_key,
                    indexes,
                    table_comment,
                    view_names,
                    view_definition,
                    has_sequence,
                    reflected,
                ) = reflected_data

                assert has_table is True
                assert str(table_name) in [str(name) for name in table_names]
                assert [column["name"].lower() for column in columns] == [
                    "select",
                    "mixedvalue",
                ]
                assert [column.get("comment") for column in columns] == [
                    "reserved column",
                    "mixed column",
                ]
                assert [
                    name.lower() for name in primary_key["constrained_columns"]
                ] == ["select"]
                assert [str(item["name"]) for item in indexes] == [
                    str(index_name)
                ]
                assert table_comment == {"text": "quoted table"}
                assert str(view_name) in [str(name) for name in view_names]
                assert str(table_name).lower() in view_definition.lower()
                assert has_sequence is (
                    True if kes_config.mode == "oracle" else None
                )
                assert (await connection.execute(select(reflected))).one() == (
                    2,
                    "commit",
                )
        finally:
            async with engine.begin() as connection:
                preparer = connection.dialect.identifier_preparer
                quoted_view = preparer.quote_identifier(str(view_name))
                await connection.exec_driver_sql(
                    f"DROP VIEW IF EXISTS {quoted_view}"
                )
                await connection.run_sync(metadata.drop_all, checkfirst=True)
                if kes_config.mode == "oracle":
                    await connection.run_sync(
                        lambda sync: sequence.drop(sync, checkfirst=True)
                    )
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-013")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_mysql_crud_and_catalog_reflection(
    mysql_config: KESConfig,
) -> None:
    """测试点：MySQL 方言覆盖建表、插入、upsert、分页、流式读取和完整反射。"""

    async def scenario() -> None:
        from sqlalchemy import (
            Column,
            ForeignKey,
            Integer,
            MetaData,
            String,
            Table,
            inspect,
            select,
            text,
        )
        from sqlalchemy.dialects.mysql import (
            BIT,
            CHAR,
            DOUBLE,
            ENUM,
            FLOAT,
            SET,
            insert,
        )
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        engine = create_async_engine(
            mysql_config.sqlalchemy_dsn(), pool_size=1, max_overflow=0
        )
        metadata = MetaData()
        table_name = unique_object_name("sa_mysql", "mysql")
        child_name = f"{table_name}_child"
        types_name = f"{table_name}_types"
        table = Table(
            table_name,
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("name", String(40), nullable=False, unique=True),
        )
        child = Table(
            child_name,
            metadata,
            Column("id", Integer, primary_key=True),
            Column(
                "parent_id",
                Integer,
                ForeignKey(
                    f"{table_name}.id",
                    name=f"fk_{table_name}_parent",
                    ondelete="CASCADE",
                ),
            ),
            Column("label", String(40), index=True),
        )
        try:
            async with engine.begin() as connection:
                await connection.run_sync(metadata.drop_all, checkfirst=True)
                await connection.run_sync(metadata.create_all)
                await connection.exec_driver_sql(
                    f"DROP TABLE IF EXISTS {types_name}"
                )
                await connection.exec_driver_sql(
                    f"CREATE TABLE {types_name} ("
                    "id INT AUTO_INCREMENT PRIMARY KEY, "
                    "state ENUM('new','done') DEFAULT 'new' "
                    "COMMENT 'state comment', "
                    "flags SET('a','b') DEFAULT 'a,b' "
                    "COMMENT 'flags comment', "
                    "bits BIT(8), fixed CHAR(5), single_value FLOAT, "
                    "double_value DOUBLE, base INT, "
                    "amount DECIMAL(10,2) DEFAULT 12.34, "
                    "note VARCHAR(20) DEFAULT 'x', "
                    "doubled INT GENERATED ALWAYS AS (base * 2) STORED) "
                    "COMMENT='types table comment'"
                )
                result = await connection.execute(
                    table.insert().values(name="alpha")
                )
                assert result.inserted_primary_key == (1,)
                await connection.execute(
                    table.insert(), [{"name": "beta"}, {"name": "gamma"}]
                )
                upsert = insert(table).values(id=1, name="updated")
                await connection.execute(
                    upsert.on_duplicate_key_update(name=upsert.inserted.name)
                )
                await connection.execute(
                    child.insert().values(id=1, parent_id=1, label="child")
                )

            async with engine.connect() as connection:
                rows = (
                    await connection.execute(
                        select(table).order_by(table.c.id).limit(2).offset(1)
                    )
                ).all()
                assert [row.name for row in rows] == ["beta", "gamma"]
                assert (
                    await connection.scalar(
                        select(table.c.name).where(table.c.id == 1)
                    )
                    == "updated"
                )
                stream = await connection.stream_scalars(
                    text("SELECT generate_series(1, 5)")
                )
                assert [value async for value in stream] == [1, 2, 3, 4, 5]

                def reflect(sync_connection):
                    inspector = inspect(sync_connection)
                    return (
                        inspector.get_columns(table_name),
                        inspector.get_pk_constraint(table_name),
                        inspector.get_unique_constraints(table_name),
                        inspector.get_foreign_keys(child_name),
                        inspector.get_indexes(child_name),
                        inspector.get_columns(types_name),
                        inspector.get_table_comment(types_name),
                    )

                (
                    columns,
                    primary_key,
                    unique,
                    foreign_keys,
                    indexes,
                    type_columns,
                    table_comment,
                ) = await connection.run_sync(reflect)
                assert [column["name"] for column in columns] == ["id", "name"]
                assert columns[0]["autoincrement"] is True
                assert primary_key["constrained_columns"] == ["id"]
                assert [item["column_names"] for item in unique] == [["name"]]
                assert foreign_keys[0]["constrained_columns"] == ["parent_id"]
                assert foreign_keys[0]["referred_columns"] == ["id"]
                assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
                assert [item["column_names"] for item in indexes] == [
                    ["label"]
                ]
                reflected_types = {
                    column["name"]: column for column in type_columns
                }
                assert isinstance(reflected_types["state"]["type"], ENUM)
                assert reflected_types["state"]["type"].enums == [
                    "new",
                    "done",
                ]
                assert reflected_types["state"]["default"] == "'new'"
                assert reflected_types["state"]["comment"] == "state comment"
                assert isinstance(reflected_types["flags"]["type"], SET)
                assert reflected_types["flags"]["type"].values == ("a", "b")
                assert isinstance(reflected_types["bits"]["type"], BIT)
                assert reflected_types["bits"]["type"].length == 8
                assert isinstance(reflected_types["fixed"]["type"], CHAR)
                assert reflected_types["fixed"]["type"].length == 5
                assert isinstance(
                    reflected_types["single_value"]["type"], FLOAT
                )
                assert isinstance(
                    reflected_types["double_value"]["type"], DOUBLE
                )
                assert (
                    reflected_types["doubled"]["computed"]["sqltext"]
                    == "(base * 2)"
                )
                assert (
                    reflected_types["doubled"]["computed"]["persisted"] is True
                )
                assert reflected_types["amount"]["default"] == "12.34"
                assert reflected_types["note"]["default"] == "'x'"
                assert table_comment == {"text": "types table comment"}
        finally:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(
                    f"DROP TABLE IF EXISTS {types_name}"
                )
                await connection.run_sync(metadata.drop_all, checkfirst=True)
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-014")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_sqlserver_crud_and_catalog_reflection(
    sqlserver_config: KESConfig,
) -> None:
    """测试点：SQL Server 方言覆盖 identity、CRUD、流读取及完整目录反射。"""

    async def scenario() -> None:
        from sqlalchemy import (
            Column,
            ForeignKey,
            Index,
            Integer,
            MetaData,
            Numeric,
            String,
            Table,
            inspect,
            select,
        )
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        engine = create_async_engine(
            sqlserver_config.sqlalchemy_dsn(), pool_size=1, max_overflow=0
        )
        metadata = MetaData()
        table_name = unique_object_name("sa_sqlserver", "sqlserver")
        child_name = f"{table_name}_child"
        index_name = f"ix_{table_name}_label"
        table = Table(
            table_name,
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column(
                "name",
                String(40),
                nullable=False,
                unique=True,
                comment="name comment",
            ),
            Column("amount", Numeric(10, 2)),
            comment="sqlserver table comment",
        )
        child = Table(
            child_name,
            metadata,
            Column("id", Integer, primary_key=True),
            Column(
                "parent_id",
                Integer,
                ForeignKey(
                    f"{table_name}.id",
                    name=f"fk_{table_name}_parent",
                    ondelete="CASCADE",
                ),
            ),
            Column("label", String(40)),
        )
        Index(index_name, child.c.label)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(metadata.drop_all, checkfirst=True)
                await connection.run_sync(metadata.create_all)
                result = await connection.execute(
                    table.insert().values(
                        name="alpha", amount=Decimal("12.50")
                    )
                )
                assert result.inserted_primary_key == (1,)
                await connection.execute(
                    table.insert().values(name="beta", amount=Decimal("3.00"))
                )
                updated = await connection.execute(
                    table.update()
                    .where(table.c.name == "beta")
                    .values(amount=Decimal("4.00"))
                    .returning(table.c.id, table.c.amount)
                )
                assert updated.one() == (2, Decimal("4.00"))
                await connection.execute(
                    table.insert().values(
                        name="temporary", amount=Decimal("1.00")
                    )
                )
                deleted = await connection.execute(
                    table.delete()
                    .where(table.c.name == "temporary")
                    .returning(table.c.id)
                )
                assert deleted.scalar_one() == 3
                await connection.execute(
                    child.insert().values(id=1, parent_id=1, label="child")
                )

            async with engine.connect() as connection:
                rows = (
                    await connection.execute(
                        select(table).order_by(table.c.id).limit(1).offset(1)
                    )
                ).all()
                assert [(row.id, row.name) for row in rows] == [(2, "beta")]

                stream = await connection.stream_scalars(
                    select(table.c.name).order_by(table.c.id)
                )
                assert [value async for value in stream] == ["alpha", "beta"]

                def reflect(sync_connection):
                    inspector = inspect(sync_connection)
                    return (
                        inspector.get_columns(table_name),
                        inspector.get_pk_constraint(table_name),
                        inspector.get_unique_constraints(table_name),
                        inspector.get_foreign_keys(child_name),
                        inspector.get_indexes(child_name),
                        inspector.get_table_comment(table_name),
                    )

                (
                    columns,
                    primary_key,
                    unique,
                    foreign_keys,
                    indexes,
                    table_comment,
                ) = await connection.run_sync(reflect)
                assert [column["name"] for column in columns] == [
                    "id",
                    "name",
                    "amount",
                ]
                assert columns[0]["autoincrement"] is True
                assert columns[1]["comment"] == "name comment"
                assert isinstance(columns[0]["type"], Integer)
                assert isinstance(columns[1]["type"], String)
                assert isinstance(columns[2]["type"], Numeric)
                assert primary_key["constrained_columns"] == ["id"]
                assert [item["column_names"] for item in unique] == [["name"]]
                assert foreign_keys[0]["constrained_columns"] == ["parent_id"]
                assert foreign_keys[0]["referred_table"] == table_name
                assert foreign_keys[0]["referred_columns"] == ["id"]
                assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
                assert [item["name"] for item in indexes] == [index_name]
                assert table_comment == {"text": "sqlserver table comment"}
        finally:
            async with engine.begin() as connection:
                await connection.run_sync(metadata.drop_all, checkfirst=True)
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-015")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_oracle_crud_stream_and_catalog_reflection(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle 方言覆盖 identity、sequence、RETURNING、computed 和反射。"""

    async def scenario() -> None:
        from sqlalchemy import (
            CheckConstraint,
            Column,
            Computed,
            ForeignKey,
            Identity,
            Index,
            Integer,
            MetaData,
            Numeric,
            Sequence,
            String,
            Table,
            inspect,
            select,
        )
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        engine = create_async_engine(
            oracle_config.sqlalchemy_dsn(), pool_size=1, max_overflow=0
        )
        metadata = MetaData()
        object_token = uuid.uuid4().hex[:8]
        table_name = f"apgso_{object_token}"
        child_name = f"{table_name}c"
        sequence_name = f"{table_name}s"
        table = Table(
            table_name,
            metadata,
            Column("id", Integer, Identity(), primary_key=True),
            Column(
                "name",
                String(40),
                nullable=False,
                unique=True,
                comment="name comment",
            ),
            Column(
                "amount",
                Numeric(10, 2),
                CheckConstraint("amount >= 0", name=f"ck_{table_name}_amount"),
            ),
            Column("doubled", Numeric(10, 2), Computed("amount * 2")),
            comment="oracle table comment",
        )
        child = Table(
            child_name,
            metadata,
            Column("id", Integer, primary_key=True),
            Column(
                "parent_id",
                Integer,
                ForeignKey(
                    f"{table_name}.id",
                    name=f"fk_{table_name}_parent",
                    ondelete="CASCADE",
                ),
            ),
            Column("label", String(40)),
        )
        Index(f"ix_{table_name}_label", child.c.label)
        sequence = Sequence(sequence_name)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(metadata.drop_all, checkfirst=True)
                await connection.run_sync(
                    lambda sync: sequence.drop(sync, checkfirst=True)
                )
                await connection.run_sync(sequence.create)
                await connection.run_sync(metadata.create_all)
                result = await connection.execute(
                    table.insert().values(
                        name="alpha", amount=Decimal("12.50")
                    )
                )
                assert result.inserted_primary_key == (1,)
                result = await connection.execute(
                    table.insert()
                    .values(name="beta", amount=Decimal("3.00"))
                    .returning(table.c.id, table.c.name)
                )
                assert result.one() == (2, "beta")
                result = await connection.execute(
                    table.insert().returning(table.c.id, table.c.name),
                    [
                        {"name": "gamma", "amount": Decimal("1.00")},
                        {"name": "delta", "amount": Decimal("2.00")},
                    ],
                )
                assert result.all() == [(3, "gamma"), (4, "delta")]
                await connection.execute(
                    table.delete().where(table.c.id.in_([3, 4]))
                )
                result = await connection.execute(
                    table.update()
                    .where(table.c.id == 1)
                    .values(amount=Decimal("20.00"))
                    .returning(table.c.id, table.c.amount)
                )
                assert result.one() == (1, Decimal("20.00"))
                result = await connection.execute(
                    table.delete().where(table.c.id == 2).returning(table.c.id)
                )
                assert result.scalar_one() == 2
                await connection.execute(
                    child.insert().values(id=1, parent_id=1, label="child")
                )
                assert await connection.scalar(sequence.next_value()) == 1

            async with engine.connect() as connection:
                row = (
                    await connection.execute(
                        select(table.c.id, table.c.name, table.c.doubled)
                    )
                ).one()
                assert row == (1, "alpha", Decimal("40.00"))
                stream = await connection.stream_scalars(
                    select(table.c.id).order_by(table.c.id)
                )
                assert [value async for value in stream] == [1]

                def reflect(sync_connection):
                    inspector = inspect(sync_connection)
                    return (
                        inspector.get_columns(table_name),
                        inspector.get_pk_constraint(table_name),
                        inspector.get_unique_constraints(table_name),
                        inspector.get_check_constraints(table_name),
                        inspector.get_foreign_keys(child_name),
                        inspector.get_indexes(child_name),
                        inspector.get_table_comment(table_name),
                        inspector.get_sequence_names(),
                        inspector.has_sequence(sequence_name),
                    )

                (
                    columns,
                    primary_key,
                    unique,
                    checks,
                    foreign_keys,
                    indexes,
                    table_comment,
                    sequence_names,
                    has_sequence,
                ) = await connection.run_sync(reflect)
                reflected = {column["name"]: column for column in columns}
                assert reflected["id"]["identity"]["always"] is False
                assert reflected["id"]["autoincrement"] is True
                assert reflected["name"]["comment"] == "name comment"
                assert (
                    reflected["doubled"]["computed"]["sqltext"]
                    == "(amount * 2)"
                )
                assert primary_key["constrained_columns"] == ["id"]
                assert [item["column_names"] for item in unique] == [["name"]]
                assert checks[0]["sqltext"] == "(amount >= (0))"
                assert foreign_keys[0]["constrained_columns"] == ["parent_id"]
                assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
                assert [item["column_names"] for item in indexes] == [
                    ["label"]
                ]
                assert table_comment == {"text": "oracle table comment"}
                assert sequence_name in sequence_names
                assert has_sequence is True
        finally:
            async with engine.begin() as connection:
                await connection.run_sync(metadata.drop_all, checkfirst=True)
                await connection.run_sync(
                    lambda sync: sequence.drop(sync, checkfirst=True)
                )
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-016")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_oracle_character_lengths_use_kes_data_length(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle CHAR/NCHAR 反射使用有效长度，不返回 KES 的零值。"""

    async def scenario() -> None:
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        table_name = unique_object_name("sa_oracle_char", oracle_config.mode)
        engine = create_async_engine(oracle_config.sqlalchemy_dsn())
        try:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(
                    f"CREATE TABLE {table_name} ("
                    "fixed_value CHAR(8), "
                    "national_value NCHAR(9), "
                    "varying_value VARCHAR2(20), "
                    "national_varying_value NVARCHAR2(21))"
                )

            async with engine.connect() as connection:
                columns = await connection.run_sync(
                    lambda sync: inspect(sync).get_columns(table_name)
                )
                reflected = {
                    column["name"]: column["type"] for column in columns
                }
                assert reflected["fixed_value"].length == 8
                assert reflected["national_value"].length == 9
                assert reflected["varying_value"].length == 20
                assert reflected["national_varying_value"].length == 21
        finally:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(
                    f"DROP TABLE IF EXISTS {table_name}"
                )
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-017")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_oracle_can_reflect_and_query_another_owner(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle 方言可发现其他用户 Schema，并反射、查询其表。"""

    async def scenario() -> None:
        from sqlalchemy import MetaData, Table, inspect, select
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        owner = f"apgown{uuid.uuid4().hex[:8]}"
        owner_password = "KesSchemaTest123"
        table_name = f"apgco{uuid.uuid4().hex[:8]}"
        admin = await asynckb.connect(**oracle_config.connection_kwargs())
        engine = None

        async def cleanup_owner() -> None:
            try:
                owner_connection = await asynckb.connect(
                    **oracle_config.connection_kwargs(
                        user=owner, password=owner_password
                    )
                )
            except asynckb.PostgresError:
                owner_connection = None
            if owner_connection is not None:
                try:
                    await drop_table(owner_connection, table_name)
                finally:
                    await owner_connection.close()
            try:
                await admin.execute(f"DROP USER {owner}")
            except asynckb.PostgresError:
                pass

        try:
            await cleanup_owner()
            await admin.execute(
                f"CREATE USER {owner} WITH PASSWORD '{owner_password}'"
            )
            owner_connection = await asynckb.connect(
                **oracle_config.connection_kwargs(
                    user=owner, password=owner_password
                )
            )
            try:
                await owner_connection.execute(
                    f"CREATE TABLE {table_name} ("
                    "id INTEGER PRIMARY KEY, name VARCHAR2(20))"
                )
                await owner_connection.execute(
                    f"INSERT INTO {table_name} VALUES (1, $1)", "cross-owner"
                )
            finally:
                await owner_connection.close()

            engine = create_async_engine(oracle_config.sqlalchemy_dsn())
            async with engine.connect() as connection:

                def reflect(sync_connection):
                    inspector = inspect(sync_connection)
                    reflected = Table(
                        table_name,
                        MetaData(),
                        schema=owner,
                        autoload_with=sync_connection,
                    )
                    return (
                        owner in inspector.get_schema_names(),
                        table_name in inspector.get_table_names(schema=owner),
                        inspector.has_table(table_name, schema=owner),
                        reflected,
                    )

                has_schema, has_name, has_table, reflected = (
                    await connection.run_sync(reflect)
                )
                assert has_schema is True
                assert has_name is True
                assert has_table is True
                assert [column.name for column in reflected.columns] == [
                    "id",
                    "name",
                ]
                assert (await connection.execute(select(reflected))).all() == [
                    (1, "cross-owner")
                ]
        finally:
            if engine is not None:
                await engine.dispose()
            await cleanup_owner()
            await admin.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-018")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_oracle_quoted_user_reflects_its_default_owner(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle mixed-case quoted 用户按精确 owner 反射自身对象。"""

    async def scenario() -> None:
        from sqlalchemy import MetaData, Table, inspect, select
        from sqlalchemy.engine import URL
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.sql import quoted_name

        register_kes_dialects()
        token = uuid.uuid4().hex[:8]
        owner = f"ApgOwner{token}"
        owner_password = "KesSchemaTest123"
        table_name = f"ApgTable{token}"
        admin = await asynckb.connect(**oracle_config.connection_kwargs())
        engine = None

        async def cleanup_owner() -> None:
            try:
                owner_connection = await asynckb.connect(
                    **oracle_config.connection_kwargs(
                        user=owner,
                        password=owner_password,
                    )
                )
            except asynckb.PostgresError:
                owner_connection = None
            if owner_connection is not None:
                try:
                    await owner_connection.execute(
                        f'DROP TABLE "{table_name}"'
                    )
                except asynckb.UndefinedTableError:
                    pass
                finally:
                    await owner_connection.close()
            try:
                await admin.execute(f'DROP USER "{owner}"')
            except asynckb.PostgresError:
                pass

        try:
            await cleanup_owner()
            await admin.execute(
                f"CREATE USER \"{owner}\" WITH PASSWORD '{owner_password}'"
            )
            owner_connection = await asynckb.connect(
                **oracle_config.connection_kwargs(
                    user=owner,
                    password=owner_password,
                )
            )
            try:
                await owner_connection.execute(
                    f'CREATE TABLE "{table_name}" ("Id" INTEGER)'
                )
                await owner_connection.execute(
                    f'INSERT INTO "{table_name}" VALUES (1)'
                )
            finally:
                await owner_connection.close()

            url = URL.create(
                "kingbase+asynckb",
                username=owner,
                password=owner_password,
                host=oracle_config.host,
                port=oracle_config.port,
                database=oracle_config.database,
            )
            engine = create_async_engine(url)
            async with engine.connect() as connection:

                def reflect(sync_connection):
                    inspector = inspect(sync_connection)
                    reflected = Table(
                        quoted_name(table_name, True),
                        MetaData(),
                        autoload_with=sync_connection,
                    )
                    return (
                        inspector.get_table_names(),
                        inspector.has_table(quoted_name(table_name, True)),
                        inspector.get_columns(quoted_name(table_name, True)),
                        reflected,
                    )

                names, has_table, columns, reflected = (
                    await connection.run_sync(reflect)
                )
                assert table_name in names
                assert has_table is True
                assert [column["name"] for column in columns] == ["Id"]
                assert (
                    await connection.execute(select(reflected.c.Id))
                ).scalar_one() == 1
        finally:
            if engine is not None:
                await engine.dispose()
            await cleanup_owner()
            await admin.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-020")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_executemany_failure_rolls_back_and_recovers(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式 SQLAlchemy executemany 失败可回滚并继续查询。"""
    async def scenario() -> None:
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        table_name = unique_object_name("sa_executemany", kes_config.mode)
        engine = create_async_engine(
            _sqlalchemy_url(kes_config, "sslmode=disable")
        )
        try:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(
                    f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY)"
                )

            async with engine.connect() as connection:
                with pytest.raises(DBAPIError):
                    await connection.execute(
                        text(f"INSERT INTO {table_name} VALUES (:id)"),
                        [{"id": 1}, {"id": 1}],
                    )
                await connection.rollback()
                assert (
                    await connection.exec_driver_sql(
                        f"SELECT count(*) FROM {table_name}"
                    )
                ).scalar_one() == 0
                assert (
                    await connection.exec_driver_sql(kes_config.select_one)
                ).scalar_one() == 1
        finally:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(
                    f"DROP TABLE IF EXISTS {table_name}"
                )
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-021")
@pytest.mark.integration
@pytest.mark.framework
def test_sqlalchemy_catalog_boundaries_in_all_kes_modes(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式 schema、物化视图和不存在对象反射语义明确。"""
    async def scenario() -> None:
        from sqlalchemy import exc, inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        missing_name = unique_object_name("sa_missing", kes_config.mode)
        engine = create_async_engine(
            _sqlalchemy_url(kes_config, "sslmode=disable")
        )
        try:
            async with engine.connect() as connection:

                def reflect(sync_connection):
                    inspector = inspect(sync_connection)
                    schemas = inspector.get_schema_names()
                    materialized_views = (
                        inspector.get_materialized_view_names()
                    )
                    with pytest.raises(exc.NoSuchTableError):
                        inspector.get_view_definition(missing_name)
                    with pytest.raises(exc.NoSuchTableError):
                        inspector.get_table_comment(missing_name)
                    with pytest.raises(exc.NoSuchTableError):
                        inspector.get_table_options(missing_name)
                    with pytest.raises(exc.NoSuchTableError):
                        inspector.get_columns(missing_name)
                    assert inspector.get_check_constraints(
                        missing_name,
                        include_all=True,
                    ) == []
                    return schemas, materialized_views

                schemas, materialized_views = await connection.run_sync(
                    reflect
                )
                assert schemas
                expected_schema = (
                    kes_config.user
                    if kes_config.mode == "oracle"
                    else connection.dialect.default_schema_name
                )
                assert expected_schema.lower() in {
                    schema.lower() for schema in schemas
                }
                assert materialized_views == []
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-SA-024")
@pytest.mark.unit
def test_sqlalchemy_connection_url_options_are_normalized(
) -> None:
    """测试点：SQLAlchemy URL 的 SSL、缓存、超时和多主机参数正确传给 asynckb。"""
    pytest.importorskip("sqlalchemy")
    from asynckb import sa_dialect
    from sqlalchemy import pool
    from sqlalchemy.engine import make_url

    dialect = sa_dialect.KESDialect_asynckb()
    url = make_url(
        "kingbase+asynckb://user:password@/test?"
        "host=127.0.0.1:1&host=127.0.0.1:54321&sslmode=disable&"
        "prepared_statement_cache_size=0&statement_cache_size=2&"
        "max_cached_statement_lifetime=1.5&"
        "max_cacheable_statement_size=2048&command_timeout=2.5&"
        "timeout=3&direct_tls=false"
    )

    positional, options = dialect.create_connect_args(url)

    assert positional == []
    assert options["host"] == ["127.0.0.1", "127.0.0.1"]
    assert options["port"] == [1, 54321]
    assert options["ssl"] == "disable"
    assert "sslmode" not in options
    assert options["prepared_statement_cache_size"] == 0
    assert options["statement_cache_size"] == 2
    assert options["max_cached_statement_lifetime"] == 1.5
    assert options["max_cacheable_statement_size"] == 2048
    assert options["command_timeout"] == 2.5
    assert options["timeout"] == 3.0
    assert options["direct_tls"] is False
    assert "kes_mode" not in options
    assert "postgresql_readonly" in dialect.connection_characteristics
    assert "postgresql_deferrable" in dialect.connection_characteristics
    fallback_url = make_url(
        "kingbase+asynckb://user:password@localhost/test?"
        "async_fallback=true"
    )
    assert dialect.get_pool_class(
        fallback_url
    ) is pool.FallbackAsyncAdaptedQueuePool


@pytest.mark.case_id("KB-SA-029")
@pytest.mark.unit
def test_sqlalchemy_connection_url_rejects_incomplete_or_conflicting_options(
) -> None:
    """测试点：SQLAlchemy URL 拒绝缺 host/port 和 SSL 参数冲突。"""
    pytest.importorskip("sqlalchemy")
    from asynckb.sa_dialect import KESDialect_asynckb
    from sqlalchemy import exc
    from sqlalchemy.engine import make_url

    dialect = KESDialect_asynckb()
    _, single_host = dialect.create_connect_args(make_url(
        "kingbase+asynckb://user:password@/test?"
        "host=127.0.0.1:54321"
    ))
    assert single_host["host"] == "127.0.0.1"
    assert single_host["port"] == 54321
    _, host_without_port = dialect.create_connect_args(make_url(
        "kingbase+asynckb://user:password@/test?host=127.0.0.1"
    ))
    assert host_without_port["host"] == "127.0.0.1"
    assert "port" not in host_without_port

    invalid_urls = (
        (
            "host=:54321&host=127.0.0.1:54322",
            "All hosts are required",
        ),
        (
            "host=127.0.0.1&host=127.0.0.1:54322",
            "All ports are required",
        ),
        (
            "ssl=disable&sslmode=disable",
            "Use either 'sslmode' or 'ssl'",
        ),
    )
    for query, message in invalid_urls:
        url = make_url(
            "kingbase+asynckb://user:password@/test?" + query
        )
        with pytest.raises(exc.ArgumentError, match=message):
            dialect.create_connect_args(url)


@pytest.mark.case_id("KB-SA-030")
@pytest.mark.unit
def test_sqlalchemy_adapter_named_deallocate_updates_both_caches() -> None:
    """测试点：SQLAlchemy 执行 named DEALLOCATE 同步关闭两层语句缓存。"""
    pytest.importorskip("sqlalchemy")
    from asynckb.sa_dialect import _KESAsyncAdaptConnection

    class Statement:
        closed = False

        def mark_closed(self) -> None:
            self.closed = True

    class DriverConnection:
        def __init__(self, statement: Statement) -> None:
            self._named_statements = {"apg_named": statement}

    class Cache(dict):
        cleared = False

        def clear(self) -> None:
            self.cleared = True
            super().clear()

    statement = Statement()
    cache = Cache({"cached": object()})
    adapter = type("Adapter", (), {})()
    adapter._connection = DriverConnection(statement)
    adapter._prepared_statement_cache = cache

    _KESAsyncAdaptConnection._handle_deallocate(
        adapter, "DEALLOCATE apg_named"
    )

    assert statement.closed is True
    assert adapter._connection._named_statements == {}
    assert cache == {}
    assert cache.cleared is True

    adapter._prepared_statement_cache = None
    _KESAsyncAdaptConnection._handle_deallocate(
        adapter, "DEALLOCATE missing_statement"
    )
