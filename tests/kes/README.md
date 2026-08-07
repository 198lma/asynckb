# KingbaseES test suite

This directory contains the complete test suite for the adapted asyncpg
driver. Tests target only the KingbaseES MySQL, Oracle, and SQL Server
compatibility modes.

## Structure

| Directory | Responsibility |
| --- | --- |
| `unit` | Driver internals that do not require a database |
| `integration/api` | Public `Connection`, `Record`, cursor, and pool APIs |
| `integration/connection` | Connection options, contracts, and statement lifecycle |
| `integration/pool` | Pool cancellation, recovery, concurrency, and shutdown |
| `integration/protocol` | Handshake, COPY, notifications, caches, and timeout races |
| `integration/schema` | Schema and database object operations |
| `integration/types` | KES type matrices, codecs, transactions, and errors |
| `integration/workflows` | Readable end-to-end asynchronous business workflows |
| `framework` | SQLAlchemy and Alembic integration |
| `support` | Shared configuration and framework helpers |

Every test function has one responsibility and starts its docstring with
`测试点：`. Mode-independent tests use `kes_config`; mode-specific behavior
uses `mysql_config`, `oracle_config`, or `sqlserver_config`.

Native asynchronous workflow tests are declared with `async def` and the
`pytest.mark.asyncio` marker. Lower-level regression tests may retain an
explicit `asyncio.run()` wrapper when event-loop ownership is itself part of
the contract under test.

## Commands

```bash
./run_kes_tests.sh unit -q
ASYNCPG_KES_PASSWORD='<password>' ./run_kes_tests.sh integration -q
ASYNCPG_KES_PASSWORD='<password>' ./run_kes_tests.sh framework -q
ASYNCPG_KES_PASSWORD='<password>' ./run_kes_tests.sh all -q
```
