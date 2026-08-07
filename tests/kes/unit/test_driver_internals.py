"""Unit tests for KES mode parsing, SQL generation, and codecs."""

from __future__ import annotations

import asyncio
import datetime
from decimal import Decimal
import uuid

import asyncpg
import pytest
from asyncpg import connect_utils
from asyncpg import kes


pytestmark = pytest.mark.unit


def test_mode_normalization_accepts_supported_names_and_rejects_unknown_names(
) -> None:
    """测试点：模式名称大小写归一化，且不允许 PostgreSQL 等非 KES 模式。"""
    assert kes.normalize_mode(None) is None
    assert kes.normalize_mode("MySQL") == "mysql"
    assert kes.normalize_mode("ORACLE") == "oracle"
    assert kes.normalize_mode("SQLSERVER") == "sqlserver"
    with pytest.raises(asyncpg.ClientConfigurationError):
        kes.normalize_mode("postgres")


def test_dsn_parser_extracts_encoded_kes_mode_and_preserves_other_settings(
) -> None:
    """测试点：DSN 解码 kes_mode、保留服务端参数并允许显式模式覆盖。"""
    dsn = (
        "postgresql://system:test-password@127.0.0.1:54321/test?"
        "%6b%65%73%5f%6d%6f%64%65=mysql&application_name=kes_test&"
        "sslmode=disable"
    )
    arguments = {
        "dsn": dsn,
        "host": None,
        "port": None,
        "user": None,
        "password": None,
        "passfile": None,
        "database": None,
        "command_timeout": None,
        "statement_cache_size": 100,
        "max_cached_statement_lifetime": 300,
        "max_cacheable_statement_size": 15360,
        "ssl": None,
        "direct_tls": None,
        "server_settings": None,
        "target_session_attrs": None,
        "krbsrvname": None,
        "gsslib": None,
        "service": None,
        "servicefile": None,
    }

    _, parameters, config = connect_utils._parse_connect_arguments(
        **arguments,
        kes_mode=None,
    )
    assert config.kes_mode == "mysql"
    assert parameters.server_settings == {"application_name": "kes_test"}

    _, parameters, config = connect_utils._parse_connect_arguments(
        **arguments,
        kes_mode="oracle",
    )
    assert config.kes_mode == "oracle"
    assert "kes_mode" not in parameters.server_settings


def test_deallocate_parser_recognizes_all_and_named_statements() -> None:
    """测试点：识别 DEALLOCATE ALL、带名称 DEALLOCATE 和普通 SQL。"""
    assert kes.deallocated_statement("DEALLOCATE ALL") is True
    assert kes.deallocated_statement('deallocate prepare "my stmt";') == (
        "my stmt"
    )
    assert kes.deallocated_statement("SELECT 1") is None


def test_mysql_transaction_sql_contains_isolation_read_only_and_savepoint(
) -> None:
    """测试点：MySQL 模式事务 SQL 包含隔离级别、只读和回滚保存点。"""
    assert kes.start_transaction("mysql", "read_committed", True, False) == (
        "SET TRANSACTION ISOLATION LEVEL READ COMMITTED;\n"
        "START TRANSACTION READ ONLY;"
    )
    assert kes.rollback_to_savepoint("mysql", "sp") == (
        "ROLLBACK TO SAVEPOINT sp;"
    )


def test_oracle_transaction_sql_rejects_unsupported_isolation_and_deferrable(
) -> None:
    """测试点：Oracle 模式生成 SERIALIZABLE 事务，并拒绝不支持的选项。"""
    assert kes.start_transaction("oracle", "serializable", True, False) == (
        "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY;\n"
        "START TRANSACTION;"
    )
    assert kes.release_savepoint("oracle", "sp") is None
    with pytest.raises(asyncpg.UnsupportedClientFeatureError):
        kes.start_transaction("oracle", "repeatable_read", False, False)
    with pytest.raises(asyncpg.UnsupportedClientFeatureError):
        kes.start_transaction("oracle", "read_committed", False, True)


def test_sqlserver_transaction_sql_uses_tsql_begin_and_savepoint_syntax(
) -> None:
    """测试点：SQL Server 模式使用 BEGIN/SAVE/ROLLBACK TRANSACTION 语法。"""
    assert kes.start_transaction(
        "sqlserver", "repeatable_read", True, False
    ) == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;\n"
        "BEGIN TRANSACTION READ ONLY;"
    )
    assert kes.savepoint("sqlserver", "sp") == "SAVE TRANSACTION sp;"
    assert kes.release_savepoint("sqlserver", "sp") is None
    assert kes.rollback_to_savepoint("sqlserver", "sp") == (
        "ROLLBACK TRANSACTION sp;"
    )
    with pytest.raises(asyncpg.UnsupportedClientFeatureError):
        kes.start_transaction("sqlserver", None, False, True)


def test_mysql_fractional_datetime_codecs_preserve_precision_and_duration(
) -> None:
    """测试点：MySQL TIME/DATETIME codec 保留小数秒并支持超过 24 小时。"""
    assert kes._decode_time("03:04:05.1234") == datetime.time(
        3, 4, 5, 123400
    )
    assert kes._decode_datetime("2025-01-02 03:04:05.1") == datetime.datetime(
        2025, 1, 2, 3, 4, 5, 100000
    )
    assert kes._decode_time("25:01:02.123") == datetime.timedelta(
        hours=25, minutes=1, seconds=2, milliseconds=123
    )
    assert kes._decode_time("-25:01:02.123") == -datetime.timedelta(
        hours=25, minutes=1, seconds=2, milliseconds=123
    )
    assert kes._encode_time(datetime.timedelta(hours=25, microseconds=1)) == (
        "25:00:00.000001"
    )


def test_kes_scalar_encoders_reject_silent_python_coercions() -> None:
    """测试点：KES 标量 codec 拒绝文本、二进制和时区值的静默转换。"""
    assert kes._encode_integer(True) == "1"
    assert kes._encode_integer(7.9) == "7"
    assert kes._encode_dsinterval(
        datetime.timedelta(days=1, seconds=2)
    ) == "1 00:00:02.000000"
    assert kes._encode_dsinterval(
        datetime.timedelta(microseconds=-1)
    ) == "-0 00:00:00.000001"
    assert kes._encode_dsinterval(
        datetime.timedelta(days=-2, seconds=3, microseconds=4)
    ) == "-1 23:59:56.999996"

    with pytest.raises(TypeError, match="expected str, got int"):
        kes._encode_text(1)
    with pytest.raises(
        TypeError,
        match="cannot be interpreted as an integer",
    ):
        kes._encode_integer("7")
    with pytest.raises(TypeError, match="a bytes-like object is required"):
        kes._encode_binary(3)
    with pytest.raises(TypeError, match="offset-naive and offset-aware"):
        kes._encode_datetime(
            datetime.datetime(
                2025, 1, 2, tzinfo=datetime.timezone.utc
            )
        )


def test_mysql_temporal_tuple_encoders_follow_integer_conversion_rules(
) -> None:
    """测试点：MySQL 日期时间 tuple codec 按 asyncpg 规则转换整数。"""
    def identity(value: object) -> object:
        return value

    cases = (
        ("date", (1.9,), "2000-01-02"),
        ("time", (1.9,), "00:00:00.000001"),
        ("timestamp", (1.9,), "2000-01-01 00:00:00.000001"),
    )
    for typename, value, expected in cases:
        encoder, _, data_format = kes.adapt_custom_codec(
            "mysql",
            typename,
            "pg_catalog",
            identity,
            identity,
            "tuple",
        )
        assert data_format == "text"
        assert encoder(value) == expected
        with pytest.raises(TypeError, match="an integer is required"):
            encoder(("1",))


def test_kes_temporal_codecs_cover_infinity_range_and_shape_boundaries(
) -> None:
    """测试点：日期时间 codec 处理无穷值、越界值和 tuple 边界。"""
    assert kes._encode_date(
        datetime.datetime(2025, 1, 2, 3, 4, 5)
    ) == "2025-01-02"
    assert kes._decode_date("infinity") == datetime.date.max
    assert kes._decode_date("-infinity") == datetime.date.min
    assert kes._decode_datetime("infinity") == datetime.datetime.max
    assert kes._decode_datetime("-infinity") == datetime.datetime.min
    assert kes._decode_time("03:04:05+08:00") == datetime.time(
        3, 4, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=8))
    )
    assert kes._encode_time(datetime.timedelta(hours=1)) == "1:00:00"

    with pytest.raises(TypeError, match="expected a datetime.date"):
        kes._encode_date("2025-01-02")
    with pytest.raises(TypeError, match="expected a datetime.time"):
        kes._encode_time("03:04:05")
    with pytest.raises(ValueError, match="invalid MySQL TIME"):
        kes._decode_time("01:60:00")

    def identity(value: object) -> object:
        return value

    date_encoder, date_decoder, _ = kes.adapt_custom_codec(
        "mysql", "date", "pg_catalog", identity, identity, "tuple"
    )
    assert date_encoder((2**31 - 1,)) == "infinity"
    assert date_encoder((-(2**31),)) == "-infinity"
    assert date_decoder("infinity") == (2**31 - 1,)
    assert date_decoder("-infinity") == (-(2**31),)
    with pytest.raises(TypeError, match="one-element tuple"):
        date_encoder(())

    class InvalidInteger:
        def __int__(self) -> int:
            raise ValueError("not an integer")

    with pytest.raises(TypeError, match="an integer is required"):
        date_encoder((InvalidInteger(),))

    time_encoder, time_decoder, _ = kes.adapt_custom_codec(
        "mysql", "time", "pg_catalog", identity, identity, "tuple"
    )
    with pytest.raises(ValueError, match="range"):
        time_encoder((86400_000000,))
    with pytest.raises(ValueError, match="outside the PostgreSQL time range"):
        time_decoder("25:00:00")

    timestamp_encoder, timestamp_decoder, _ = kes.adapt_custom_codec(
        "mysql", "timestamp", "pg_catalog", identity, identity, "tuple"
    )
    assert timestamp_encoder((2**63 - 1,)) == "infinity"
    assert timestamp_encoder((-(2**63),)) == "-infinity"
    assert timestamp_decoder("infinity") == (2**63 - 1,)
    assert timestamp_decoder("-infinity") == (-(2**63),)


def test_kes_scalar_codecs_cover_false_hex_numeric_and_uuid_boundaries(
) -> None:
    """测试点：标量 codec 覆盖布尔假值、BIT、数值、UUID 和非法输入。"""
    value = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert kes._encode_boolean(False) == "0"
    assert kes._decode_boolean("FALSE") is False
    assert kes._encode_decimal(Decimal("12.50")) == "12.50"
    assert kes._encode_uuid(value) == str(value)
    assert kes._encode_dsinterval("+01 02:03:04") == "+01 02:03:04"
    assert kes._decode_mysql_bit("0x0102") == b"\x01\x02"
    assert kes._decode_mysql_bit("AB") == b"AB"
    assert kes._encode_mysql_bit(258) == "0x0102"
    assert kes._encode_mysql_bit(b"\x00\xff") == "0x00ff"
    assert kes._encode_mysql_bit("0x01") == "0x01"

    with pytest.raises(TypeError, match="expected bool"):
        kes._encode_boolean(1)
    with pytest.raises(ValueError, match="invalid boolean"):
        kes._decode_boolean("yes")
    with pytest.raises(TypeError, match="expected a number"):
        kes._encode_decimal("12.50")
    with pytest.raises(TypeError, match="expected a number"):
        kes._encode_decimal(object())
    with pytest.raises(TypeError, match="expected uuid.UUID"):
        kes._encode_uuid(str(value))
    with pytest.raises(ValueError, match="cannot be negative"):
        kes._encode_mysql_bit(-1)


def test_kes_codec_aliases_cover_discovery_fallback_and_passthrough(
) -> None:
    """测试点：Codec 别名覆盖 set 发现、默认候选和不适配透传。"""
    aliases = kes.discover_codec_aliases(
        {("sys", "tinyint"), ("sys", "mysql_json")}, "mysql"
    )
    assert aliases[("pg_catalog", "tinyint")] == ("sys", "tinyint")
    assert aliases[("pg_catalog", "json")] == ("sys", "mysql_json")
    assert kes.resolve_codec_type(
        "mysql", "tinyint", "pg_catalog"
    ) == ("sys", "tinyint")
    assert kes.resolve_codec_type(
        "mysql", "unknown", "pg_catalog"
    ) == ("pg_catalog", "unknown")
    assert kes.discover_codec_mirrors([
        {
            "schema_name": "sys",
            "type_name": "json",
            "type_kind": "d",
            "base_schema_name": None,
            "base_type_name": None,
        },
    ], "mysql") == {}

    encoder = str
    decoder = int
    assert kes.adapt_custom_codec(
        "oracle",
        "timestamp",
        "pg_catalog",
        encoder,
        decoder,
        "tuple",
    ) == (encoder, decoder, "tuple")

    with pytest.raises(asyncpg.InternalClientError, match="unexpected KES"):
        kes.start_transaction("invalid", None, False, False)


def test_codec_registration_uses_discovered_oids_and_rejects_missing_markers(
) -> None:
    """测试点：Codec 注册使用服务端发现的 OID，模式标记缺失时不注册。"""
    calls: list[tuple[object, ...]] = []

    class Settings:
        def add_python_codec(self, *args: object) -> None:
            calls.append(args)

    aliases, mirrors = kes.register_codecs(
        Settings(),
        [
            {
                "oid": 12345,
                "schema_name": "sys",
                "type_name": "tinyint",
                "type_kind": b"b",
                "base_schema_name": None,
                "base_type_name": None,
            },
            {
                "oid": 4802,
                "schema_name": "sys",
                "type_name": "json",
                "type_kind": b"d",
                "base_schema_name": "pg_catalog",
                "base_type_name": "jsonb",
            },
            {
                "oid": 3384,
                "schema_name": "sys",
                "type_name": "varbinary",
                "type_kind": b"b",
                "base_schema_name": None,
                "base_type_name": None,
            },
        ],
        "mysql",
    )
    assert calls[0][0:3] == (12345, "tinyint", "sys")
    assert calls[0][-1] == "text"
    assert kes.resolve_codec_type(
        "mysql", "tinyint", "pg_catalog", aliases
    ) == ("sys", "tinyint")
    assert kes.resolve_codec_type(
        "mysql", "json", "pg_catalog", aliases
    ) == ("sys", "json")
    assert mirrors[("sys", "json")] == ("pg_catalog", "jsonb")
    assert kes.resolve_codec_type(
        "mysql", "varbinary", "pg_catalog", aliases
    ) == ("sys", "varbinary")

    legacy_aliases = kes.discover_codec_aliases(
        [
            {
                "schema_name": "pg_catalog",
                "type_name": "tinyint",
                "type_kind": b"b",
                "base_schema_name": None,
                "base_type_name": None,
            },
            {
                "schema_name": "sys",
                "type_name": "mysql_json",
                "type_kind": b"b",
                "base_schema_name": None,
                "base_type_name": None,
            },
        ],
        "mysql",
    )
    assert kes.resolve_codec_type(
        "mysql", "tinyint", "pg_catalog", legacy_aliases
    ) == ("pg_catalog", "tinyint")
    assert kes.resolve_codec_type(
        "mysql", "json", "pg_catalog", legacy_aliases
    ) == ("sys", "mysql_json")
    assert kes.discover_codec_mirrors([], "mysql") == {}
    assert kes.codec_wire_format("mysql", "timestamp", "sys") == "text"
    assert kes.codec_wire_format(
        "mysql", "varbinary", "pg_catalog"
    ) == "binary"
    assert kes.codec_wire_format(None, "timestamp", "sys") is None

    class FailingSettings:
        def add_python_codec(self, *args: object) -> None:
            raise AssertionError("codec registration must not run")

    with pytest.raises(asyncpg.ClientConfigurationError):
        kes.register_codecs(FailingSettings(), [], "oracle")


def test_sqlalchemy_dialects_compile_mode_specific_ddl_and_pagination(
) -> None:
    """测试点：SQLAlchemy 方言分别生成三种 KES 模式兼容 SQL。"""
    pytest.importorskip("sqlalchemy")
    from asyncpg.sa_dialect import KESMySQLDialect_asyncpg
    from asyncpg.sa_dialect import KESOracleDialect_asyncpg
    from asyncpg.sa_dialect import KESSQLServerDialect_asyncpg
    from sqlalchemy import Column
    from sqlalchemy import Computed
    from sqlalchemy import Identity
    from sqlalchemy import Integer
    from sqlalchemy import MetaData
    from sqlalchemy import select
    from sqlalchemy import String
    from sqlalchemy import Table
    from sqlalchemy.schema import CreateTable

    mysql_table = Table(
        "kes_mysql_compile",
        MetaData(),
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("name", String(30)),
        Column("doubled", Integer, Computed("id * 2", persisted=True)),
    )
    mysql_ddl = str(
        CreateTable(mysql_table).compile(dialect=KESMySQLDialect_asyncpg())
    )
    mysql_select = str(
        select(mysql_table)
        .limit(5)
        .offset(2)
        .compile(dialect=KESMySQLDialect_asyncpg())
    )
    assert "AUTO_INCREMENT" in mysql_ddl
    assert "VARCHAR(30)" in mysql_ddl
    assert "LIMIT" in mysql_select.upper()
    assert "FETCH FIRST" not in mysql_select.upper()

    oracle_table = Table(
        "kes_oracle_compile",
        MetaData(),
        Column("id", Integer, Identity(), primary_key=True),
        Column("name", String(30)),
    )
    oracle_ddl = str(
        CreateTable(oracle_table).compile(dialect=KESOracleDialect_asyncpg())
    )
    oracle_select = str(
        select(oracle_table)
        .limit(5)
        .offset(2)
        .compile(dialect=KESOracleDialect_asyncpg())
    )
    assert "GENERATED BY DEFAULT AS IDENTITY" in oracle_ddl
    assert "VARCHAR2(30 CHAR)" in oracle_ddl
    assert "FETCH FIRST" in oracle_select.upper()
    assert "AUTO_INCREMENT" not in oracle_ddl

    sqlserver_table = Table(
        "kes_sqlserver_compile",
        MetaData(),
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("name", String(30)),
    )
    sqlserver_ddl = str(
        CreateTable(sqlserver_table).compile(
            dialect=KESSQLServerDialect_asyncpg()
        )
    )
    sqlserver_select = str(
        select(sqlserver_table)
        .order_by(sqlserver_table.c.id)
        .limit(5)
        .offset(2)
        .compile(dialect=KESSQLServerDialect_asyncpg())
    )
    assert "IDENTITY" in sqlserver_ddl.upper()
    assert "VARCHAR(30)" in sqlserver_ddl.upper()
    assert "ROW_NUMBER" in sqlserver_select.upper()


@pytest.mark.parametrize(
    ("dialect_class", "driver_name", "mode"),
    (
        ("KESMySQLDialect_asyncpg", "kingbase_mysql", "mysql"),
        ("KESOracleDialect_asyncpg", "kingbase_oracle", "oracle"),
        (
            "KESSQLServerDialect_asyncpg",
            "kingbase_sqlserver",
            "sqlserver",
        ),
    ),
)
def test_sqlalchemy_connection_url_options_are_normalized(
    dialect_class: str,
    driver_name: str,
    mode: str,
) -> None:
    """测试点：SQLAlchemy URL 的 SSL、缓存、超时和多主机参数正确传给 asyncpg。"""
    pytest.importorskip("sqlalchemy")
    from asyncpg import sa_dialect
    from sqlalchemy import pool
    from sqlalchemy.engine import make_url

    dialect = getattr(sa_dialect, dialect_class)()
    url = make_url(
        f"{driver_name}+asyncpg://user:password@/test?"
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
    assert options["kes_mode"] == mode
    assert "postgresql_readonly" in dialect.connection_characteristics
    assert "postgresql_deferrable" in dialect.connection_characteristics
    fallback_url = make_url(
        f"{driver_name}+asyncpg://user:password@localhost/test?"
        "async_fallback=true"
    )
    assert dialect.get_pool_class(
        fallback_url
    ) is pool.FallbackAsyncAdaptedQueuePool


def test_sqlalchemy_connection_url_rejects_incomplete_or_conflicting_options(
) -> None:
    """测试点：SQLAlchemy URL 拒绝缺 host/port 和 SSL 参数冲突。"""
    pytest.importorskip("sqlalchemy")
    from asyncpg.sa_dialect import KESMySQLDialect_asyncpg
    from sqlalchemy import exc
    from sqlalchemy.engine import make_url

    dialect = KESMySQLDialect_asyncpg()
    _, single_host = dialect.create_connect_args(make_url(
        "kingbase_mysql+asyncpg://user:password@/test?"
        "host=127.0.0.1:54321"
    ))
    assert single_host["host"] == "127.0.0.1"
    assert single_host["port"] == 54321
    _, host_without_port = dialect.create_connect_args(make_url(
        "kingbase_mysql+asyncpg://user:password@/test?host=127.0.0.1"
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
            "kingbase_mysql+asyncpg://user:password@/test?" + query
        )
        with pytest.raises(exc.ArgumentError, match=message):
            dialect.create_connect_args(url)


def test_sqlalchemy_adapter_named_deallocate_updates_both_caches() -> None:
    """测试点：SQLAlchemy 执行 named DEALLOCATE 同步关闭两层语句缓存。"""
    pytest.importorskip("sqlalchemy")
    from asyncpg.sa_dialect import _KESAsyncAdaptConnection

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


def test_stale_named_statement_cleanup_does_not_close_replacement() -> None:
    """测试点：旧 named statement 清理不会误关闭同名新语句。"""
    class Statement:
        def __init__(self, name: str) -> None:
            self.name = name

    class Protocol:
        def __init__(self) -> None:
            self.closed: list[Statement] = []

        async def close_statement(
            self, statement: Statement, timeout: object
        ) -> None:
            self.closed.append(statement)

    async def scenario() -> None:
        old_statement = Statement("apg_replaced")
        new_statement = Statement("apg_replaced")
        protocol = Protocol()
        connection = type("ConnectionState", (), {})()
        connection._stmts_to_close = {old_statement}
        connection._kes_mode = "mysql"
        connection._named_statements = {
            "apg_replaced": new_statement,
        }
        connection._protocol = protocol

        await asyncpg.Connection._cleanup_stmts(connection)

        assert protocol.closed == []
        assert connection._stmts_to_close == set()
        assert connection._named_statements == {
            "apg_replaced": new_statement,
        }

    asyncio.run(scenario())


def test_sqlalchemy_dialect_helpers_preserve_connection_state_and_defaults(
) -> None:
    """测试点：方言连接状态、版本和 MySQL 默认值辅助逻辑正确。"""
    pytest.importorskip("sqlalchemy")
    from asyncpg import sa_dialect

    dialect = sa_dialect.KESMySQLDialect_asyncpg()
    dialect.dbapi = dialect.import_dbapi()
    state = type(
        "ConnectionState",
        (),
        {"readonly": True, "deferrable": False},
    )()
    assert dialect.get_readonly(state) is True
    assert dialect.get_deferrable(state) is False
    assert sa_dialect._parse_kes_version("not a KES version") == (9, 0, 0)
    assert dialect._kes_mysql_default("nextval('seq'::regclass)") == (
        "nextval('seq'::regclass)"
    )
    assert dialect._kes_mysql_default("'value'::text") == "'value'"
    assert dialect._kes_catalog_char("\x00") == ""
    assert dialect._kes_oracle_expression(
        "value + 1", check=True
    ) == "value + 1"

    closed_driver = type("Driver", (), {"is_closed": lambda self: True})()
    adapted = type("Adapted", (), {"_connection": closed_driver})()
    assert dialect.is_disconnect(RuntimeError(), adapted, None) is True
    assert dialect.is_disconnect(
        dialect.dbapi.InterfaceError("connection is closed"), None, None
    ) is True

    class Cursor:
        closed = False

        def execute(self, query: str) -> None:
            assert query == "SHOW transaction isolation level"

        def fetchone(self) -> tuple[str]:
            return ("read committed",)

        def close(self) -> None:
            self.closed = True

    cursor = Cursor()
    dbapi_connection = type(
        "DBAPIConnection", (), {"cursor": lambda self: cursor}
    )()
    assert dialect.get_isolation_level(dbapi_connection) == "READ COMMITTED"
    assert cursor.closed is True


def test_sqlalchemy_reflected_type_helpers_cover_three_mode_metadata(
) -> None:
    """测试点：三模式反射类型转换保留长度、精度和无符号信息。"""
    pytest.importorskip("sqlalchemy")
    from asyncpg import sa_dialect
    from sqlalchemy import types as sqltypes

    mysql = sa_dialect.KESMySQLDialect_asyncpg()
    mysql_unsigned = mysql._kes_column_type((
        "value", "user-defined", "NO", None, None, None, None, None,
        "tinyint unsigned",
    ))
    assert mysql_unsigned.unsigned is True
    mysql_timestamp = mysql._kes_column_type((
        "created_at", "timestamp", "YES", None, None, None, None, 6,
        "timestamp(6)",
    ))
    assert mysql_timestamp.fsp == 6
    mysql_unbounded = mysql._kes_column_type((
        "label", "varchar", "YES", None, None, None, None, None,
        "varchar",
    ))
    assert mysql_unbounded.length is None
    assert isinstance(mysql._kes_column_type((
        "value", "integer", "YES", None, 10, None, None, None, "integer",
    )), sqltypes.Integer)

    sqlserver = sa_dialect.KESSQLServerDialect_asyncpg()
    sqlserver_datetime = sqlserver._kes_sqlserver_type((
        "created_at", "datetime2", "YES", None, None, None, None, 6,
        None, None, None, None, "datetime2(6)",
    ))
    assert sqlserver_datetime.precision == 6
    sqlserver_max = sqlserver._kes_sqlserver_type((
        "payload", "varcharbyte", "YES", None, None, None, None, None,
        None, None, None, None, "varchar(max)",
    ))
    assert sqlserver_max.length == "max"
    sqlserver_numeric = sqlserver._kes_sqlserver_type((
        "amount", "numeric", "YES", None, None, None, None, None,
        None, None, None, None, "numeric",
    ))
    assert sqlserver_numeric.precision is None
    assert sqlserver_numeric.scale is None
    sqlserver_default_datetime = sqlserver._kes_sqlserver_type((
        "created_at", "datetime2", "YES", None, None, None, None, None,
        None, None, None, None, None,
    ))
    assert sqlserver_default_datetime.precision is None
    assert isinstance(sqlserver._kes_column_type((
        "value", "integer", "YES", None, None, None, None, None,
    )), sqltypes.Integer)

    class RejectingType(sqltypes.TypeEngine):
        def __init__(self, **kwargs: object) -> None:
            if kwargs:
                raise TypeError("metadata arguments are unsupported")

    sqlserver.ischema_names = dict(sqlserver.ischema_names)
    sqlserver.ischema_names["datetime2"] = RejectingType
    assert isinstance(sqlserver._kes_sqlserver_type((
        "created_at", "datetime2", "YES", None, None, None, None, 6,
        None, None, None, None, "datetime2(6)",
    )), RejectingType)

    oracle_cases = (
        ("SMALLINT", sqltypes.SmallInteger),
        ("BIGINT", sqltypes.BigInteger),
        ("NUMBER", sqltypes.Numeric),
        ("BINARY_FLOAT", sa_dialect.BINARY_FLOAT),
        ("BINARY_DOUBLE", sa_dialect.BINARY_DOUBLE),
        ("VARCHAR2", sqltypes.VARCHAR),
        ("NVARCHAR2", sqltypes.NVARCHAR),
        ("CHAR", sqltypes.CHAR),
        ("NCHAR", sqltypes.NCHAR),
        ("CLOB", sqltypes.CLOB),
        ("NCLOB", sqltypes.UnicodeText),
        ("BLOB", sqltypes.LargeBinary),
        ("DATE", sa_dialect.ORACLE_DATE),
        ("TIMESTAMP", sa_dialect.ORACLE_TIMESTAMP),
        ("TIMESTAMP WITH TIME ZONE", sa_dialect.ORACLE_TIMESTAMP),
        ("TIMESTAMP WITH LOCAL TIME ZONE", sa_dialect.ORACLE_TIMESTAMP),
        ("DSINTERVAL", sa_dialect.ORACLE_INTERVAL),
        ("YMINTERVAL", sqltypes.String),
        ("BOOLEAN", sqltypes.Boolean),
        ("UNKNOWN", sqltypes.String),
    )
    for type_name, expected_type in oracle_cases:
        reflected = sa_dialect.KESOracleDialect_asyncpg._kes_oracle_type((
            "value", type_name, "Y", None, 20, 10, 2,
        ))
        assert isinstance(reflected, expected_type), type_name


def test_sqlalchemy_reflection_preserves_foreign_key_and_index_options(
) -> None:
    """测试点：方言反射保留 FK 动作、MATCH、表达式及索引长度。"""
    pytest.importorskip("sqlalchemy")
    from asyncpg.sa_dialect import KESMySQLDialect_asyncpg

    class Result:
        def __init__(self, rows: list[tuple[object, ...]]) -> None:
            self._rows = rows

        def all(self) -> list[tuple[object, ...]]:
            return self._rows

    class Connection:
        def exec_driver_sql(
            self,
            query: str,
            parameters: tuple[object, ...],
        ) -> Result:
            if "referential_constraints" in query:
                return Result([
                    (
                        "fk_child_parent",
                        "parent_id",
                        "public",
                        "parent",
                        "id",
                        "CASCADE",
                        "SET NULL",
                        "FULL",
                    ),
                    (
                        "fk_child_optional",
                        "optional_parent_id",
                        "public",
                        "parent",
                        "id",
                        None,
                        None,
                        None,
                    ),
                ])
            if "FROM pg_catalog.pg_class AS tbl" in query:
                return Result([
                    (
                        "ix_expression", None, True, 1, None,
                        "lower(label)",
                    ),
                    ("ix_prefix", "label", True, 1, 10, None),
                    ("uq_label", "label", False, 1, None, None),
                ])
            raise AssertionError(query)

    dialect = KESMySQLDialect_asyncpg()
    dialect.default_schema_name = "public"
    connection = Connection()

    foreign_keys = dialect.get_foreign_keys(connection, "child")
    foreign_keys_by_name = {
        item["name"]: item for item in foreign_keys
    }
    assert foreign_keys_by_name["fk_child_parent"] == {
        "name": "fk_child_parent",
        "constrained_columns": ["parent_id"],
        "referred_schema": "public",
        "referred_table": "parent",
        "referred_columns": ["id"],
        "options": {
            "onupdate": "CASCADE",
            "ondelete": "SET NULL",
            "match": "FULL",
        },
    }
    assert foreign_keys_by_name["fk_child_optional"]["options"] == {}

    dialect.get_pk_constraint = lambda *args, **kwargs: {
        "name": "pk_child"
    }
    dialect.get_unique_constraints = lambda *args, **kwargs: [{
        "name": "uq_label"
    }]
    indexes = {
        item["name"]: item
        for item in dialect.get_indexes(connection, "child")
    }
    assert indexes["ix_expression"]["expressions"] == ["lower(label)"]
    assert indexes["ix_prefix"]["dialect_options"] == {
        "mysql_length": {"label": 10}
    }
    assert indexes["uq_label"]["duplicates_constraint"] == "uq_label"


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
def test_pool_configuration_boundaries_fail_before_connecting(
    options: dict[str, object],
    error_type: type[Exception],
    message: str,
) -> None:
    """测试点：Pool 容量、生命周期及扩展类型非法边界在建连前失败。"""
    async def scenario() -> None:
        with pytest.raises(error_type, match=message):
            asyncpg.create_pool(**options)

    asyncio.run(scenario())


def test_connect_timeout_aborts_stalled_protocol_handshake() -> None:
    """测试点：建连总超时会中止已建立 TCP 但不响应的协议握手。"""
    async def scenario() -> None:
        release_handlers = asyncio.Event()
        handler_tasks: set[asyncio.Task[None]] = set()

        async def stalled_server(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            task = asyncio.current_task()
            assert task is not None
            handler_tasks.add(task)
            try:
                await release_handlers.wait()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(
            stalled_server, "127.0.0.1", 0
        )
        port = server.sockets[0].getsockname()[1]
        started = asyncio.get_running_loop().time()
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncpg.connect(
                    host="127.0.0.1",
                    port=port,
                    user="system",
                    password="unused",
                    database="test",
                    kes_mode="mysql",
                    ssl=False,
                    timeout=0.05,
                )
            elapsed = asyncio.get_running_loop().time() - started
            assert 0.04 <= elapsed < 1
        finally:
            release_handlers.set()
            server.close()
            await server.wait_closed()
            if handler_tasks:
                await asyncio.gather(*handler_tasks)

    asyncio.run(scenario())
