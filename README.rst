asyncpg with KingbaseES compatibility modes
============================================

.. image:: https://github.com/198lma/asyncpg-kes/actions/workflows/tests.yml/badge.svg
   :target: https://github.com/198lma/asyncpg-kes/actions/workflows/tests.yml
   :alt: CI status

This repository extends asyncpg 0.31.0 with KingbaseES MySQL, Oracle, and SQL
Server compatibility-mode support.  It keeps asyncpg's asyncio transport,
PostgreSQL Wire Protocol implementation, prepared statements, codecs,
transactions, cursors, and connection pool.  It does not load ``libkci`` and
does not contain a separate ``asynckes`` driver.

The runtime path is::

    asyncio application / SQLAlchemy AsyncEngine
        -> asyncpg Connection / Pool
        -> asyncpg Cython protocol and codecs
        -> PostgreSQL Wire Protocol
        -> KingbaseES MySQL, Oracle, or SQL Server compatibility mode

KES-specific code is limited to mode validation, dynamic KES type-codec
registration, mode transaction syntax, small protocol-behavior corrections,
and SQLAlchemy MySQL/Oracle/SQL Server dialects.  The current implementation
uses the original asyncpg COPY and LISTEN/NOTIFY protocol paths.

Installation
------------

Python 3.9 or later is required.  SQLAlchemy support is optional::

    python -m pip install 'asyncpg-kes[sqlalchemy]'

The distribution name is ``asyncpg-kes`` and the import name remains
``asyncpg`` for API compatibility.  Do not install ``asyncpg`` and
``asyncpg-kes`` into the same environment because both provide the
``asyncpg`` Python package.

Basic usage
-----------

.. code-block:: python

    import asyncio
    import asyncpg

    async def main():
        connection = await asyncpg.connect(
            host="127.0.0.1",
            port=54321,
            user="system",
            password="password",
            database="test",
            ssl=False,
        )
        try:
            row = await connection.fetchrow(
                "SELECT CAST($1 AS INT) AS id, "
                "CAST($2 AS VARCHAR(30)) AS name", 1, "KES"
            )
            print(row["id"], row["name"])
        finally:
            await connection.close()

    asyncio.run(main())

The driver runs ``SHOW DATABASE_MODE`` after authentication and automatically
selects the corresponding KES compatibility mode.  The detected mode is
available through ``connection.get_kes_mode()``.  Passing
``kes_mode="mysql"``, ``kes_mode="oracle"`` or ``kes_mode="sqlserver"`` is
optional and enables an explicit mode check when required.

Connection service files may also declare the KES compatibility mode::

    [kes]
    host=127.0.0.1
    port=54321
    user=system
    dbname=test
    sslmode=disable
    kes_mode=mysql

The service can then be selected explicitly with
``asyncpg.connect(service="kes", servicefile="/path/to/pg_service.conf")``
or through the standard ``PGSERVICE`` and ``PGSERVICEFILE`` environment
variables.  An explicit ``kes_mode`` argument takes precedence over the
service-file value.

SQLAlchemy
----------

The package registers three SQLAlchemy 2.x asynchronous dialects::

    kingbase_mysql+asyncpg://user:password@host:54321/database
    kingbase_oracle+asyncpg://user:password@host:54322/database
    kingbase_sqlserver+asyncpg://user:password@host:54323/database

Standard asyncpg connection options can be supplied in the URL.  For example,
the following disables TLS negotiation, disables SQLAlchemy's prepared
statement cache, and sets the default command timeout::

    kingbase_mysql+asyncpg://user:password@host:54321/database?sslmode=disable&prepared_statement_cache_size=0&command_timeout=5

Repeated ``host=address:port`` query parameters enable asyncpg multi-host
fallback.  Numeric cache and timeout values and the ``direct_tls`` boolean are
converted to their native Python types by the dialect.

These dialects use mode-specific SQL compilers and provide KES catalog
reflection for tables, views, columns, primary keys, foreign keys, unique
constraints, check constraints, and indexes.

Compatibility boundaries
------------------------

The KES MySQL, Oracle, and SQL Server instances have been verified with text,
CSV, and binary COPY, LISTEN/NOTIFY, prepared statements, cursors,
transactions, cancellation, connection pooling, and dynamic KES codecs.  The Oracle
SQLAlchemy dialect additionally supports identity and computed columns,
sequences, streamed results, single-row INSERT/UPDATE/DELETE RETURNING, and
KES catalog reflection for constraints, comments, and indexes.

The KES SQL Server mode supports identity columns, streamed results,
INSERT/UPDATE/DELETE RETURNING, nested transactions, native comments, and KES
catalog reflection.  The tested V009R001C010 server does not support computed
column syntax, so that server capability is not advertised by this dialect.

SQL passed directly to asyncpg is not translated.  Applications must use SQL
for the active KES compatibility mode.  The ``kingbase_mysql+asyncpg``
SQLAlchemy dialect provides MySQL quoting, ``AUTO_INCREMENT``,
``LIMIT/OFFSET``, ``ON DUPLICATE KEY UPDATE``, string concatenation,
``LAST_INSERT_ID()``, and KES MySQL catalog reflection.  The
``kingbase_oracle+asyncpg`` dialect uses SQLAlchemy's Oracle compiler.
PostgreSQL-specific SQL semantics such as ``||`` string concatenation or
transactional DDL are intentionally not emulated by the driver.

KES compatibility types registered with a text wire codec cannot be aliased
to a PostgreSQL binary builtin codec.  For those types,
``set_builtin_type_codec()`` requires ``format='text'``; use
``set_type_codec()`` when custom Python conversion is needed.  This prevents
silent timestamp shifts and binary JSON marker leakage in KES MySQL mode.

KES Oracle mode returns rows for ``RETURNING`` without an Oracle ``INTO``
clause.  The dialect compiles SQLAlchemy RETURNING to that form and maps
SQLAlchemy executemany RETURNING to asyncpg's ``PreparedStatement.fetchmany()``.
Oracle-style OUT bind variables remain outside asyncpg's API; regular and
batched RETURNING provide the equivalent DML result path supported by KES.
The tested Oracle-mode server rejects extended-protocol parameters in
``CALL`` statements, although literal ``CALL`` statements work.  It also does
not expose ``VARBINARY``; use the supported ``BLOB`` or ``BYTEA`` types for
binary data.

The tested MySQL-mode server can infer an untyped placeholder as ``text`` in
some expressions.  Use an explicit mode type such as ``CAST($1 AS INT)`` when
the surrounding expression does not determine the intended parameter type.

Calling ``connect()`` without ``kes_mode`` preserves the upstream connection
API.  After authentication, the driver probes ``SHOW DATABASE_MODE`` and
automatically initializes the matching KingbaseES compatibility mode.  If the
server does not support that KES command, the connection remains on the
standard PostgreSQL path.  Passing ``kes_mode`` is still supported when an
application needs an explicit mode check.

Testing against KES
-------------------

All regression tests in this repository target KingbaseES and are maintained
directly in ``tests/kes``.  The upstream PostgreSQL-only suite has been
replaced by tests for the three supported KES compatibility modes.

Set the password and run all three compatibility modes::

    ASYNCPG_KES_PASSWORD=password ./run_kes_tests.sh all -q

Run a specific layer or compatibility mode with::

    ./run_kes_tests.sh unit -q
    ASYNCPG_KES_PASSWORD=password \
        ./run_kes_tests.sh integration --kes-mode mysql -q
    ASYNCPG_KES_PASSWORD=password ./run_kes_tests.sh framework -q

The suite covers the portable asyncpg API, KES-specific behavior, SQLAlchemy,
and Alembic against MySQL, Oracle, and SQL Server compatibility modes.  The
default local endpoints are ports 54321, 54322, and 54323 respectively; all
connection settings can be overridden with ``ASYNCPG_KES_*`` environment
variables documented in ``docs/kes-testing/TEST_PLAN.md``.

License
-------

Apache License 2.0.

Project policies
----------------

See `CHANGELOG.md <CHANGELOG.md>`_, `CONTRIBUTING.md <CONTRIBUTING.md>`_,
`SECURITY.md <SECURITY.md>`_, `UPSTREAM.md <UPSTREAM.md>`_, and
`docs/DELIVERY.md <docs/DELIVERY.md>`_.
