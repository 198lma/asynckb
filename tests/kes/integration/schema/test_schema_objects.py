"""Integration tests for objects in pre-created KES schemas."""

from __future__ import annotations

import asyncio

import asyncpg
import pytest

from tests.kes.support.config import KESConfig, drop_table, unique_object_name


pytestmark = pytest.mark.integration

TEST_SCHEMA = "asynckes"


def test_create_and_use_table_in_asynckes_schema(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式均可在已有 asynckes schema 中创建并使用表。"""

    async def scenario() -> None:
        table_name = unique_object_name("schema_table", kes_config.mode)
        qualified_table = f"{TEST_SCHEMA}.{table_name}"
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        table_created = False
        try:
            schema_exists = await connection.fetchval(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_namespace WHERE lower(nspname) = lower($1)"
                ")",
                TEST_SCHEMA,
            )
            assert schema_exists, (
                f"{TEST_SCHEMA} schema does not exist in the "
                f"{kes_config.mode} KES test database"
            )

            if kes_config.mode == "oracle":
                columns = (
                    "id NUMBER(10) PRIMARY KEY, "
                    "label VARCHAR2(50) NOT NULL"
                )
            else:
                columns = "id INT PRIMARY KEY, label VARCHAR(50) NOT NULL"

            await connection.execute(
                f"CREATE TABLE {qualified_table} ({columns})"
            )
            table_created = True
            await connection.execute(
                f"INSERT INTO {qualified_table} (id, label) VALUES ($1, $2)",
                1,
                f"{kes_config.mode}-schema",
            )

            row = await connection.fetchrow(
                f"SELECT id, label FROM {qualified_table} WHERE id = $1",
                1,
            )
            assert row is not None
            assert tuple(row) == (1, f"{kes_config.mode}-schema")
        finally:
            if table_created:
                await drop_table(connection, qualified_table)
            await connection.close()

    asyncio.run(scenario())
