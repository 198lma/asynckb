"""Tests for the protocol and async requirement module."""

from __future__ import annotations

import asyncio
import io
import os
from decimal import Decimal
import asynckb
import pytest
from tests.kes.support.config import KESConfig, drop_table, unique_object_name


@pytest.mark.case_id("KB-PROTO-016")
@pytest.mark.integration
def test_connected_server_rejects_the_wrong_compatibility_mode(
    kes_config: KESConfig,
) -> None:
    """测试点：配置模式与实际 KES 实例不一致时连接必须失败。"""
    async def scenario() -> None:
        wrong_mode = "oracle" if kes_config.mode == "mysql" else "mysql"
        with pytest.raises(
            asynckb.ClientConfigurationError,
            match="does not match the connected KingbaseES instance",
        ):
            await asynckb.connect(
                **kes_config.connection_kwargs(kes_mode=wrong_mode)
            )

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-017")
@pytest.mark.integration
def test_wrong_mode_initialization_closes_server_session(
    kes_config: KESConfig,
) -> None:
    """测试点：KES 模式识别失败后驱动关闭已建立的服务端会话。"""
    async def scenario() -> None:
        application_name = unique_object_name("wrong_mode", kes_config.mode)
        wrong_mode = "oracle" if kes_config.mode == "mysql" else "mysql"
        observer = await asynckb.connect(
            **kes_config.connection_kwargs()
        )
        try:
            with pytest.raises(asynckb.ClientConfigurationError):
                await asynckb.connect(
                    **kes_config.connection_kwargs(
                        kes_mode=wrong_mode,
                        server_settings={
                            "application_name": application_name,
                        },
                    )
                )
            assert await observer.fetchval(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE application_name = $1",
                application_name,
            ) == 0
        finally:
            await observer.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-020")
@pytest.mark.integration
def test_copy_round_trip_supports_records_csv_text_and_binary(
    kes_config: KESConfig,
) -> None:
    """测试点：COPY records、CSV、TEXT、BINARY 四条数据路径结果一致。"""
    async def scenario() -> None:
        prefix = unique_object_name("copy", kes_config.mode)
        suffixes = ("src", "csv", "text", "binary")
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        records = [
            (1, "alpha", Decimal("12.34"), b"abc"),
            (2, "tab\tline", Decimal("0.50"), b"\x00\xff"),
        ]
        try:
            for suffix in suffixes:
                table = f"{prefix}_{suffix}"
                if kes_config.mode == "oracle":
                    types = (
                        "NUMBER(10)",
                        "VARCHAR2(100)",
                        "NUMBER(10,2)",
                        "BLOB",
                    )
                else:
                    types = (
                        "INT",
                        "VARCHAR(100)",
                        "DECIMAL(10,2)",
                        "VARBINARY(100)",
                    )
                await connection.execute(
                    f"CREATE TABLE {table} (id {types[0]} PRIMARY KEY, "
                    f"txt {types[1]}, amount {types[2]}, payload {types[3]})"
                )

            assert await connection.copy_records_to_table(
                f"{prefix}_src", records=records
            ) == "COPY 2"

            csv_output = io.BytesIO()
            assert await connection.copy_from_table(
                f"{prefix}_src", output=csv_output, format="csv", header=True
            ) == "COPY 2"
            assert await connection.copy_to_table(
                f"{prefix}_csv",
                source=csv_output.getvalue(),
                format="csv",
                header=True,
            ) == "COPY 2"

            text_output = io.BytesIO()
            assert await connection.copy_from_table(
                f"{prefix}_src", output=text_output, format="text"
            ) == "COPY 2"
            assert await connection.copy_to_table(
                f"{prefix}_text", source=text_output.getvalue(), format="text"
            ) == "COPY 2"

            binary_output = io.BytesIO()
            assert await connection.copy_from_table(
                f"{prefix}_src", output=binary_output, format="binary"
            ) == "COPY 2"
            assert await connection.copy_to_table(
                f"{prefix}_binary",
                source=binary_output.getvalue(),
                format="binary",
            ) == "COPY 2"

            for suffix in suffixes:
                rows = await connection.fetch(
                    f"SELECT id, txt, amount, payload FROM {prefix}_{suffix} "
                    "ORDER BY id"
                )
                assert [tuple(row) for row in rows] == records
        finally:
            for suffix in suffixes:
                await drop_table(connection, f"{prefix}_{suffix}")
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-021")
@pytest.mark.integration
def test_copy_source_accepts_inline_bytes_and_bytes_file_path(
    kes_config: KESConfig,
    tmp_path,
) -> None:
    """测试点：COPY source 同时支持内存 bytes 和原 asynckb 的 bytes 文件路径。"""
    async def scenario() -> None:
        table = unique_object_name("copy_bytes_path", kes_config.mode)
        connection = await asynckb.connect(
            **kes_config.connection_kwargs()
        )
        source_path = tmp_path / "copy-source.csv"
        source_path.write_bytes(b"2,file-path\n")
        try:
            id_type = (
                "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            )
            text_type = (
                "VARCHAR2(30)"
                if kes_config.mode == "oracle"
                else "VARCHAR(30)"
            )
            await connection.execute(
                f"CREATE TABLE {table} (id {id_type}, label {text_type})"
            )
            assert await connection.copy_to_table(
                table,
                source=b"1,inline\n",
                format="csv",
            ) == "COPY 1"
            assert await connection.copy_to_table(
                table,
                source=os.fsencode(source_path),
                format="csv",
            ) == "COPY 1"
            rows = await connection.fetch(
                f"SELECT id, label FROM {table} ORDER BY id"
            )
            assert [tuple(row) for row in rows] == [
                (1, "inline"),
                (2, "file-path"),
            ]
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-022")
@pytest.mark.integration
def test_copy_inline_bytes_survives_path_probe_errors(
    kes_config: KESConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试点：bytes 源的文件路径探测失败时仍按内存 COPY 数据处理。"""
    async def scenario() -> None:
        table = unique_object_name("copy_path_probe", kes_config.mode)
        connection = await asynckb.connect(
            **kes_config.connection_kwargs()
        )
        try:
            id_type = (
                "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            )
            text_type = (
                "VARCHAR2(30)"
                if kes_config.mode == "oracle"
                else "VARCHAR(30)"
            )
            await connection.execute(
                f"CREATE TABLE {table} (id {id_type}, label {text_type})"
            )

            def fail_path_probe(path: object) -> bool:
                raise OSError("simulated path probe failure")

            monkeypatch.setattr(
                "asynckb.connection.os.path.exists", fail_path_probe
            )
            assert await connection.copy_to_table(
                table,
                source=b"1,inline\n",
                format="csv",
            ) == "COPY 1"
            assert await connection.fetchrow(
                f"SELECT id, label FROM {table}"
            ) == (1, "inline")
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-024")
@pytest.mark.integration
def test_copy_async_records_parameterized_sink_and_source(
    kes_config: KESConfig,
) -> None:
    """测试点：COPY 支持异步 records、带参数查询、异步输出和异步输入链路。"""
    async def scenario() -> None:
        source_table = unique_object_name("copy_async_src", kes_config.mode)
        target_table = unique_object_name("copy_async_dst", kes_config.mode)
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        chunks: list[bytes] = []

        async def records():
            for record in ((1, "one"), (2, "two"), (3, "three")):
                await asyncio.sleep(0)
                yield record

        async def sink(chunk: bytes) -> None:
            await asyncio.sleep(0)
            chunks.append(chunk)

        async def source():
            for chunk in chunks:
                await asyncio.sleep(0)
                yield chunk

        try:
            id_type = (
                "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            )
            text_type = (
                "VARCHAR2(30)"
                if kes_config.mode == "oracle"
                else "VARCHAR(30)"
            )
            for table in (source_table, target_table):
                await connection.execute(
                    f"CREATE TABLE {table} "
                    f"(id {id_type}, label {text_type})"
                )

            assert await connection.copy_records_to_table(
                source_table, records=records()
            ) == "COPY 3"
            parameter = (
                "CAST($1 AS INT)" if kes_config.mode == "mysql" else "$1"
            )
            assert await connection.copy_from_query(
                f"SELECT id, label FROM {source_table} "
                f"WHERE id >= {parameter} ORDER BY id",
                2,
                output=sink,
                format="csv",
            ) == "COPY 2"
            assert chunks
            assert await connection.copy_to_table(
                target_table,
                source=source(),
                format="csv",
            ) == "COPY 2"
            assert [tuple(row) for row in await connection.fetch(
                f"SELECT id, label FROM {target_table} ORDER BY id"
            )] == [(2, "two"), (3, "three")]
        finally:
            await drop_table(connection, target_table)
            await drop_table(connection, source_table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-025")
@pytest.mark.integration
def test_copy_completed_output_sink_failure_preserves_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：小结果 COPY 已完成后 sink 异常不触发无限取消等待。"""
    async def scenario() -> None:
        table = unique_object_name("copy_done_sink_error", kes_config.mode)
        connection = await asynckb.connect(
            **kes_config.connection_kwargs()
        )

        async def failing_sink(chunk: bytes) -> None:
            assert chunk
            raise RuntimeError("output sink failure")

        try:
            id_type = (
                "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            )
            await connection.execute(
                f"CREATE TABLE {table} (id {id_type})"
            )
            await connection.execute(f"INSERT INTO {table} VALUES (1)")

            with pytest.raises(RuntimeError, match="output sink failure"):
                await connection.copy_from_table(
                    table,
                    output=failing_sink,
                    format="csv",
                )

            assert await asyncio.wait_for(
                connection.fetchval(kes_config.select_one),
                timeout=2,
            ) == 1
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-026")
@pytest.mark.integration
def test_copy_active_output_sink_failure_preserves_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：大结果 COPY 进行中 sink 异常能取消命令并复用连接。"""
    async def scenario() -> None:
        table = unique_object_name("copy_active_sink_error", kes_config.mode)
        connection = await asynckb.connect(
            **kes_config.connection_kwargs()
        )
        row_count = 1024

        async def failing_sink(chunk: bytes) -> None:
            assert chunk
            await asyncio.sleep(0.01)
            raise RuntimeError("active output sink failure")

        try:
            id_type = (
                "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            )
            text_type = (
                "VARCHAR2(1200)"
                if kes_config.mode == "oracle"
                else "VARCHAR(1200)"
            )
            await connection.execute(
                f"CREATE TABLE {table} "
                f"(id {id_type}, payload {text_type})"
            )
            assert await connection.copy_records_to_table(
                table,
                records=((index, "x" * 1000) for index in range(row_count)),
            ) == f"COPY {row_count}"

            with pytest.raises(
                RuntimeError,
                match="active output sink failure",
            ):
                await connection.copy_from_table(
                    table,
                    output=failing_sink,
                    format="csv",
                )

            assert await asyncio.wait_for(
                connection.fetchval(kes_config.select_one),
                timeout=2,
            ) == 1
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == row_count
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-027")
@pytest.mark.integration
def test_copy_async_source_failures_are_atomic_and_connection_reusable(
    kes_config: KESConfig,
) -> None:
    """测试点：COPY source 首次和中途异常均回滚已发送数据并复用连接。"""
    async def scenario() -> None:
        tables = [
            unique_object_name("copy_source_first", kes_config.mode),
            unique_object_name("copy_source_middle", kes_config.mode),
        ]
        connection = await asynckb.connect(
            **kes_config.connection_kwargs()
        )

        async def fail_on_first_read():
            raise RuntimeError("source first-read failure")
            yield b""  # pragma: no cover

        async def fail_after_one_chunk():
            yield b"1,partial\n"
            await asyncio.sleep(0)
            raise RuntimeError("source middle failure")

        sources = (
            (fail_on_first_read(), "source first-read failure"),
            (fail_after_one_chunk(), "source middle failure"),
        )
        try:
            id_type = (
                "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            )
            text_type = (
                "VARCHAR2(30)"
                if kes_config.mode == "oracle"
                else "VARCHAR(30)"
            )
            for table in tables:
                await connection.execute(
                    f"CREATE TABLE {table} "
                    f"(id {id_type}, label {text_type})"
                )

            for table, (source, message) in zip(tables, sources):
                with pytest.raises(RuntimeError, match=message):
                    await connection.copy_to_table(
                        table,
                        source=source,
                        format="csv",
                    )
                assert await asyncio.wait_for(
                    connection.fetchval(kes_config.select_one),
                    timeout=2,
                ) == 1
                assert await connection.fetchval(
                    f"SELECT count(*) FROM {table}"
                ) == 0
        finally:
            for table in tables:
                await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-028")
@pytest.mark.integration
def test_copy_async_source_timeout_is_atomic_and_connection_reusable(
    kes_config: KESConfig,
) -> None:
    """测试点：COPY source 超时后无部分数据且连接可继续查询。"""
    async def scenario() -> None:
        table = unique_object_name("copy_source_timeout", kes_config.mode)
        connection = await asynckb.connect(
            **kes_config.connection_kwargs()
        )

        async def slow_source():
            yield b"1,partial\n"
            await asyncio.sleep(1)
            yield b"2,late\n"

        try:
            id_type = (
                "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            )
            text_type = (
                "VARCHAR2(30)"
                if kes_config.mode == "oracle"
                else "VARCHAR(30)"
            )
            await connection.execute(
                f"CREATE TABLE {table} "
                f"(id {id_type}, label {text_type})"
            )

            with pytest.raises(asyncio.TimeoutError):
                await connection.copy_to_table(
                    table,
                    source=slow_source(),
                    format="csv",
                    timeout=0.05,
                )

            assert await asyncio.wait_for(
                connection.fetchval(kes_config.select_one),
                timeout=2,
            ) == 1
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 0
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-029")
@pytest.mark.integration
def test_copy_server_error_before_source_error_preserves_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：COPY 服务端先拒绝数据时不再为延迟 source 异常取消空闲连接。"""
    async def scenario() -> None:
        table = unique_object_name("copy_server_source_error", kes_config.mode)
        connection = await asynckb.connect(
            **kes_config.connection_kwargs()
        )

        async def failing_source():
            yield b"not-an-integer\n"
            await asyncio.sleep(0.2)
            raise RuntimeError("late source failure")

        try:
            id_type = (
                "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            )
            await connection.execute(
                f"CREATE TABLE {table} (id {id_type})"
            )

            with pytest.raises(RuntimeError, match="late source failure"):
                await connection.copy_to_table(
                    table,
                    source=failing_source(),
                    format="csv",
                )

            assert await asyncio.wait_for(
                connection.fetchval(kes_config.select_one),
                timeout=2,
            ) == 1
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 0
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-030")
@pytest.mark.integration
def test_copy_server_error_racing_source_timeout_preserves_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：COPY 服务端报错与 source 超时竞态不产生内部异常或污染连接。"""
    async def scenario() -> None:
        table = unique_object_name("copy_server_timeout", kes_config.mode)
        connection = await asynckb.connect(
            **kes_config.connection_kwargs()
        )

        async def slow_source():
            yield b"not-an-integer\n"
            await asyncio.sleep(1)
            yield b"1\n"

        try:
            id_type = (
                "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            )
            await connection.execute(
                f"CREATE TABLE {table} (id {id_type})"
            )

            with pytest.raises(
                (asyncio.TimeoutError, asynckb.PostgresError)
            ) as error:
                await connection.copy_to_table(
                    table,
                    source=slow_source(),
                    format="csv",
                    timeout=0.2,
                )
            assert not isinstance(error.value, asynckb.InternalClientError)

            assert await asyncio.wait_for(
                connection.fetchval(kes_config.select_one),
                timeout=2,
            ) == 1
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 0
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-031")
@pytest.mark.integration
def test_copy_completed_output_sink_timeout_preserves_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：小结果 COPY 已完成后 sink 超时不再取消已空闲的连接。"""
    async def scenario() -> None:
        table = unique_object_name("copy_done_sink_timeout", kes_config.mode)
        connection = await asynckb.connect(
            **kes_config.connection_kwargs()
        )

        async def slow_sink(chunk: bytes) -> None:
            assert chunk
            await asyncio.sleep(1)

        try:
            id_type = (
                "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            )
            await connection.execute(
                f"CREATE TABLE {table} (id {id_type})"
            )
            await connection.execute(f"INSERT INTO {table} VALUES (1)")

            with pytest.raises(asyncio.TimeoutError):
                await connection.copy_from_table(
                    table,
                    output=slow_sink,
                    format="csv",
                    timeout=0.1,
                )

            assert await asyncio.wait_for(
                connection.fetchval(kes_config.select_one),
                timeout=2,
            ) == 1
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-032")
@pytest.mark.integration
def test_copy_server_error_before_source_cancellation_preserves_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：COPY 服务端先报错后取消 source 任务不会阻塞连接复用。"""
    async def scenario() -> None:
        table = unique_object_name("copy_server_cancel", kes_config.mode)
        connection = await asynckb.connect(
            **kes_config.connection_kwargs()
        )

        async def blocked_source():
            yield b"not-an-integer\n"
            await asyncio.sleep(5)

        try:
            id_type = (
                "NUMBER(10)" if kes_config.mode == "oracle" else "INT"
            )
            await connection.execute(
                f"CREATE TABLE {table} (id {id_type})"
            )
            task = asyncio.create_task(connection.copy_to_table(
                table,
                source=blocked_source(),
                format="csv",
            ))
            await asyncio.sleep(0.2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)

            assert await asyncio.wait_for(
                connection.fetchval(kes_config.select_one),
                timeout=2,
            ) == 1
            assert await connection.fetchval(
                f"SELECT count(*) FROM {table}"
            ) == 0
        finally:
            await drop_table(connection, table)
            await connection.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-033")
@pytest.mark.integration
def test_listen_notify_delivers_payload_in_both_modes(
    kes_config: KESConfig,
) -> None:
    """测试点：监听连接能收到发送连接发出的频道和 payload。"""
    async def scenario() -> None:
        listener = await asynckb.connect(**kes_config.connection_kwargs())
        sender = await asynckb.connect(**kes_config.connection_kwargs())
        event = asyncio.Event()
        notifications: list[tuple[str, str]] = []
        channel = unique_object_name("channel", kes_config.mode)

        def callback(
            connection: asynckb.Connection,
            pid: int,
            name: str,
            payload: str,
        ) -> None:
            notifications.append((name, payload))
            event.set()

        try:
            await listener.add_listener(channel, callback)
            await sender.execute(
                "SELECT pg_notify($1, $2)", channel, kes_config.mode
            )
            await asyncio.wait_for(event.wait(), timeout=2)
            assert notifications == [(channel, kes_config.mode)]
            await listener.remove_listener(channel, callback)
        finally:
            await listener.close()
            await sender.close()

    asyncio.run(scenario())


@pytest.mark.case_id("KB-PROTO-035")
@pytest.mark.integration
def test_repeated_query_timeout_race_preserves_connection(
    kes_config: KESConfig,
) -> None:
    """测试点：三模式连续极短查询超时不会污染取消状态或后续连接。"""
    async def scenario() -> None:
        connection = await asynckb.connect(**kes_config.connection_kwargs())
        try:
            for _ in range(100):
                with pytest.raises(asyncio.TimeoutError):
                    await connection.fetch(
                        "SELECT pg_sleep(1)", timeout=1e-10
                    )
                assert await connection.fetchval(
                    kes_config.select_one, timeout=1
                ) == 1
        finally:
            await connection.close()

    asyncio.run(scenario())
