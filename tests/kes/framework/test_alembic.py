"""Framework tests for Alembic migrations through both KES dialects."""

from __future__ import annotations

import asyncio

import pytest

from tests.kes.support.config import KESConfig, unique_object_name
from tests.kes.support.sqlalchemy_support import register_kes_dialects

pytestmark = [pytest.mark.integration, pytest.mark.framework]
pytest.importorskip("alembic")
pytest.importorskip("sqlalchemy")


def test_alembic_autogenerate_and_operations_round_trip(
    kes_config: KESConfig,
) -> None:
    """测试点：三个 KES 方言均支持 Alembic 比对、建列、索引、删列和删表。"""

    async def scenario() -> None:
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import (
            Column,
            Computed,
            Identity,
            Integer,
            MetaData,
            Numeric,
            String,
            Table,
            inspect,
        )
        from sqlalchemy.ext.asyncio import create_async_engine

        register_kes_dialects()
        for config in (kes_config,):
            engine = create_async_engine(config.dsn(config.mode))
            metadata = MetaData()
            table_name = unique_object_name("alembic", config.mode)
            migration_name = unique_object_name("migration", config.mode)
            index_name = unique_object_name("index", config.mode)
            if config.mode == "oracle":
                id_column = Column("id", Integer, Identity(), primary_key=True)
            else:
                id_column = Column(
                    "id", Integer, primary_key=True, autoincrement=True
                )
            doubled_column = (
                Column("doubled", Numeric(10, 2))
                if config.mode == "sqlserver"
                else Column(
                    "doubled", Numeric(10, 2), Computed("amount * 2")
                )
            )
            Table(
                table_name,
                metadata,
                id_column,
                Column("name", String(30), nullable=False),
                Column("amount", Numeric(10, 2)),
                doubled_column,
            )
            try:
                async with engine.begin() as connection:
                    await connection.run_sync(
                        metadata.drop_all, checkfirst=True
                    )
                    await connection.run_sync(metadata.create_all)

                async with engine.connect() as connection:

                    def compare(sync_connection):
                        def include_name(name, type_, parent_names):
                            return type_ != "table" or name == table_name

                        context = MigrationContext.configure(
                            sync_connection,
                            opts={"include_name": include_name},
                        )
                        return compare_metadata(context, metadata)

                    assert await connection.run_sync(compare) == []

                async with engine.begin() as connection:
                    await connection.exec_driver_sql(
                        f"DROP TABLE IF EXISTS {migration_name}"
                    )

                    def upgrade(sync_connection):
                        operations = Operations(
                            MigrationContext.configure(sync_connection)
                        )
                        operations.create_table(
                            migration_name,
                            Column("id", Integer, primary_key=True),
                            Column("name", String(20)),
                        )
                        operations.add_column(
                            migration_name, Column("note", String(30))
                        )
                        operations.create_index(
                            index_name, migration_name, ["name"]
                        )
                        return [
                            column["name"]
                            for column in inspect(sync_connection).get_columns(
                                migration_name
                            )
                        ]

                    assert await connection.run_sync(upgrade) == [
                        "id",
                        "name",
                        "note",
                    ]

                async with engine.begin() as connection:

                    def downgrade(sync_connection):
                        operations = Operations(
                            MigrationContext.configure(sync_connection)
                        )
                        operations.drop_index(
                            index_name, table_name=migration_name
                        )
                        operations.drop_column(migration_name, "note")
                        columns = [
                            column["name"]
                            for column in inspect(sync_connection).get_columns(
                                migration_name
                            )
                        ]
                        operations.drop_table(migration_name)
                        return columns

                    assert await connection.run_sync(downgrade) == [
                        "id",
                        "name",
                    ]
            finally:
                async with engine.begin() as connection:
                    await connection.exec_driver_sql(
                        f"DROP TABLE IF EXISTS {migration_name}"
                    )
                    await connection.run_sync(
                        metadata.drop_all, checkfirst=True
                    )
                await engine.dispose()

    asyncio.run(scenario())
