"""Integration tests for KES enum, domain, composite, and range types."""

from __future__ import annotations

import asyncio

import asyncpg
import pytest

from tests.kes.support.config import KESConfig, unique_object_name


pytestmark = pytest.mark.integration


async def drop_type(connection: asyncpg.Connection, type_name: str) -> None:
    try:
        await connection.execute(f"DROP TYPE {type_name}")
    except asyncpg.UndefinedObjectError:
        pass


async def drop_domain(
    connection: asyncpg.Connection,
    domain_name: str,
) -> None:
    try:
        await connection.execute(f"DROP DOMAIN {domain_name}")
    except asyncpg.UndefinedObjectError:
        pass


def test_enum_custom_codec_applies_to_scalar_and_array(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式 ENUM 自定义 codec 同时作用于标量和数组元素。"""
    async def scenario() -> None:
        type_name = unique_object_name("enum_type", kes_config.mode)
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
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


def test_nested_domain_uses_base_codec_and_rejects_custom_domain_codec(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式递归解析 DOMAIN 基类型并保持 domain codec 限制。"""
    async def scenario() -> None:
        base_domain = unique_object_name("domain_base", kes_config.mode)
        nested_domain = unique_object_name("domain_nested", kes_config.mode)
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
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
            assert attribute.type.name == "int4"
            assert attribute.type.kind == "scalar"

            with pytest.raises(
                asyncpg.UnsupportedClientFeatureError,
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


def test_composite_mapping_round_trip_after_schema_cache_reload(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式 COMPOSITE 映射编解码及 schema cache 重载可用。"""
    async def scenario() -> None:
        type_name = unique_object_name("composite_type", kes_config.mode)
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
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


def test_range_codec_round_trip_and_invalid_input(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式 RANGE codec 保持边界归一化并拒绝非法输入。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            value = await connection.fetchval(
                "SELECT $1::int4range", (1, 9)
            )
            assert value == asyncpg.Range(1, 10)

            unbounded = await connection.fetchval(
                "SELECT $1::int4range", (None, 2)
            )
            assert unbounded == asyncpg.Range(None, 3)

            with pytest.raises(asyncpg.DataError, match="expected 0, 1 or 2"):
                await connection.fetchval(
                    "SELECT $1::int4range", (1, 2, 3)
                )
        finally:
            await connection.close()

    asyncio.run(scenario())
