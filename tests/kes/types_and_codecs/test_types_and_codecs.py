"""Tests for the types and codecs requirement module."""

from __future__ import annotations

import asyncio
import asynckb
import pytest
import datetime
import ipaddress
import json
from decimal import Decimal
import uuid
from tests.kes.support.config import KESConfig, drop_table, unique_object_name
from asynckb import kes
from asynckb.utils import _quote_ident

async def drop_type(connection: asynckb.Connection, type_name: str) -> None:
    try:
        await connection.execute(f"DROP TYPE {type_name}")
    except asynckb.UndefinedObjectError:
        pass
async def drop_domain(
    connection: asynckb.Connection,
    domain_name: str,
) -> None:
    try:
        await connection.execute(f"DROP DOMAIN {domain_name}")
    except asynckb.UndefinedObjectError:
        pass
@pytest.mark.case_id("KB-TYPE-001")
@pytest.mark.integration
def test_enum_custom_codec_applies_to_scalar_and_array(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式 ENUM 自定义 codec 同时作用于标量和数组元素。"""
    async def scenario() -> None:
        type_name = unique_object_name("enum_type", kes_config.mode)
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            await connection.execute(
                f"CREATE TYPE {type_name} AS ENUM ('foo', 'bar', 'baz')"
            )
            await connection.set_type_codec(
                type_name,
                schema="public",
                encoder=lambda value: str(value).removeprefix("enum: "),
                decoder=lambda value: f"enum: {value}",
                format="text",
            )

            assert await connection.fetchval(
                f"SELECT $1::{type_name}", "enum: foo"
            ) == "enum: foo"
            assert await connection.fetchval(
                "SELECT $1::{}".format(
                    kes_config.array_type(type_name, schema="public")
                ),
                ["enum: foo", "enum: bar"],
            ) == ["enum: foo", "enum: bar"]
        finally:
            await drop_type(connection, type_name)
            await connection.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-TYPE-002")
@pytest.mark.integration
def test_nested_domain_uses_base_codec_and_rejects_custom_domain_codec(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式递归解析 DOMAIN 基类型并保持 domain codec 限制。"""
    async def scenario() -> None:
        base_domain = unique_object_name("domain_base", kes_config.mode)
        nested_domain = unique_object_name("domain_nested", kes_config.mode)
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            await connection.execute(f"CREATE DOMAIN {base_domain} AS INT")
            await connection.execute(
                f"CREATE DOMAIN {nested_domain} AS {base_domain}"
            )

            statement = await connection.prepare(
                f"SELECT $1::{nested_domain} AS domain_value"
            )
            assert await statement.fetchval(7) == 7
            attribute = statement.get_attributes()[0]
            expected_type = "int" if kes_config.mode == "sqlserver" else "int4"
            assert attribute.type.name == expected_type
            assert attribute.type.kind == "scalar"

            with pytest.raises(
                asynckb.UnsupportedClientFeatureError,
                match="custom codecs on domain types are not supported",
            ):
                await connection.set_type_codec(
                    nested_domain,
                    schema="public",
                    encoder=str,
                    decoder=int,
                    format="text",
                )
        finally:
            await drop_domain(connection, nested_domain)
            await drop_domain(connection, base_domain)
            await connection.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-TYPE-003")
@pytest.mark.integration
def test_composite_mapping_round_trip_after_schema_cache_reload(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式 COMPOSITE 映射编解码及 schema cache 重载可用。"""
    async def scenario() -> None:
        type_name = unique_object_name("composite_type", kes_config.mode)
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            await connection.execute(
                f"CREATE TYPE {type_name} AS (id INT, label TEXT)"
            )
            value = await connection.fetchval(
                f"SELECT $1::{type_name}", {"id": 1, "label": "first"}
            )
            assert tuple(value) == (1, "first")

            await connection.reload_schema_state()
            statement = await connection.prepare(
                f"SELECT $1::{type_name} AS composite_value"
            )
            value = await statement.fetchval({"id": 2, "label": "second"})
            assert tuple(value) == (2, "second")
            attribute = statement.get_attributes()[0]
            assert attribute.type.name == type_name
            assert attribute.type.kind == "composite"
        finally:
            await drop_type(connection, type_name)
            await connection.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-TYPE-004")
@pytest.mark.integration
def test_range_codec_round_trip_and_invalid_input(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式 RANGE codec 保持边界归一化并拒绝非法输入。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            value = await connection.fetchval(
                "SELECT $1::int4range", (1, 9)
            )
            assert value == asynckb.Range(1, 10)

            unbounded = await connection.fetchval(
                "SELECT $1::int4range", (None, 2)
            )
            assert unbounded == asynckb.Range(None, 3)

            with pytest.raises(asynckb.DataError, match="expected 0, 1 or 2"):
                await connection.fetchval(
                    "SELECT $1::int4range", (1, 2, 3)
                )
        finally:
            await connection.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-TYPE-005")
@pytest.mark.integration
def test_sqlserver_sql_variant_uses_text_representation(
    sqlserver_config: KESConfig,
) -> None:
    """测试点：SQL_VARIANT 的异构值以文本形式返回并可绑定字符串。"""
    async def scenario() -> None:
        connection = await asynckb.connect(
            **sqlserver_config.connection_kwargs()
        )
        try:
            values = await connection.fetchrow(
                "SELECT CAST(42 AS sys.sql_variant) AS numeric_value, "
                "CAST('hello' AS sys.sql_variant) AS text_value"
            )
            assert tuple(values) == ("42", "hello")
            assert await connection.fetchval(
                "SELECT CAST($1 AS sys.sql_variant)", "bound-value"
            ) == "bound-value"
        finally:
            await connection.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-TYPE-006")
@pytest.mark.integration
def test_standard_asynckb_scalar_array_and_network_codecs(
    kes_config: KESConfig,
) -> None:
    """测试点：原 asynckb 标量、UUID、二进制、数组、JSONB 和网络 codec 正常。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**kes_config.connection_kwargs())
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
            assert tuple(row[:11]) == values[:11]
            assert isinstance(row[11], str)
            assert json.loads(row[11]) == {"a": 1}
            assert tuple(row[12:]) == values[12:]
        finally:
            await connection.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-TYPE-007")
@pytest.mark.integration
def test_oracle_nested_transaction_uses_session_default_isolation(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle 隐式外层事务按会话 SERIALIZABLE 校验嵌套隔离级别。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**oracle_config.connection_kwargs(
            server_settings={
                "default_transaction_isolation": "serializable",
            }))
        try:
            async with connection.transaction():
                async with connection.transaction(isolation="serializable"):
                    assert await connection.fetchval(
                        "SHOW transaction_isolation") == "serializable"

                with pytest.raises(
                    asynckb.InterfaceError,
                    match="current 'read_committed' != outer 'serializable'",
                ):
                    async with connection.transaction(
                        isolation="read_committed"
                    ):
                        pass
        finally:
            await connection.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-TYPE-008")
@pytest.mark.integration
def test_mysql_custom_codec_reset_restores_kes_default(
    mysql_config: KESConfig,
) -> None:
    """测试点：MySQL 专有类型的自定义 codec 重置后恢复 KES 默认 codec。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**mysql_config.connection_kwargs())
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
@pytest.mark.case_id("KB-TYPE-009")
@pytest.mark.integration
def test_oracle_custom_codec_reset_restores_kes_default(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle 专有类型的自定义 codec 重置后恢复 KES 默认 codec。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**oracle_config.connection_kwargs())
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
@pytest.mark.case_id("KB-TYPE-010")
@pytest.mark.integration
def test_kes_builtin_codec_rejects_incompatible_binary_wire_format(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式文本 wire 类型拒绝错误 binary builtin 且连接可复用。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**kes_config.connection_kwargs())
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
                        asynckb.UnsupportedClientFeatureError,
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
@pytest.mark.case_id("KB-TYPE-011")
@pytest.mark.integration
def test_oracle_standard_date_tuple_codec_maps_to_timestamp_oid(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle DATE codec 映射实际 TIMESTAMP OID 并保留 PG date tuple。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**oracle_config.connection_kwargs())
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
@pytest.mark.case_id("KB-TYPE-012")
@pytest.mark.integration
def test_mysql_standard_json_codec_name_maps_to_kes_json(
    mysql_config: KESConfig,
) -> None:
    """测试点：标准 pg_catalog.json codec API 映射到 KES MySQL JSON。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**mysql_config.connection_kwargs())
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
                asynckb.DataError,
                match="a bytes-like object is required",
            ):
                await connection.fetchval("SELECT $1::json", data)

            await connection.reset_type_codec("json", schema="pg_catalog")
            assert await connection.fetchval("SELECT '{}'::json") == "{}"
            with pytest.raises(
                asynckb.DataError,
                match="expected str, got int",
            ):
                await connection.fetchval("SELECT $1::json", 1)
        finally:
            await connection.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-TYPE-013")
@pytest.mark.integration
def test_mysql_builtin_json_codec_updates_domain_and_base_type(
    mysql_config: KESConfig,
) -> None:
    """测试点：MySQL JSON builtin codec 同步更新 domain 及其基类型。"""
    async def scenario() -> None:
        connection = await asynckb.connect(
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
@pytest.mark.case_id("KB-TYPE-014")
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
@pytest.mark.integration
def test_mysql_standard_codec_name_maps_to_kes_type(
    mysql_config: KESConfig,
    typename: str,
    query: str,
) -> None:
    """测试点：MySQL 标准日期时间和 BIT codec 名称映射到实际 KES OID。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**mysql_config.connection_kwargs())
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
@pytest.mark.case_id("KB-TYPE-015")
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
@pytest.mark.integration
def test_mysql_standard_temporal_tuple_codec_maps_to_kes_text_protocol(
    mysql_config: KESConfig,
    typename: str,
    value: tuple[int],
    expected_text: str,
) -> None:
    """测试点：标准时间 tuple codec 保留 PG epoch 语义并适配 KES 文本协议。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**mysql_config.connection_kwargs())
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
@pytest.mark.case_id("KB-TYPE-016")
@pytest.mark.integration
def test_mysql_timestamp_accepts_date_and_rejects_invalid_input(
    mysql_config: KESConfig,
) -> None:
    """测试点：MySQL TIMESTAMP 接受 date，拒绝字符串和带时区时间。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**mysql_config.connection_kwargs())
        try:
            assert await connection.fetchval(
                "SELECT $1::timestamp", datetime.date(2025, 1, 2)
            ) == datetime.datetime(2025, 1, 2)
            with pytest.raises(
                asynckb.DataError,
                match="expected a datetime.date",
            ):
                await connection.fetchval("SELECT $1::timestamp", "invalid")
            with pytest.raises(
                asynckb.DataError,
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
@pytest.mark.case_id("KB-TYPE-017")
@pytest.mark.integration
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
        connection = await asynckb.connect(**mysql_config.connection_kwargs())
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
@pytest.mark.case_id("KB-TYPE-018")
@pytest.mark.integration
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
        connection = await asynckb.connect(**oracle_config.connection_kwargs())
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
@pytest.mark.case_id("KB-TYPE-019")
@pytest.mark.integration
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
        connection = await asynckb.connect(
            **sqlserver_config.connection_kwargs()
        )
        try:
            await connection.execute(
                f"CREATE TABLE {table} (id INT PRIMARY KEY, flag BIT, "
                "tiny TINYINT, amount MONEY, event_date DATE, "
                "event_time TIME(6), created DATETIME2(6), "
                "legacy DATETIME, rounded SMALLDATETIME, "
                "identifier UNIQUEIDENTIFIER, fixed NCHAR(4), "
                "label NVARCHAR(30), payload VARBINARY(10))"
            )
            await connection.execute(
                f"INSERT INTO {table} (id, flag, tiny, amount, event_date, "
                "event_time, created, legacy, rounded, identifier, fixed, "
                "label, payload) VALUES ("
                "$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
                *values,
            )
            row = await connection.fetchrow(f"SELECT * FROM {table}")
            assert tuple(row) == values[:10] + ("ab  ",) + values[11:]
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-TYPE-020")
@pytest.mark.integration
def test_sqlserver_rowversion_database_support(sqlserver_config: KESConfig) -> None:
    """测试点：临时业务数据库中的 ROWVERSION 返回 8 字节并随更新变化。"""
    async def scenario() -> None:
        admin = await asynckb.connect(
            **sqlserver_config.connection_kwargs(database="master")
        )
        database = unique_object_name("rowversion_db", "sqlserver")
        table = unique_object_name("rowversion", "sqlserver")
        connection = None
        created = False
        try:
            await admin.execute(f"CREATE DATABASE {_quote_ident(database)}")
            created = True
            connection = await asynckb.connect(
                **sqlserver_config.connection_kwargs(database=database)
            )
            await connection.execute(
                f"CREATE TABLE {table}(id INT, rv ROWVERSION)"
            )
            await connection.execute(f"INSERT INTO {table}(id) VALUES (1)")
            value = await connection.fetchval(f"SELECT rv FROM {table}")
            assert isinstance(value, bytes)
            assert len(value) == 8
            await connection.execute(f"UPDATE {table} SET id=2 WHERE id=1")
            updated = await connection.fetchval(
                f"SELECT rv FROM {table} WHERE id=2"
            )
            assert isinstance(updated, bytes)
            assert len(updated) == 8
            assert updated != value
        finally:
            try:
                if connection is not None:
                    await connection.close()
                if created:
                    await admin.execute(
                        f"DROP DATABASE {_quote_ident(database)}"
                    )
            finally:
                await admin.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-TYPE-022")
@pytest.mark.integration
def test_mysql_unsigned_enum_set_and_binary_types_round_trip(
    mysql_config: KESConfig,
) -> None:
    """测试点：MySQL 无符号整数边界、ENUM/SET 及含零字节二进制类型正常。"""
    async def scenario() -> None:
        table = unique_object_name("mysql_native", mysql_config.mode)
        connection = await asynckb.connect(
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
                with pytest.raises(asynckb.NumericValueOutOfRangeError):
                    await connection.execute(
                        f"INSERT INTO {table} (u4, u8) VALUES ($1, $2)",
                        u4,
                        u8,
                    )

            for invalid_binary in (3, [65, 66]):
                with pytest.raises(
                    asynckb.DataError,
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
                asynckb.DataError,
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
@pytest.mark.case_id("KB-TYPE-023")
@pytest.mark.integration
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
        connection = await asynckb.connect(
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
                asynckb.DataError,
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
                asynckb.DataError,
                match="expected str, got int",
            ):
                await locator_statement.fetchrow(123)
            with pytest.raises(
                asynckb.DataError,
                match="expected str, got int",
            ):
                await connection.fetchval(
                    "SELECT $1::yminterval FROM dual", 123
                )
        finally:
            try:
                await connection.execute(f"DROP DIRECTORY {directory}")
            except asynckb.PostgresError:
                pass
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())
@pytest.mark.case_id("KB-TYPE-025")
@pytest.mark.integration
def test_oracle_types_and_supported_transaction_isolation(
    oracle_config: KESConfig,
) -> None:
    """测试点：Oracle INTERVAL 编解码、READ COMMITTED 和 SERIALIZABLE 事务。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**oracle_config.connection_kwargs())
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
@pytest.mark.case_id("KB-TYPE-026")
@pytest.mark.integration
def test_supported_readonly_transactions_reject_writes_and_recover(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式只读事务在支持的隔离级别下拒绝写入，回滚后连接可复用。"""
    async def scenario() -> None:
        table = unique_object_name("readonly", kes_config.mode)
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            await connection.execute(f"CREATE TABLE {table} (id INTEGER)")

            for isolation in (None, "read_committed", "serializable"):
                with pytest.raises(asynckb.ReadOnlySQLTransactionError):
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
@pytest.mark.case_id("KB-TYPE-027")
@pytest.mark.integration
def test_server_errors_map_to_driver_subclasses_and_preserve_connection(
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
        connection = await asynckb.connect(**kes_config.connection_kwargs())

        async def assert_error(
            error_type: type[asynckb.PostgresError],
            sqlstate: str,
            query: str,
        ) -> asynckb.PostgresError:
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
                asynckb.UniqueViolationError,
                "23505",
                f"INSERT INTO {child_table} VALUES (2, 10, 1, 1)",
            )
            await assert_error(
                asynckb.CheckViolationError,
                "23514",
                f"INSERT INTO {child_table} VALUES (2, 20, -1, 1)",
            )
            await assert_error(
                asynckb.ForeignKeyViolationError,
                "23503",
                f"INSERT INTO {child_table} VALUES (2, 20, 1, 999)",
            )
            await assert_error(
                asynckb.PostgresSyntaxError,
                "42601",
                "SELEC 1",
            )
            await assert_error(
                asynckb.UndefinedTableError,
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
@pytest.mark.case_id("KB-TYPE-030")
@pytest.mark.integration
def test_schema_reload_and_statement_expiry_preserve_kes_codecs(
    kes_config: KESConfig,
) -> None:
    """测试点：Schema cache reload 和 statement TTL 到期后 KES codec 仍可用。"""
    async def scenario() -> None:
        connection = await asynckb.connect(
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
@pytest.mark.case_id("KB-TYPE-031")
@pytest.mark.unit
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
@pytest.mark.case_id("KB-TYPE-032")
@pytest.mark.unit
def test_sqlserver_datetime2_default_precision_decodes_to_microseconds(
) -> None:
    """测试点：SQL Server DATETIME2(7) 截取为 Python 六位微秒精度。"""
    assert kes._decode_datetime(
        "2026-01-02 03:04:05.1234567"
    ) == datetime.datetime(2026, 1, 2, 3, 4, 5, 123456)
@pytest.mark.case_id("KB-TYPE-033")
@pytest.mark.unit
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
@pytest.mark.case_id("KB-TYPE-035")
@pytest.mark.unit
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
@pytest.mark.case_id("KB-TYPE-036")
@pytest.mark.unit
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

@pytest.mark.case_id("KB-TYPE-038")
@pytest.mark.unit
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

    with pytest.raises(asynckb.ClientConfigurationError):
        kes.register_codecs(FailingSettings(), [], "oracle")




@pytest.mark.case_id("KB-TYPE-041")
@pytest.mark.integration
@pytest.mark.parametrize(("sql_type", "value"), [
    ("SMALLINT", -32768),
    ("INT", 2147483647),
    ("BIGINT", 9223372036854775807),
    ("NUMERIC(20,4)", Decimal("123456789.1250")),
    ("REAL", 1.25),
    ("FLOAT", 2.5),
    ("BIT", True),
    ("TINYINT", 255),
    ("DATE", datetime.date(2026, 11, 9)),
    ("TIME", datetime.time(12, 30, 45)),
    ("DATETIME2", datetime.datetime(2026, 11, 9, 12, 30, 45)),
    ("UNIQUEIDENTIFIER", uuid.UUID("12345678-1234-5678-1234-567812345678")),
    ("NVARCHAR(30)", "中文类型测试"),
    ("NTEXT", "中文类型测试"),
    ("MONEY", Decimal("123.4500")),
    ("SMALLMONEY", Decimal("12.3400")),
    ("BINARY(5)", b"\x00\xffabc"),
    ("VARBINARY(8)", b"\x00\xffabc"),
    ("IMAGE", b"\x00\xffabc"),
])
def test_sqlserver_execution_row_descriptions_preserve_python_types(
    sqlserver_config: KESConfig, sql_type: str, value: object,
) -> None:
    """Text result messages must not turn typed values into strings."""
    async def scenario():
        con = await asynckb.connect(**sqlserver_config.connection_kwargs())
        try:
            statement = await con.prepare(
                f"SELECT CAST($1 AS {sql_type}) AS value; "
                f"SELECT CAST($1 AS {sql_type}) AS value")
            for argument in (value, None, value):
                rows = await statement.fetch(argument)
                assert [tuple(row) for row in rows] == [(argument,), (argument,)]
                if argument is not None:
                    assert all(type(row[0]) is type(value) for row in rows)
        finally:
            await con.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-TYPE-042")
@pytest.mark.integration
@pytest.mark.parametrize(("sql_type", "value"), [
    ("SMALLINT", -32768),
    ("INT", 2147483647),
    ("BIGINT", 9223372036854775807),
    ("NUMERIC(20,4)", Decimal("123456789.1250")),
    ("REAL", 1.25),
    ("FLOAT", 2.5),
    ("TEXT", "large text"),
    ("NTEXT", "中文类型测试"),
    ("SYSNAME", "object_name"),
    ("IMAGE", b"\x00\xffabc"),
    ("XML", "<root>value</root>"),
])
def test_sqlserver_native_scalar_types_round_trip_and_reset(
    sqlserver_config: KESConfig, sql_type: str, value: object,
) -> None:
    """New KES system types retain Python values and restore default codecs."""
    async def scenario() -> None:
        connection = await asynckb.connect(**sqlserver_config.connection_kwargs())
        query = f"SELECT CAST($1 AS {sql_type})"
        try:
            statement = await connection.prepare(query)
            parameter = statement.get_parameters()[0]
            actual = await statement.fetchval(value)
            assert actual == value
            assert type(actual) is type(value)
            assert await statement.fetchval(None) is None
            if parameter.schema == "sys":
                await connection.reset_type_codec(
                    parameter.name, schema=parameter.schema)
                assert await connection.fetchval(query, value) == value
        finally:
            await connection.close()

    asyncio.run(scenario())
