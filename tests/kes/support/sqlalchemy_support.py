"""SQLAlchemy registration helpers for the KES integration suite."""


def register_kes_dialects() -> None:
    """Register the local asyncpg KES dialect entry points."""
    from sqlalchemy.dialects import registry

    registry.register(
        "kingbase_mysql.asyncpg",
        "asyncpg.sa_dialect",
        "KESMySQLDialect_asyncpg",
    )
    registry.register(
        "kingbase_oracle.asyncpg",
        "asyncpg.sa_dialect",
        "KESOracleDialect_asyncpg",
    )
    registry.register(
        "kingbase_sqlserver.asyncpg",
        "asyncpg.sa_dialect",
        "KESSQLServerDialect_asyncpg",
    )
