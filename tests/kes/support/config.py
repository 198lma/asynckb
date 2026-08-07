from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from urllib.parse import quote

import asyncpg


@dataclass(frozen=True)
class KESConfig:
    mode: str
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str

    @classmethod
    def from_env(cls, mode: str) -> "KESConfig":
        if mode not in {"mysql", "oracle", "sqlserver"}:
            raise ValueError(f"unsupported KES mode: {mode}")

        password = os.environ.get("ASYNCPG_KES_PASSWORD")
        if not password:
            raise RuntimeError(
                "ASYNCPG_KES_PASSWORD must be set for integration tests"
            )

        port_name = f"ASYNCPG_KES_{mode.upper()}_PORT"
        default_ports = {
            "mysql": 54321,
            "oracle": 54322,
            "sqlserver": 54323,
        }
        return cls(
            mode=mode,
            host=os.environ.get("ASYNCPG_KES_HOST", "127.0.0.1"),
            port=int(os.environ.get(port_name, default_ports[mode])),
            user=os.environ.get("ASYNCPG_KES_USER", "system"),
            password=password,
            database=os.environ.get("ASYNCPG_KES_DATABASE", "test"),
        )

    def connection_kwargs(self, **overrides: object) -> dict[str, object]:
        options: dict[str, object] = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "kes_mode": self.mode,
            "ssl": False,
            "timeout": 5,
        }
        options.update(overrides)
        return options

    def dsn(self, dialect: str | None = None) -> str:
        scheme = f"kingbase_{dialect}+asyncpg" if dialect else "postgresql"
        user = quote(self.user, safe="")
        password = quote(self.password, safe="")
        database = quote(self.database, safe="")
        mode_query = f"?kes_mode={self.mode}&sslmode=disable"
        return (
            f"{scheme}://{user}:{password}@{self.host}:{self.port}/"
            f"{database}{mode_query if dialect is None else ''}"
        )

    @property
    def select_one(self) -> str:
        if self.mode == "oracle":
            return "SELECT 1 FROM dual"
        return "SELECT 1"

    def cast_integer(self, placeholder: str) -> str:
        if self.mode == "oracle":
            return f"SELECT CAST({placeholder} AS NUMBER) FROM dual"
        return f"SELECT CAST({placeholder} AS SIGNED)"

    def array_type(self, type_name: str, *, schema: str | None = None) -> str:
        if self.mode == "sqlserver":
            namespace = schema or "pg_catalog"
            internal_name = {
                "integer": "_int4",
                "text": "_text",
            }.get(type_name, f"_{type_name}")
            return f"{namespace}.{internal_name}"
        qualified_name = f"{schema}.{type_name}" if schema else type_name
        return f"{qualified_name}[]"

    def create_users_table(self, table: str) -> str:
        if self.mode == "oracle":
            return (
                f"CREATE TABLE {table} ("
                "id NUMBER(10) PRIMARY KEY, "
                "username VARCHAR2(50) NOT NULL UNIQUE, "
                "age NUMBER(3), note CLOB)"
            )
        return (
            f"CREATE TABLE {table} ("
            "id INT PRIMARY KEY, "
            "username VARCHAR(50) NOT NULL UNIQUE, "
            "age INT, note TEXT)"
        )

    def create_copy_table(self, table: str) -> str:
        if self.mode == "oracle":
            columns = (
                "id NUMBER(10), label VARCHAR2(50), payload BLOB"
            )
        else:
            columns = "id INT, label VARCHAR(50), payload VARBINARY(50)"
        return f"CREATE TABLE {table} ({columns})"


def unique_object_name(prefix: str, mode: str) -> str:
    token = uuid.uuid4().hex[:8]
    return f"apg_{prefix}_{mode}_{token}"


async def drop_table(connection: asyncpg.Connection, table: str) -> None:
    try:
        await connection.execute(f"DROP TABLE {table}")
    except asyncpg.UndefinedTableError:
        pass
