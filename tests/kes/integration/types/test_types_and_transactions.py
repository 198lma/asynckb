"""Integration tests for KES codecs, data types, and transactions."""

from __future__ import annotations

import asyncio
import datetime
import ipaddress
import json
from decimal import Decimal
import uuid

import asyncpg
import pytest

from tests.kes.support.config import KESConfig, drop_table, unique_object_name


pytestmark = pytest.mark.integration


async def _assert_rejected_transaction_option_preserves_connection(
    config: KESConfig,
    transaction_options: dict[str, object],
) -> None:
    connection = await asyncpg.connect(**config.connection_kwargs())
    try:
        transaction = connection.transaction(**transaction_options)
        with pytest.raises(asyncpg.UnsupportedClientFeatureError):
            await transaction.start()

        assert connection._top_xact is None
        assert not connection.is_in_transaction()

        async with connection.transaction():
            assert await connection.fetchval(config.select_one) == 1

        assert connection._top_xact is None
        assert not connection.is_in_transaction()
    finally:
        await connection.close()


def test_standard_asyncpg_scalar_array_and_network_codecs(
    kes_config: KESConfig,
) -> None:
    """测试点：原 asyncpg 标量、UUID、二进制、数组、JSONB 和网络 codec 正常。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        suffix = " FROM dual" if kes_config.mode == "oracle" else ""
        values = (
            True,
            -123,
            123456,
            2**40,
            1.25,
            2.5,
            Decimal("12345.6789"),
            uuid.UUID("12345678-1234-5678-1234-567812345678"),
            b"\x00\xffabc",
            ["a", None, "c"],
            [1, None, 3],
            json.dumps({"a": 1}),
            ipaddress.ip_address("192.0.2.1"),
            ipaddress.ip_network("192.0.2.0/24"),
        )
        query = (
            "SELECT $1::boolean, $2::smallint, $3::integer, $4::bigint, "
            "$5::real, $6::double precision, $7::numeric(20,4), "
            f"$8::uuid, $9::bytea, "
            f"$10::{kes_config.array_type('text')}, "
            f"$11::{kes_config.array_type('integer')}, "
            "$12::jsonb, $13::inet, $14::cidr" + suffix
        )
        try:
            row = await connection.fetchrow(query, *values)
            assert tuple(row) == values
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_mysql_rejected_deferrable_transaction_preserves_connection(
    mysql_config: KESConfig,
) -> None:
    """测试点：MySQL 拒绝 DEFERRABLE 后不残留事务，连接可立即复用。"""
    asyncio.run(_assert_rejected_transaction_option_preserves_connection(
        mysql_config, {"deferrable": True}))


@pytest.mark.parametrize(
    "transaction_options",
    [
        pytest.param(
            {"isolation": "read_uncommitted"}, id="read-uncommitted"),
        pytest.param(
            {"isolation": "repeatable_read"}, id="repeatable-read"),
        pytest.param({"deferrable": True}, id="deferrable"),
    ],
)
def test_oracle_rejected_transaction_option_preserves_connection(
    oracle_config: KESConfig,
    transaction_options: dict[str, object],
) -> None:
    """测试点：Oracle 拒绝不支持的事务选项后，连接状态可立即复用。"""
    asyncio.run(_assert_rejected_transaction_option_preserves_connection(
        oracle_config, transaction_options))


def test_oracle_nested_transaction_uses_session_default_isolation(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle 隐式外层事务按会话 SERIALIZABLE 校验嵌套隔离级别。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**oracle_config.connection_kwargs(
            server_settings={
                "default_transaction_isolation": "serializable",
            }))
        try:
            async with connection.transaction():
                async with connection.transaction(isolation="serializable"):
                    assert await connection.fetchval(
                        "SHOW transaction_isolation") == "serializable"

                with pytest.raises(
                    asyncpg.InterfaceError,
                    match="current 'read_committed' != outer 'serializable'",
                ):
                    async with connection.transaction(
                        isolation="read_committed"
                    ):
                        pass
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_mysql_custom_codec_reset_restores_kes_default(
    mysql_config: KESConfig,
) -> None:
    """测试点：MySQL 专有类型的自定义 codec 重置后恢复 KES 默认 codec。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**mysql_config.connection_kwargs())
        try:
            await connection.set_type_codec(
                "tinyint",
                schema="pg_catalog",
                encoder=str,
                decoder=lambda value: ("custom", value),
                format="text",
            )
            assert await connection.fetchval(
                "SELECT CAST(7 AS TINYINT)") == ("custom", "7")

            await connection.reset_type_codec(
                "tinyint", schema="pg_catalog")
            assert await connection.fetchval(
                "SELECT CAST(7 AS TINYINT)") == 7

            await connection.set_builtin_type_codec(
                "tinyint",
                schema="pg_catalog",
                codec_name="text",
                format="text",
            )
            assert await connection.fetchval(
                "SELECT CAST(8 AS TINYINT)") == "8"

            await connection.reset_type_codec(
                "tinyint", schema="pg_catalog")
            assert await connection.fetchval(
                "SELECT CAST(8 AS TINYINT)") == 8
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_oracle_custom_codec_reset_restores_kes_default(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle 专有类型的自定义 codec 重置后恢复 KES 默认 codec。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**oracle_config.connection_kwargs())
        query = "SELECT INTERVAL '1 02:03:04' DAY TO SECOND FROM dual"
        try:
            await connection.set_type_codec(
                "dsinterval",
                schema="sys",
                encoder=str,
                decoder=lambda value: ("custom", value),
                format="text",
            )
            assert await connection.fetchval(query) == (
                "custom", "+01 02:03:04.000000")

            await connection.reset_type_codec("dsinterval", schema="sys")
            assert await connection.fetchval(
                query) == "+01 02:03:04.000000"
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_kes_builtin_codec_rejects_incompatible_binary_wire_format(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式文本 wire 类型拒绝错误 binary builtin 且连接可复用。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        if kes_config.mode == "mysql":
            rejected_codecs = (
                ("timestamp", "pg_catalog", "timestamp"),
                ("json", "pg_catalog", "json"),
            )
            text_type = ("timestamp", "pg_catalog")
            text_query = (
                "SELECT CAST("
                "'2025-01-02 03:04:05.123456' AS TIMESTAMP(6))"
            )
            expected_default = datetime.datetime(
                2025, 1, 2, 3, 4, 5, 123456
            )
            expected_text = "2025-01-02 03:04:05.123456"
            binary_schema = "pg_catalog"
            binary_query = "SELECT $1::varbinary"
        elif kes_config.mode == "oracle":
            rejected_codecs = (("dsinterval", "sys", "interval"),)
            text_type = ("dsinterval", "sys")
            text_query = (
                "SELECT INTERVAL '1 02:03:04.123456' "
                "DAY TO SECOND FROM dual"
            )
            expected_default = "+01 02:03:04.123456"
            expected_text = expected_default
            binary_schema = "pg_catalog"
            binary_query = "SELECT $1::blob FROM dual"
        else:
            rejected_codecs = (("datetime2", "sys", "timestamp"),)
            text_type = ("datetime2", "sys")
            text_query = (
                "SELECT CAST("
                "'2025-01-02 03:04:05.123456' AS DATETIME2(6))"
            )
            expected_default = datetime.datetime(
                2025, 1, 2, 3, 4, 5, 123456
            )
            expected_text = "2025-01-02 03:04:05.123456"
            binary_schema = "sys"
            binary_query = "SELECT CAST($1 AS VARBINARY(20))"
        try:
            for typename, schema, codec_name in rejected_codecs:
                for data_format in (None, "binary"):
                    with pytest.raises(
                        asyncpg.UnsupportedClientFeatureError,
                        match="text-only wire format",
                    ):
                        await connection.set_builtin_type_codec(
                            typename,
                            schema=schema,
                            codec_name=codec_name,
                            format=data_format,
                        )

            assert await connection.fetchval(text_query) == expected_default
            if kes_config.mode == "mysql":
                assert await connection.fetchval(
                    "SELECT CAST('{\"a\":1}' AS JSON)"
                ) == '{"a": 1}'

            await connection.set_builtin_type_codec(
                text_type[0],
                schema=text_type[1],
                codec_name="text",
                format="text",
            )
            assert await connection.fetchval(text_query) == expected_text
            await connection.reset_type_codec(
                text_type[0], schema=text_type[1]
            )

            await connection.set_builtin_type_codec(
                "blob" if kes_config.mode == "oracle" else "varbinary",
                schema=binary_schema,
                codec_name="bytea",
                format="binary",
            )
            assert await connection.fetchval(
                binary_query, b"\x00binary"
            ) == b"\x00binary"
            await connection.reset_type_codec(
                "blob" if kes_config.mode == "oracle" else "varbinary",
                schema=binary_schema,
            )

            assert await connection.fetchval(kes_config.select_one) == 1
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_oracle_standard_date_tuple_codec_maps_to_timestamp_oid(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle DATE codec 映射实际 TIMESTAMP OID 并保留 PG date tuple。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**oracle_config.connection_kwargs())
        try:
            await connection.set_type_codec(
                "date",
                schema="pg_catalog",
                encoder=tuple,
                decoder=tuple,
                format="tuple",
            )
            assert await connection.fetchval(
                "SELECT ($1::date)::text FROM dual", (3,)
            ) == "2000-01-04 00:00:00"
            assert await connection.fetchval(
                "SELECT $1::date FROM dual", (3,)
            ) == (3,)

            await connection.reset_type_codec(
                "date", schema="pg_catalog")
            assert await connection.fetchval(
                "SELECT DATE '2025-01-02' FROM dual"
            ) == datetime.datetime(2025, 1, 2)
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_mysql_standard_json_codec_name_maps_to_kes_json(
    mysql_config: KESConfig,
) -> None:
    """测试点：标准 pg_catalog.json codec API 映射到 KES MySQL JSON。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**mysql_config.connection_kwargs())
        data = {"foo": "bar", "count": 2}
        try:
            await connection.set_type_codec(
                "json",
                schema="pg_catalog",
                encoder=json.dumps,
                decoder=json.loads,
                format="text",
            )
            assert await connection.fetchval("SELECT $1::json", data) == data
            assert await connection.fetchval(
                f"SELECT $1::{mysql_config.array_type('json')}",
                [data],
            ) == [data]

            await connection.set_type_codec(
                "json",
                schema="pg_catalog",
                encoder=lambda value: json.dumps(value).encode("utf-8"),
                decoder=lambda value: json.loads(value.decode("utf-8")),
                format="binary",
            )
            assert await connection.fetchval("SELECT $1::json", data) == data
            assert await connection.fetchval(
                f"SELECT $1::{mysql_config.array_type('json')}",
                [data],
            ) == [data]

            await connection.set_type_codec(
                "json",
                schema="pg_catalog",
                encoder=lambda value: 3,
                decoder=lambda value: value,
                format="binary",
            )
            with pytest.raises(
                asyncpg.DataError,
                match="a bytes-like object is required",
            ):
                await connection.fetchval("SELECT $1::json", data)

            await connection.reset_type_codec("json", schema="pg_catalog")
            assert await connection.fetchval("SELECT '{}'::json") == "{}"
            with pytest.raises(
                asyncpg.DataError,
                match="expected str, got int",
            ):
                await connection.fetchval("SELECT $1::json", 1)
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_mysql_builtin_json_codec_updates_domain_and_base_type(
    mysql_config: KESConfig,
) -> None:
    """测试点：MySQL JSON builtin codec 同步更新 domain 及其基类型。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(
            **mysql_config.connection_kwargs()
        )
        try:
            await connection.set_builtin_type_codec(
                "json",
                schema="pg_catalog",
                codec_name="text",
                format="text",
            )
            scalar = await connection.fetchval(
                "SELECT $1::json", '{"value":1}'
            )
            assert isinstance(scalar, str)
            assert json.loads(scalar) == {"value": 1}
            array = await connection.fetchval(
                f"SELECT $1::{mysql_config.array_type('json')}",
                ['{"value":1}', '{"value":2}'],
            )
            assert all(isinstance(item, str) for item in array)
            assert [json.loads(item) for item in array] == [
                {"value": 1},
                {"value": 2},
            ]

            await connection.reset_type_codec(
                "json", schema="pg_catalog"
            )
            assert await connection.fetchval("SELECT '{}'::json") == "{}"
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("typename", "query"),
    [
        pytest.param(
            "date", "SELECT CAST('2025-01-02' AS DATE)", id="date"),
        pytest.param(
            "time", "SELECT CAST('03:04:05' AS TIME)", id="time"),
        pytest.param(
            "timestamp",
            "SELECT CAST('2025-01-02 03:04:05' AS TIMESTAMP)",
            id="timestamp",
        ),
        pytest.param("bit", "SELECT CAST(5 AS BIT(8))", id="bit"),
    ],
)
def test_mysql_standard_codec_name_maps_to_kes_type(
    mysql_config: KESConfig,
    typename: str,
    query: str,
) -> None:
    """测试点：MySQL 标准日期时间和 BIT codec 名称映射到实际 KES OID。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**mysql_config.connection_kwargs())
        try:
            expected = await connection.fetchval(query)
            await connection.set_type_codec(
                typename,
                schema="pg_catalog",
                encoder=str,
                decoder=lambda value: ("custom", value),
                format="text",
            )
            assert (await connection.fetchval(query))[0] == "custom"

            await connection.reset_type_codec(
                typename, schema="pg_catalog")
            assert await connection.fetchval(query) == expected
        finally:
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("typename", "value", "expected_text"),
    [
        pytest.param("date", (3,), "2000-01-04", id="date"),
        pytest.param("date", (2**31 - 1,), "infinity", id="date-infinity"),
        pytest.param("time", (60 * 10**6,), "00:01:00", id="time"),
        pytest.param(
            "timestamp",
            (60 * 10**6,),
            "2000-01-01 00:01:00",
            id="timestamp",
        ),
        pytest.param(
            "timestamp",
            (2**63 - 1,),
            "infinity",
            id="timestamp-infinity",
        ),
    ],
)
def test_mysql_standard_temporal_tuple_codec_maps_to_kes_text_protocol(
    mysql_config: KESConfig,
    typename: str,
    value: tuple[int],
    expected_text: str,
) -> None:
    """测试点：标准时间 tuple codec 保留 PG epoch 语义并适配 KES 文本协议。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**mysql_config.connection_kwargs())
        try:
            await connection.set_type_codec(
                typename,
                schema="pg_catalog",
                encoder=tuple,
                decoder=tuple,
                format="tuple",
            )
            assert await connection.fetchval(
                f"SELECT ($1::{typename})::text", value
            ) == expected_text
            assert await connection.fetchval(
                f"SELECT $1::{typename}", value
            ) == value
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_mysql_timestamp_accepts_date_and_rejects_invalid_input(
    mysql_config: KESConfig,
) -> None:
    """测试点：MySQL TIMESTAMP 接受 date，拒绝字符串和带时区时间。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**mysql_config.connection_kwargs())
        try:
            assert await connection.fetchval(
                "SELECT $1::timestamp", datetime.date(2025, 1, 2)
            ) == datetime.datetime(2025, 1, 2)
            with pytest.raises(
                asyncpg.DataError,
                match="expected a datetime.date",
            ):
                await connection.fetchval("SELECT $1::timestamp", "invalid")
            with pytest.raises(
                asyncpg.DataError,
                match="offset-naive and offset-aware",
            ):
                await connection.fetchval(
                    "SELECT $1::timestamp",
                    datetime.datetime(
                        2025,
                        1,
                        2,
                        3,
                        4,
                        5,
                        tzinfo=datetime.timezone.utc,
                    ),
                )
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_mysql_common_type_matrix_round_trips_values(
    mysql_config: KESConfig,
) -> None:
    """测试点：MySQL 模式覆盖数值、字符、二进制、日期时间、JSON、BIT。"""
    async def scenario() -> None:
        table = unique_object_name("mysql_types", mysql_config.mode)
        values = (
            1,
            2,
            3,
            Decimal("4.50"),
            1.25,
            2.5,
            "v",
            "text",
            b"blob",
            b"var",
            datetime.date(2025, 1, 2),
            datetime.time(3, 4, 5, 6000),
            datetime.datetime(2025, 1, 2, 3, 4, 5, 6000),
            datetime.datetime(2025, 1, 2, 3, 4, 5, 6000),
            "{}",
            b"\x05",
        )
        connection = await asyncpg.connect(**mysql_config.connection_kwargs())
        try:
            await connection.execute(
                f"CREATE TABLE {table} (id INT PRIMARY KEY, si SMALLINT, "
                f"bi BIGINT, de DECIMAL(10,2), fl FLOAT, db DOUBLE, "
                f"vc VARCHAR(20), tx TEXT, bl BLOB, vb VARBINARY(20), "
                f"dt DATE, tm TIME(6), dtt DATETIME(6), ts TIMESTAMP(6), "
                f"js JSON, bt BIT(8))"
            )
            await connection.execute(
                f"INSERT INTO {table} VALUES ("
                "$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)",
                *values,
            )
            row = await connection.fetchrow(f"SELECT * FROM {table}")
            assert tuple(row) == values
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_oracle_common_type_matrix_round_trips_values(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle 模式覆盖 NUMBER、CHAR、LOB、BLOB、时区和 INTERVAL。"""
    async def scenario() -> None:
        table = unique_object_name("oracle_types", oracle_config.mode)
        value_datetime = datetime.datetime(2025, 1, 2, 3, 4, 5)
        values = (
            1,
            Decimal("2.50"),
            1.25,
            2.5,
            "c",
            "n",
            "v",
            "nv",
            "clob",
            "nclob",
            b"blob",
            b"var",
            value_datetime,
            value_datetime,
            value_datetime.replace(tzinfo=datetime.timezone.utc),
            datetime.timedelta(days=1, seconds=2),
            "+02-03",
            True,
        )
        expected = (
            1,
            Decimal("2.50"),
            1.25,
            2.5,
            "c    ",
            "n    ",
            "v",
            "nv",
            "clob",
            "nclob",
            b"blob",
            b"var",
            value_datetime,
            value_datetime,
            value_datetime.replace(tzinfo=datetime.timezone.utc),
            "+01 00:00:02.000000",
            "+02-03",
            True,
        )
        connection = await asyncpg.connect(**oracle_config.connection_kwargs())
        try:
            await connection.execute(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, "
                f"n NUMBER(10,2), bf BINARY_FLOAT, bd BINARY_DOUBLE, "
                f"c CHAR(5), nc NCHAR(5), vc VARCHAR2(20), "
                f"nvc NVARCHAR2(20), "
                f"cl CLOB, ncl NCLOB, bl BLOB, vb BYTEA, d DATE, "
                f"ts TIMESTAMP, tz TIMESTAMP WITH TIME ZONE, "
                f"ds INTERVAL DAY TO SECOND, ym INTERVAL YEAR TO MONTH, "
                f"b BOOLEAN)"
            )
            await connection.execute(
                f"INSERT INTO {table} VALUES ("
                "$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,"
                "$15,$16,$17,$18)",
                *values,
            )
            row = await connection.fetchrow(f"SELECT * FROM {table}")
            assert tuple(row) == expected
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_sqlserver_common_type_matrix_round_trips_values(
    sqlserver_config: KESConfig,
) -> None:
    """测试点：SQL Server 模式覆盖数值、Unicode、日期时间、UUID 和二进制类型。"""
    async def scenario() -> None:
        table = unique_object_name("sqlserver_types", sqlserver_config.mode)
        identifier = uuid.UUID("12345678-1234-5678-1234-567812345678")
        values = (
            1,
            True,
            255,
            Decimal("123.4500"),
            datetime.date(2025, 1, 2),
            datetime.time(3, 4, 5, 123456),
            datetime.datetime(2025, 1, 2, 3, 4, 5, 123456),
            datetime.datetime(2025, 1, 2, 3, 4, 5),
            datetime.datetime(2025, 1, 2, 3, 4),
            identifier,
            "ab",
            "label",
            b"\x00\xff",
        )
        connection = await asyncpg.connect(
            **sqlserver_config.connection_kwargs()
        )
        try:
            await connection.execute(
                f"CREATE TABLE {table} (id INT PRIMARY KEY, flag BIT, "
                "tiny TINYINT, amount MONEY, event_date DATE, "
                "event_time TIME(6), created DATETIME2(6), "
                "legacy DATETIME, rounded SMALLDATETIME, "
                "identifier UNIQUEIDENTIFIER, fixed NCHAR(4), "
                "label NVARCHAR(30), payload VARBINARY(10), rv ROWVERSION)"
            )
            await connection.execute(
                f"INSERT INTO {table} (id, flag, tiny, amount, event_date, "
                "event_time, created, legacy, rounded, identifier, fixed, "
                "label, payload) VALUES ("
                "$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
                *values,
            )
            row = await connection.fetchrow(f"SELECT * FROM {table}")
            assert tuple(row[:-1]) == values[:10] + ("ab  ",) + values[11:]
            assert isinstance(row[-1], bytes)
            assert len(row[-1]) == 8
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_mysql_unsigned_enum_set_and_binary_types_round_trip(
    mysql_config: KESConfig,
) -> None:
    """测试点：MySQL 无符号整数边界、ENUM/SET 及含零字节二进制类型正常。"""
    async def scenario() -> None:
        table = unique_object_name("mysql_native", mysql_config.mode)
        connection = await asyncpg.connect(
            **mysql_config.connection_kwargs()
        )
        try:
            await connection.execute(
                f"CREATE TABLE {table} ("
                "u4 INT UNSIGNED, u8 BIGINT UNSIGNED, "
                "fixed BINARY(5), varying VARBINARY(5), "
                "choice ENUM('red','green'), flags SET('a','b','c'))"
            )
            await connection.execute(
                f"INSERT INTO {table} VALUES ($1,$2,$3,$4,$5,$6)",
                2**32 - 1,
                2**64 - 1,
                b"a\x00b",
                b"\x00z",
                "green",
                "a,c",
            )

            statement = await connection.prepare(f"SELECT * FROM {table}")
            assert tuple(await statement.fetchrow()) == (
                2**32 - 1,
                2**64 - 1,
                b"a\x00b\x00\x00",
                b"\x00z",
                "green",
                "a,c",
            )
            assert [
                attribute.type.name
                for attribute in statement.get_attributes()[:4]
            ] == ["uint4", "uint8", "binary", "varbinary"]

            invalid_values = (
                (-1, 1),
                (1, -1),
                (2**32, 1),
                (1, 2**64),
            )
            for u4, u8 in invalid_values:
                with pytest.raises(asyncpg.NumericValueOutOfRangeError):
                    await connection.execute(
                        f"INSERT INTO {table} (u4, u8) VALUES ($1, $2)",
                        u4,
                        u8,
                    )

            for invalid_binary in (3, [65, 66]):
                with pytest.raises(
                    asyncpg.DataError,
                    match="a bytes-like object is required",
                ):
                    await connection.execute(
                        f"INSERT INTO {table} (varying) VALUES ($1)",
                        invalid_binary,
                    )

            assert await connection.fetchval(
                "SELECT $1::tinyint", True
            ) == 1
            with pytest.raises(
                asyncpg.DataError,
                match="cannot be interpreted as an integer",
            ):
                await connection.fetchval("SELECT $1::tinyint", "7")

            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 1
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_oracle_rowid_bfile_and_local_timestamp_types_round_trip(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle ROWID/UROWID、BFILE、BLOB 和本地时区时间戳正常。"""
    async def scenario() -> None:
        table = unique_object_name("oracle_native", oracle_config.mode)
        directory = f"APGDIR{uuid.uuid4().hex[:8].upper()}"
        local_timestamp = datetime.datetime(
            2025, 1, 2, 3, 4, 5, 6000
        )
        connection = await asyncpg.connect(
            **oracle_config.connection_kwargs()
        )
        try:
            await connection.execute(
                f"CREATE TABLE {table} ("
                "payload BLOB, "
                "local_time TIMESTAMP WITH LOCAL TIME ZONE)"
            )
            await connection.execute(
                f"INSERT INTO {table} VALUES ($1, $2)",
                b"\x00z",
                local_timestamp,
            )

            statement = await connection.prepare(f"SELECT * FROM {table}")
            assert tuple(await statement.fetchrow()) == (
                b"\x00z",
                local_timestamp,
            )
            assert [
                attribute.type.name
                for attribute in statement.get_attributes()
            ] == ["bytea", "timestamp"]

            with pytest.raises(
                asyncpg.DataError,
                match="a bytes-like object is required",
            ):
                await connection.execute(
                    f"INSERT INTO {table} (payload) VALUES ($1)",
                    3,
                )

            await connection.execute(
                f"CREATE DIRECTORY {directory} AS '/tmp'"
            )
            locator_statement = await connection.prepare(
                "SELECT nextrowid() AS rid, $1::urowid AS urid, "
                f"BFILENAME('{directory}', 'missing.dat') AS file "
                "FROM dual"
            )
            row = await locator_statement.fetchrow(
                "AAAPr9AAEAAAACXAAA"
            )
            assert row[0]
            assert row[1] == "AAAPr9AAEAAAACXAAA"
            assert row[2] == (
                f"bfilename('{directory}', 'missing.dat')"
            )
            assert [
                attribute.type.name
                for attribute in locator_statement.get_attributes()
            ] == ["rowid", "urowid", "bfile"]
            assert locator_statement.get_parameters()[0].name == "urowid"
            with pytest.raises(
                asyncpg.DataError,
                match="expected str, got int",
            ):
                await locator_statement.fetchrow(123)
            with pytest.raises(
                asyncpg.DataError,
                match="expected str, got int",
            ):
                await connection.fetchval(
                    "SELECT $1::yminterval FROM dual", 123
                )
        finally:
            try:
                await connection.execute(f"DROP DIRECTORY {directory}")
            except asyncpg.PostgresError:
                pass
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_mysql_types_transactions_and_pool(mysql_config: KESConfig) -> None:
    """测试点：MySQL 特有类型、嵌套事务和单连接连接池均可工作。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**mysql_config.connection_kwargs())
        try:
            assert connection.get_kes_mode() == "mysql"
            assert await connection.fetchval(
                "SELECT CAST($1 AS TINYINT)", 12
            ) == 12
            assert await connection.fetchval(
                "SELECT CAST('2025-01-02' AS DATE)"
            ) == datetime.date(2025, 1, 2)
            assert await connection.fetchval(
                "SELECT CAST($1 AS VARBINARY)", b"abc"
            ) == b"abc"
            assert await connection.fetchval(
                "SELECT CAST('25:01:02.123' AS TIME(3))"
            ) == datetime.timedelta(
                hours=25, minutes=1, seconds=2, milliseconds=123
            )
            assert await connection.fetchval(
                "SELECT CAST('-25:01:02.123' AS TIME(3))"
            ) == -datetime.timedelta(
                hours=25, minutes=1, seconds=2, milliseconds=123
            )
            for isolation in (
                "read_uncommitted",
                "read_committed",
                "repeatable_read",
                "serializable",
            ):
                async with connection.transaction(isolation=isolation):
                    assert await connection.fetchval(
                        "SHOW transaction_isolation"
                    ) == isolation.replace("_", " ")
                    async with connection.transaction():
                        assert await connection.fetchval("SELECT 1") == 1
        finally:
            await connection.close()

        pool_options = mysql_config.connection_kwargs()
        pool_options.pop("timeout")
        pool = await asyncpg.create_pool(
            **pool_options, min_size=1, max_size=1
        )
        try:
            async with pool.acquire() as pooled:
                assert await pooled.fetchval("SELECT CAST(7 AS TINYINT)") == 7
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_oracle_types_and_supported_transaction_isolation(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle INTERVAL 编解码、READ COMMITTED 和 SERIALIZABLE 事务。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**oracle_config.connection_kwargs())
        try:
            assert connection.get_kes_mode() == "oracle"
            assert await connection.fetchval(
                "SELECT INTERVAL '3 04:05:06.123456' "
                "DAY TO SECOND FROM dual"
            ) == "+03 04:05:06.123456"
            assert await connection.fetchval(
                "SELECT INTERVAL '2-3' YEAR TO MONTH FROM dual"
            ) == "+02-03"
            negative_interval = datetime.timedelta(microseconds=-1)
            assert await connection.fetchval(
                "SELECT extract(epoch from "
                "CAST($1 AS INTERVAL DAY TO SECOND)) FROM dual",
                negative_interval,
            ) == pytest.approx(-0.000001)
            assert await connection.fetchval(
                "SELECT TIMESTAMP '2000-01-01 00:00:00' + "
                "CAST($1 AS INTERVAL DAY TO SECOND) FROM dual",
                negative_interval,
            ) == datetime.datetime(1999, 12, 31, 23, 59, 59, 999999)
            async with connection.transaction(isolation="read_committed"):
                assert await connection.fetchval("SELECT 1 FROM dual") == 1
            async with connection.transaction(isolation="serializable"):
                assert await connection.fetchval("SELECT 1 FROM dual") == 1
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_supported_readonly_transactions_reject_writes_and_recover(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式只读事务在支持的隔离级别下拒绝写入，回滚后连接可复用。"""
    async def scenario() -> None:
        table = unique_object_name("readonly", kes_config.mode)
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            await connection.execute(f"CREATE TABLE {table} (id INTEGER)")

            for isolation in (None, "read_committed", "serializable"):
                with pytest.raises(asyncpg.ReadOnlySQLTransactionError):
                    async with connection.transaction(
                        isolation=isolation,
                        readonly=True,
                    ):
                        assert await connection.fetchval(
                            "SHOW transaction_read_only"
                        ) == "on"
                        await connection.execute(
                            f"INSERT INTO {table} VALUES (1)"
                        )

                assert not connection.is_in_transaction()
                assert await connection.fetchval(kes_config.select_one) == 1

            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 0
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_server_errors_map_to_asyncpg_subclasses_and_preserve_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式约束及 SQL 错误映射准确，报错后连接可立即复用。"""
    async def scenario() -> None:
        parent_table = unique_object_name("error_parent", kes_config.mode)
        child_table = unique_object_name("error_child", kes_config.mode)
        missing_table = unique_object_name("error_missing", kes_config.mode)
        integer_type = (
            "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
        )
        connection = await asyncpg.connect(**kes_config.connection_kwargs())

        async def assert_error(
            error_type: type[asyncpg.PostgresError],
            sqlstate: str,
            query: str,
        ) -> asyncpg.PostgresError:
            with pytest.raises(error_type) as raised:
                await connection.execute(query)
            assert raised.value.sqlstate == sqlstate
            assert await connection.fetchval(kes_config.select_one) == 1
            return raised.value

        try:
            await connection.execute(
                f"CREATE TABLE {parent_table} ("
                f"id {integer_type} PRIMARY KEY)"
            )
            await connection.execute(
                f"CREATE TABLE {child_table} ("
                f"id {integer_type} PRIMARY KEY, "
                f"unique_value {integer_type} UNIQUE, "
                f"checked_value {integer_type} CHECK (checked_value > 0), "
                f"parent_id {integer_type} REFERENCES {parent_table}(id))"
            )
            await connection.execute(
                f"INSERT INTO {parent_table} VALUES (1)"
            )
            await connection.execute(
                f"INSERT INTO {child_table} VALUES (1, 10, 1, 1)"
            )

            await assert_error(
                asyncpg.UniqueViolationError,
                "23505",
                f"INSERT INTO {child_table} VALUES (2, 10, 1, 1)",
            )
            await assert_error(
                asyncpg.CheckViolationError,
                "23514",
                f"INSERT INTO {child_table} VALUES (2, 20, -1, 1)",
            )
            await assert_error(
                asyncpg.ForeignKeyViolationError,
                "23503",
                f"INSERT INTO {child_table} VALUES (2, 20, 1, 999)",
            )
            await assert_error(
                asyncpg.PostgresSyntaxError,
                "42601",
                "SELEC 1",
            )
            await assert_error(
                asyncpg.UndefinedTableError,
                "42P01",
                f"SELECT * FROM {missing_table}",
            )

            assert await connection.fetchval(
                f"SELECT count(*) FROM {child_table}"
            ) == 1
        finally:
            await drop_table(connection, child_table)
            await drop_table(connection, parent_table)
            await connection.close()

    asyncio.run(scenario())


def test_not_null_semantics_match_kes_compatibility_mode(
    kes_config: KESConfig,
) -> None:
    """测试点：NOT NULL 的 MySQL 零值转换和 Oracle 拒绝语义均符合 KES。"""
    async def scenario() -> None:
        parent_table = unique_object_name("notnull_parent", kes_config.mode)
        plain_table = unique_object_name("notnull_plain", kes_config.mode)
        foreign_table = unique_object_name("notnull_foreign", kes_config.mode)
        integer_type = (
            "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
        )
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            await connection.execute(
                f"CREATE TABLE {parent_table} ("
                f"id {integer_type} PRIMARY KEY)"
            )
            await connection.execute(
                f"CREATE TABLE {plain_table} ("
                f"id {integer_type} PRIMARY KEY, "
                f"required_value {integer_type} NOT NULL)"
            )
            await connection.execute(
                f"CREATE TABLE {foreign_table} ("
                f"id {integer_type} PRIMARY KEY, "
                f"parent_id {integer_type} NOT NULL "
                f"REFERENCES {parent_table}(id))"
            )

            if kes_config.mode == "mysql":
                await connection.execute(
                    f"INSERT INTO {plain_table} VALUES (1, NULL)"
                )
                assert await connection.fetchval(
                    f"SELECT required_value FROM {plain_table} WHERE id = 1"
                ) == 0
                with pytest.raises(
                    asyncpg.ForeignKeyViolationError
                ) as raised:
                    await connection.execute(
                        f"INSERT INTO {foreign_table} VALUES (1, NULL)"
                    )
                assert raised.value.sqlstate == "23503"
                assert "(parent_id)=(0)" in (raised.value.detail or "")
            else:
                with pytest.raises(asyncpg.NotNullViolationError) as raised:
                    await connection.execute(
                        f"INSERT INTO {plain_table} VALUES (1, NULL)"
                    )
                assert raised.value.sqlstate == "23502"
                assert raised.value.column_name == "required_value"

                with pytest.raises(asyncpg.NotNullViolationError) as raised:
                    await connection.execute(
                        f"INSERT INTO {foreign_table} VALUES (1, NULL)"
                    )
                assert raised.value.sqlstate == "23502"
                assert raised.value.column_name == "parent_id"

            assert await connection.fetchval(kes_config.select_one) == 1
        finally:
            await drop_table(connection, foreign_table)
            await drop_table(connection, plain_table)
            await drop_table(connection, parent_table)
            await connection.close()

    asyncio.run(scenario())


def test_oracle_transaction_timeout_and_task_cancellation(
    oracle_config: KESConfig,
) -> None:
    """测试点：事务内层回滚、查询超时和 asyncio 取消后连接仍可复用。"""
    async def scenario() -> None:
        table = unique_object_name("oracle_tx", oracle_config.mode)
        connection = await asyncpg.connect(**oracle_config.connection_kwargs())
        try:
            await connection.execute(
                f"CREATE TABLE {table} ("
                "id INTEGER PRIMARY KEY, label VARCHAR2(20))"
            )
            async with connection.transaction(isolation="serializable"):
                await connection.execute(
                    f"INSERT INTO {table} VALUES (1, 'outer')"
                )
                with pytest.raises(RuntimeError, match="rollback inner"):
                    async with connection.transaction():
                        await connection.execute(
                            f"INSERT INTO {table} VALUES (2, 'inner')"
                        )
                        raise RuntimeError("rollback inner")
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 1

            with pytest.raises(asyncio.TimeoutError):
                await connection.fetchval(
                    "SELECT pg_sleep(1) FROM dual", timeout=0.01
                )
            assert await connection.fetchval("SELECT 42 FROM dual") == 42

            task = asyncio.create_task(
                connection.fetchval("SELECT pg_sleep(1) FROM dual")
            )
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await connection.fetchval("SELECT 43 FROM dual") == 43
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_schema_reload_and_statement_expiry_preserve_kes_codecs(
    kes_config: KESConfig,
) -> None:
    """测试点：Schema cache reload 和 statement TTL 到期后 KES codec 仍可用。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(
            **kes_config.connection_kwargs(
                statement_cache_size=2,
                max_cached_statement_lifetime=0.05,
            )
        )
        if kes_config.mode == "mysql":
            query = "SELECT CAST('2025-01-02' AS DATE)"
            expected = datetime.date(2025, 1, 2)
        elif kes_config.mode == "oracle":
            query = (
                "SELECT INTERVAL '1 00:00:00.123456' "
                "DAY TO SECOND FROM dual"
            )
            expected = "+01 00:00:00.123456"
        else:
            query = (
                "SELECT CAST("
                "'2025-01-02 03:04:05.123456' AS DATETIME2(6))"
            )
            expected = datetime.datetime(2025, 1, 2, 3, 4, 5, 123456)
        try:
            assert await connection.fetchval(query) == expected
            await connection.reload_schema_state()
            assert await connection.fetchval(query) == expected
            await asyncio.sleep(0.1)
            assert len(connection._stmt_cache) == 0
            assert await connection.fetchval(query) == expected
            assert len(connection._stmts_to_close) == 0
        finally:
            await connection.close()

    asyncio.run(scenario())
