"""Integration tests for asyncpg connection and pool public APIs on KES."""

from __future__ import annotations

import asyncio
import datetime
import io

import asyncpg
import pytest

from tests.kes.support.config import KESConfig, drop_table, unique_object_name


pytestmark = pytest.mark.integration


class KESRecord(asyncpg.Record):
    @property
    def first_value(self) -> object:
        return self[0]


class KESConnection(asyncpg.Connection):
    def active_mode(self) -> str | None:
        return self.get_kes_mode()


def test_connection_custom_classes_logging_and_prepared_metadata(
    kes_config: KESConfig,
) -> None:
    """测试点：连接/Record 扩展、查询日志、预编译元数据和 EXPLAIN 均可用。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(
            **kes_config.connection_kwargs(
                connection_class=KESConnection,
                record_class=KESRecord,
                server_settings={"application_name": "apg_kes_public_api"},
            )
        )
        query_records: list[asyncpg.connection.LoggedQuery] = []
        suffix = " FROM dual" if kes_config.mode == "oracle" else ""
        try:
            assert connection.active_mode() == kes_config.mode
            assert connection.get_settings().application_name == (
                "apg_kes_public_api")

            with connection.query_logger(query_records.append):
                row = await connection.fetchrow(f"SELECT 42 AS answer{suffix}")
                assert isinstance(row, KESRecord)
                assert row.first_value == 42

                with pytest.raises(asyncpg.UndefinedColumnError):
                    await connection.fetchval(
                        f"SELECT apg_missing_column{suffix}")

            await asyncio.sleep(0)
            assert len(query_records) == 2
            assert query_records[0].exception is None
            assert isinstance(
                query_records[1].exception, asyncpg.UndefinedColumnError)

            statement = await connection.prepare(
                f"SELECT CAST($1 AS INTEGER) AS answer{suffix}")
            attributes = statement.get_attributes()
            assert [(item.name, item.type.name) for item in attributes] == [
                ("answer", "int4")
            ]
            plan = await statement.explain(7)
            assert isinstance(plan, list)
            assert plan and "Plan" in plan[0]
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_connection_reset_log_listener_and_termination_listener(
    kes_config: KESConfig,
) -> None:
    """测试点：服务端日志回调、事务 reset 和连接终止回调保持原 API 语义。"""
    async def scenario() -> None:
        table = unique_object_name("lifecycle", kes_config.mode)
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        notices: list[str] = []
        terminated = asyncio.Event()

        def log_listener(
            _: asyncpg.Connection,
            message: asyncpg.PostgresLogMessage,
        ) -> None:
            notices.append(message.message)

        try:
            id_type = "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            await connection.execute(
                f"CREATE TABLE {table} (id {id_type} PRIMARY KEY)")
            connection.add_log_listener(log_listener)
            await connection.execute(
                "DO $$ BEGIN RAISE NOTICE 'kes-public-api-notice'; END; $$ "
                "LANGUAGE plpgsql")
            await asyncio.sleep(0)
            assert notices == ["kes-public-api-notice"]

            transaction = connection.transaction()
            await transaction.start()
            await connection.execute(f"INSERT INTO {table} VALUES (1)")
            await connection.reset()

            assert connection._top_xact is None
            assert not connection.is_in_transaction()
            assert not connection._log_listeners
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}") == 0

            connection.add_termination_listener(
                lambda _: terminated.set())
        finally:
            await drop_table(connection, table)
            await connection.close()

        await asyncio.wait_for(terminated.wait(), timeout=1)
        assert connection.is_closed()

    asyncio.run(scenario())


def test_pool_reconnect_configuration_and_copy_proxy_methods(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool 连接过期、重连参数及四个 COPY 代理方法均可用。"""
    async def scenario() -> None:
        source_table = unique_object_name("pool_copy_src", kes_config.mode)
        target_table = unique_object_name("pool_copy_dst", kes_config.mode)
        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        pool = await asyncpg.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
        )
        try:
            async with pool.acquire() as connection:
                first_pid = connection.get_server_pid()

            await pool.expire_connections()
            async with pool.acquire() as connection:
                second_pid = connection.get_server_pid()
            assert second_pid != first_pid

            pool.set_connect_args(
                **pool_options,
                server_settings={"application_name": "apg_kes_pool_reconnect"},
            )
            await pool.expire_connections()
            async with pool.acquire() as connection:
                assert connection.get_settings().application_name == (
                    "apg_kes_pool_reconnect")

            id_type = "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            text_type = (
                "VARCHAR2(30)" if kes_config.mode == "oracle"
                else "VARCHAR(30)"
            )
            await pool.execute(
                f"CREATE TABLE {source_table} "
                f"(id {id_type}, label {text_type})")
            await pool.execute(
                f"CREATE TABLE {target_table} "
                f"(id {id_type}, label {text_type})")

            records = [(1, "one"), (2, "two")]
            assert await pool.copy_records_to_table(
                source_table, records=records) == "COPY 2"

            query_output = io.BytesIO()
            assert await pool.copy_from_query(
                f"SELECT id, label FROM {source_table} ORDER BY id",
                output=query_output,
                format="csv",
            ) == "COPY 2"
            assert await pool.copy_to_table(
                target_table,
                source=query_output.getvalue(),
                format="csv",
            ) == "COPY 2"

            table_output = io.BytesIO()
            assert await pool.copy_from_table(
                target_table,
                output=table_output,
                format="csv",
            ) == "COPY 2"
            assert table_output.getvalue() == query_output.getvalue()
            assert [tuple(row) for row in await pool.fetch(
                f"SELECT id, label FROM {target_table} ORDER BY id"
            )] == records
        finally:
            async with pool.acquire() as connection:
                await drop_table(connection, target_table)
                await drop_table(connection, source_table)
            await pool.close()

    asyncio.run(scenario())


def test_pool_can_switch_between_kes_compatibility_modes(
    mysql_config: KESConfig,
    oracle_config: KESConfig,
) -> None:
    """测试点：Pool 更新连接参数后可在两个 KES 模式间重建连接和 codec。"""
    async def scenario() -> None:
        mysql_options = mysql_config.connection_kwargs()
        mysql_options.pop("timeout")
        oracle_options = oracle_config.connection_kwargs()
        oracle_options.pop("timeout")
        pool = await asyncpg.create_pool(
            **mysql_options,
            min_size=1,
            max_size=1,
        )
        try:
            async with pool.acquire() as connection:
                assert connection.get_kes_mode() == "mysql"
                assert await connection.fetchval(
                    "SELECT CAST($1 AS TINYINT)", 7
                ) == 7

            pool.set_connect_args(**oracle_options)
            await pool.expire_connections()
            async with pool.acquire() as connection:
                assert connection.get_kes_mode() == "oracle"
                assert await connection.fetchval(
                    "SELECT INTERVAL '1 00:00:00.123456' "
                    "DAY TO SECOND FROM dual"
                ) == "+01 00:00:00.123456"

            pool.set_connect_args(**mysql_options)
            await pool.expire_connections()
            async with pool.acquire() as connection:
                assert connection.get_kes_mode() == "mysql"
                assert await connection.fetchval(
                    "SELECT CAST('2025-01-02' AS DATE)"
                ) == datetime.date(2025, 1, 2)
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_pool_release_rolls_back_transaction_and_reloads_kes_codecs(
    kes_config: KESConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """测试点：Pool 释放时回滚事务，过期重连后重新注册 KES codec。"""
    async def scenario() -> None:
        table = unique_object_name("pool_reset", kes_config.mode)
        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        pool = await asyncpg.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
        )
        try:
            id_type = "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            await pool.execute(
                f"CREATE TABLE {table} (id {id_type} PRIMARY KEY)"
            )

            connection = await pool.acquire()
            transaction = connection.transaction()
            await transaction.start()
            await connection.execute(f"INSERT INTO {table} VALUES (1)")
            await pool.release(connection)
            assert any(
                "Resetting connection with an active transaction"
                in record.getMessage()
                for record in caplog.records
            )

            async with pool.acquire() as connection:
                assert not connection.is_in_transaction()
                assert await connection.fetchval(
                    f"SELECT count(*) FROM {table}"
                ) == 0
                first_pid = connection.get_server_pid()

            await pool.expire_connections()
            async with pool.acquire() as connection:
                assert connection.get_server_pid() != first_pid
                if kes_config.mode == "mysql":
                    assert await connection.fetchval(
                        "SELECT CAST('2025-01-02' AS DATE)"
                    ) == datetime.date(2025, 1, 2)
                elif kes_config.mode == "oracle":
                    assert await connection.fetchval(
                        "SELECT INTERVAL '1 02:03:04' DAY TO SECOND FROM dual"
                    ) == "+01 02:03:04.000000"
                else:
                    assert await connection.fetchval(
                        "SELECT CAST(0x00ff AS VARBINARY(2))"
                    ) == b"\x00\xff"
        finally:
            async with pool.acquire() as connection:
                await drop_table(connection, table)
            await pool.close()

    asyncio.run(scenario())


def test_pool_callbacks_run_in_order_and_preserve_kes_mode(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool init/setup/reset 生命周期顺序正确且连接保持 KES 模式。"""
    async def scenario() -> None:
        events: list[tuple[str, int]] = []

        async def init(connection: asyncpg.Connection) -> None:
            assert connection.get_kes_mode() == kes_config.mode
            events.append(("init", connection.get_server_pid()))

        async def setup(connection: asyncpg.Connection) -> None:
            assert connection.get_kes_mode() == kes_config.mode
            events.append(("setup", connection.get_server_pid()))

        async def reset(connection: asyncpg.Connection) -> None:
            events.append(("reset", connection.get_server_pid()))
            await connection.reset()

        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        pool = await asyncpg.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
            init=init,
            setup=setup,
            reset=reset,
        )
        try:
            pids = []
            for _ in range(2):
                async with pool.acquire() as connection:
                    pids.append(connection.get_server_pid())
                    assert await connection.fetchval(
                        kes_config.select_one
                    ) == 1
            assert pids[0] == pids[1]
            assert [event for event, _ in events] == [
                "init", "setup", "reset", "setup", "reset"
            ]
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_pool_partial_initialization_failure_closes_kes_connections(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool 部分初始化失败时关闭所有已建立的 KES 连接。"""
    async def scenario() -> None:
        opened_connections: list[asyncpg.Connection] = []
        connection_attempt = 0

        async def connect_then_fail(*args, **kwargs) -> asyncpg.Connection:
            nonlocal connection_attempt
            connection_attempt += 1
            if connection_attempt == 2:
                await asyncio.sleep(0.05)
                raise RuntimeError("simulated pool initialization failure")

            connection = await asyncpg.connect(*args, **kwargs)
            opened_connections.append(connection)
            return connection

        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        with pytest.raises(
            RuntimeError, match="simulated pool initialization failure"
        ):
            await asyncpg.create_pool(
                **pool_options,
                min_size=3,
                max_size=3,
                connect=connect_then_fail,
            )

        assert opened_connections
        assert all(
            connection.is_closed() for connection in opened_connections
        )

    asyncio.run(scenario())


def test_pool_init_callback_failure_closes_kes_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool init 回调失败时关闭刚建立的 KES 连接。"""
    async def scenario() -> None:
        opened_connections: list[asyncpg.Connection] = []

        async def tracked_connect(*args, **kwargs) -> asyncpg.Connection:
            connection = await asyncpg.connect(*args, **kwargs)
            opened_connections.append(connection)
            return connection

        async def failing_init(connection: asyncpg.Connection) -> None:
            raise RuntimeError("simulated pool init failure")

        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        with pytest.raises(
            RuntimeError, match="simulated pool init failure"
        ):
            await asyncpg.create_pool(
                **pool_options,
                min_size=1,
                max_size=1,
                connect=tracked_connect,
                init=failing_init,
            )

        assert len(opened_connections) == 1
        assert opened_connections[0].is_closed()

    asyncio.run(scenario())


def test_pool_setup_callback_failure_discards_connection_and_recovers(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool setup 回调失败后丢弃连接，下一次 acquire 可恢复。"""
    async def scenario() -> None:
        opened_connections: list[asyncpg.Connection] = []
        setup_calls = 0

        async def tracked_connect(*args, **kwargs) -> asyncpg.Connection:
            connection = await asyncpg.connect(*args, **kwargs)
            opened_connections.append(connection)
            return connection

        async def fail_first_setup(connection: asyncpg.Connection) -> None:
            nonlocal setup_calls
            setup_calls += 1
            if setup_calls == 1:
                raise RuntimeError("simulated pool setup failure")

        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        pool = await asyncpg.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
            connect=tracked_connect,
            setup=fail_first_setup,
        )
        try:
            with pytest.raises(
                RuntimeError, match="simulated pool setup failure"
            ):
                await pool.acquire()

            assert opened_connections[0].is_closed()
            async with pool.acquire() as connection:
                assert await connection.fetchval(kes_config.select_one) == 1
            assert len(opened_connections) == 2
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_pool_reset_callback_failure_discards_connection_and_recovers(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool reset 回调失败后终止连接，下一次 acquire 可恢复。"""
    async def scenario() -> None:
        opened_connections: list[asyncpg.Connection] = []
        reset_calls = 0

        async def tracked_connect(*args, **kwargs) -> asyncpg.Connection:
            connection = await asyncpg.connect(*args, **kwargs)
            opened_connections.append(connection)
            return connection

        async def fail_first_reset(connection: asyncpg.Connection) -> None:
            nonlocal reset_calls
            reset_calls += 1
            if reset_calls == 1:
                raise RuntimeError("simulated pool reset failure")
            await connection.reset()

        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        pool = await asyncpg.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
            connect=tracked_connect,
            reset=fail_first_reset,
        )
        try:
            connection = await pool.acquire()
            with pytest.raises(
                RuntimeError, match="simulated pool reset failure"
            ):
                await pool.release(connection)

            assert opened_connections[0].is_closed()
            async with pool.acquire() as recovered_connection:
                assert await recovered_connection.fetchval(
                    kes_config.select_one
                ) == 1
            assert len(opened_connections) == 2
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_pool_rejects_wrong_connection_class_without_leaking_kes_session(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool connect 回调返回错误连接类型时关闭已建立的 KES 会话。"""
    class RequiredConnection(asyncpg.Connection):
        pass

    async def scenario() -> None:
        opened_connections: list[asyncpg.Connection] = []

        async def connect_with_wrong_class(
            *args, **kwargs
        ) -> asyncpg.Connection:
            kwargs["connection_class"] = asyncpg.Connection
            connection = await asyncpg.connect(*args, **kwargs)
            opened_connections.append(connection)
            return connection

        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        with pytest.raises(
            asyncpg.InterfaceError,
            match="expected pool connect callback to return an instance",
        ):
            await asyncpg.create_pool(
                **pool_options,
                min_size=1,
                max_size=1,
                connect=connect_with_wrong_class,
                connection_class=RequiredConnection,
            )

        assert len(opened_connections) == 1
        assert opened_connections[0].is_closed()

    asyncio.run(scenario())


def test_pool_rejects_foreign_proxy_without_terminating_its_kes_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool connect 回调返回其他 Pool 代理时不终止其 KES 连接。"""
    async def scenario() -> None:
        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")
        source_pool = await asyncpg.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
        )
        source_connection = await source_pool.acquire()

        async def connect_with_foreign_proxy(*args, **kwargs):
            return source_connection

        try:
            with pytest.raises(
                asyncpg.InterfaceError,
                match="expected pool connect callback to return an instance",
            ):
                await asyncpg.create_pool(
                    **pool_options,
                    min_size=1,
                    max_size=1,
                    connect=connect_with_foreign_proxy,
                )

            assert not source_connection.is_closed()
            assert await source_connection.fetchval(kes_config.select_one) == 1
        finally:
            await source_pool.release(source_connection)
            await source_pool.close()

    asyncio.run(scenario())


def test_pool_query_and_idle_recycling_reload_kes_codecs(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool 按查询数和空闲时间回收后，新连接重新注册 KES codec。"""
    async def codec_value(connection: asyncpg.Connection):
        if kes_config.mode == "mysql":
            return await connection.fetchval(
                "SELECT CAST('2025-01-02' AS DATE)"
            )
        if kes_config.mode == "sqlserver":
            return await connection.fetchval(
                "SELECT CAST(0x00ff AS VARBINARY(2))"
            )
        return await connection.fetchval(
            "SELECT INTERVAL '1 00:00:00.123456' "
            "DAY TO SECOND FROM dual"
        )

    async def scenario() -> None:
        expected = (
            datetime.date(2025, 1, 2)
            if kes_config.mode == "mysql"
            else (
                b"\x00\xff"
                if kes_config.mode == "sqlserver"
                else "+01 00:00:00.123456"
            )
        )
        pool_options = kes_config.connection_kwargs()
        pool_options.pop("timeout")

        query_pool = await asyncpg.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
            max_queries=1,
        )
        try:
            query_pids = []
            for _ in range(2):
                async with query_pool.acquire() as connection:
                    query_pids.append(connection.get_server_pid())
                    assert await codec_value(connection) == expected
            assert query_pids[0] != query_pids[1]
        finally:
            await query_pool.close()

        idle_pool = await asyncpg.create_pool(
            **pool_options,
            min_size=1,
            max_size=1,
            max_inactive_connection_lifetime=0.05,
        )
        try:
            async with idle_pool.acquire() as connection:
                first_pid = connection.get_server_pid()
                assert await codec_value(connection) == expected
            await asyncio.sleep(0.1)
            async with idle_pool.acquire() as connection:
                assert connection.get_server_pid() != first_pid
                assert await codec_value(connection) == expected
        finally:
            await idle_pool.close()

    asyncio.run(scenario())


def test_connection_public_metadata_and_callback_removal(
    kes_config: KESConfig,
) -> None:
    """测试点：服务器元数据及日志、查询、终止回调的移除语义完整可用。"""
    async def scenario() -> None:
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        query_records: list[asyncpg.connection.LoggedQuery] = []
        notices: list[str] = []
        removed_terminations: list[asyncpg.Connection] = []
        active_termination = asyncio.Event()

        def log_listener(
            _: asyncpg.Connection,
            message: asyncpg.PostgresLogMessage,
        ) -> None:
            notices.append(message.message)

        def removed_termination_listener(con: asyncpg.Connection) -> None:
            removed_terminations.append(con)

        try:
            version = connection.get_server_version()
            assert version.major > 0
            assert connection.get_server_pid() > 0
            assert "RESET ALL" in connection.get_reset_query()

            connection.add_query_logger(query_records.append)
            assert await connection.fetchval(kes_config.select_one) == 1
            connection.remove_query_logger(query_records.append)
            await asyncio.sleep(0)
            assert [record.query for record in query_records] == [
                kes_config.select_one
            ]
            assert await connection.fetchval(kes_config.select_one) == 1
            await asyncio.sleep(0)
            assert len(query_records) == 1

            connection.add_log_listener(log_listener)
            await connection.execute(
                "DO $$ BEGIN RAISE NOTICE 'kes-callback-active'; END; $$ "
                "LANGUAGE plpgsql"
            )
            await asyncio.sleep(0)
            connection.remove_log_listener(log_listener)
            await connection.execute(
                "DO $$ BEGIN RAISE NOTICE 'kes-callback-removed'; END; $$ "
                "LANGUAGE plpgsql"
            )
            await asyncio.sleep(0)
            assert notices == ["kes-callback-active"]

            connection.add_termination_listener(
                removed_termination_listener)
            connection.remove_termination_listener(
                removed_termination_listener)
            connection.add_termination_listener(
                lambda _: active_termination.set())
        finally:
            await connection.close()

        await asyncio.wait_for(active_termination.wait(), timeout=1)
        assert removed_terminations == []

    asyncio.run(scenario())


def test_batch_cursor_and_manual_transaction_public_contracts(
    kes_config: KESConfig,
) -> None:
    """测试点：批处理、预编译信息、双游标及手动提交回滚保持原 API 合同。"""
    async def scenario() -> None:
        table = unique_object_name("public_batch", kes_config.mode)
        id_type = "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
        text_type = (
            "VARCHAR2(30)" if kes_config.mode == "oracle"
            else "VARCHAR(30)"
        )
        connection = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            await connection.execute(
                f"CREATE TABLE {table} "
                f"(id {id_type} PRIMARY KEY, label {text_type})"
            )
            assert await connection.executemany(
                f"INSERT INTO {table} (id, label) VALUES ($1, $2)",
                [(1, "one"), (2, "two")],
            ) is None

            query = f"SELECT id, label FROM {table} WHERE id = $1"
            statement_name = f"apg_public_batch_{kes_config.mode}"
            statement = await connection.prepare(query, name=statement_name)
            assert statement.get_name() == statement_name
            assert statement.get_query() == query
            expected_parameter_type = (
                "numeric" if kes_config.mode == "oracle" else "int4"
            )
            assert [item.name for item in statement.get_parameters()] == [
                expected_parameter_type
            ]
            assert [item.name for item in statement.get_attributes()] == [
                "id", "label"
            ]
            assert [tuple(row) for row in await statement.fetch(1)] == [
                (1, "one")
            ]
            assert statement.get_statusmsg() == "SELECT 1"
            assert [tuple(row) for row in await statement.fetchmany(
                [(1,), (2,)]
            )] == [(1, "one"), (2, "two")]

            update = await connection.prepare(
                f"UPDATE {table} SET label = $2 WHERE id = $1"
            )
            assert await update.executemany(
                [(1, "first"), (2, "second")]
            ) is None

            async with connection.transaction():
                cursor = await connection.cursor(
                    f"SELECT id FROM {table} ORDER BY id"
                )
                assert await cursor.fetchrow() == (1,)
                assert await cursor.forward(1) == 1
                assert await cursor.fetchrow() is None

                fetch_cursor = await connection.cursor(
                    f"SELECT id FROM {table} ORDER BY id"
                )
                assert await fetch_cursor.fetch(2) == [(1,), (2,)]

                prepared_cursor = await statement.cursor(2)
                assert await prepared_cursor.fetchrow() == (2, "second")

            rollback = connection.transaction()
            await rollback.start()
            await connection.execute(
                f"INSERT INTO {table} VALUES ($1, $2)", 3, "rollback"
            )
            await rollback.rollback()
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 2

            commit = connection.transaction()
            await commit.start()
            await connection.execute(
                f"INSERT INTO {table} VALUES ($1, $2)", 3, "commit"
            )
            await commit.commit()
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 3
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


def test_pool_batch_capacity_timeout_and_shutdown_contracts(
    kes_config: KESConfig,
) -> None:
    """测试点：Pool 批处理代理、容量统计、获取超时、并发排队和关闭状态正常。"""
    async def scenario() -> None:
        table = unique_object_name("pool_contract", kes_config.mode)
        id_type = "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
        text_type = (
            "VARCHAR2(30)" if kes_config.mode == "oracle"
            else "VARCHAR(30)"
        )
        options = kes_config.connection_kwargs()
        options.pop("timeout")
        pool = await asyncpg.create_pool(
            **options, min_size=1, max_size=3
        )
        cleanup = await asyncpg.connect(**kes_config.connection_kwargs())
        try:
            assert pool.get_min_size() == 1
            assert pool.get_max_size() == 3
            assert pool.get_size() == 1
            assert pool.get_idle_size() == 1
            assert not pool.is_closing()

            await pool.execute(
                f"CREATE TABLE {table} "
                f"(id {id_type} PRIMARY KEY, label {text_type})"
            )
            assert await pool.executemany(
                f"INSERT INTO {table} VALUES ($1, $2)",
                [(1, "one"), (2, "two")],
            ) is None
            rows = await pool.fetchmany(
                f"SELECT label FROM {table} WHERE id = $1",
                [(1,), (2,)],
            )
            assert [row["label"] for row in rows] == ["one", "two"]

            held = await pool.acquire()
            try:
                second = await pool.acquire()
                third = await pool.acquire()
                try:
                    with pytest.raises(asyncio.TimeoutError):
                        await pool.acquire(timeout=0.01)
                finally:
                    await pool.release(third)
                    await pool.release(second)
            finally:
                await pool.release(held)

            async def worker(value: int) -> int:
                async with pool.acquire() as connection:
                    await asyncio.sleep(0.01)
                    return await connection.fetchval(
                        "SELECT CAST($1 AS INTEGER)" + (
                            " FROM dual" if kes_config.mode == "oracle"
                            else ""
                        ),
                        value,
                    )

            assert await asyncio.gather(
                *(worker(value) for value in range(12))
            ) == list(range(12))
            assert 1 <= pool.get_size() <= 3
            assert pool.get_idle_size() == pool.get_size()

            await pool.execute(f"DROP TABLE {table}")
            await pool.close()
            assert pool.is_closing()

            terminate_pool = await asyncpg.create_pool(
                **options, min_size=1, max_size=1
            )
            assert not terminate_pool.is_closing()
            terminate_pool.terminate()
            assert terminate_pool.is_closing()
        finally:
            if not pool.is_closing():
                pool.terminate()
            await drop_table(cleanup, table)
            await cleanup.close()

    asyncio.run(scenario())
