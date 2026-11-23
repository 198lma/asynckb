from __future__ import annotations

import asyncio
import base64
import struct


class AuthenticationProxy:
    """Relay real, non-TLS KES traffic and retain only authentication metadata."""

    def __init__(self, host: str, port: int, *, tamper: str | None = None):
        self.host = host
        self.port = port
        self.tamper = tamper
        self.exchanges: list[list[int]] = []
        self.mechanisms: list[bytes] = []
        self.client_macs: list[bytes] = []
        self._tasks: set[asyncio.Task] = set()
        self._writers: set[asyncio.StreamWriter] = set()

    async def __aenter__(self):
        self._server = await asyncio.start_server(
            self._relay, "127.0.0.1", 0
        )
        self.local_port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self._server.close()
        await self._server.wait_closed()
        for writer in tuple(self._writers):
            writer.close()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _relay(self, reader, writer):
        task = asyncio.current_task()
        self._tasks.add(task)
        self._writers.add(writer)
        upstream_writer = None
        pumps = []
        statuses: list[int] = []
        self.exchanges.append(statuses)
        sasl_initial = False
        mac_requested = False

        async def frontend(upstream):
            nonlocal sasl_initial, mac_requested
            length = struct.unpack("!I", await reader.readexactly(4))[0]
            startup = await reader.readexactly(length - 4)
            upstream.write(struct.pack("!I", length) + startup)
            await upstream.drain()
            while True:
                kind = await reader.readexactly(1)
                size = struct.unpack("!I", await reader.readexactly(4))[0]
                payload = await reader.readexactly(size - 4)
                if sasl_initial and kind == b"p":
                    self.mechanisms.append(payload.split(b"\0", 1)[0])
                    sasl_initial = False
                elif mac_requested and kind == b"p":
                    self.client_macs.append(payload.rstrip(b"\0"))
                    mac_requested = False
                upstream.write(kind + struct.pack("!I", size) + payload)
                await upstream.drain()

        async def backend(upstream):
            nonlocal sasl_initial, mac_requested
            while True:
                kind = await upstream.readexactly(1)
                size = struct.unpack("!I", await upstream.readexactly(4))[0]
                payload = await upstream.readexactly(size - 4)
                if kind == b"R":
                    status = struct.unpack("!I", payload[:4])[0]
                    statuses.append(status)
                    sasl_initial = status == 10
                    mac_requested = status == 19
                    if status == 10 and self.tamper == "mechanism":
                        payload = payload[:4] + b"UNSUPPORTED-TEST\0\0"
                    elif status == 11 and self.tamper == "nonce":
                        payload = payload[:4] + b"r=invalid," + payload.split(
                            b",", 1
                        )[1]
                    elif status == 12 and self.tamper == "signature":
                        payload = payload[:4] + b"v=" + base64.b64encode(
                            bytes(32)
                        )
                writer.write(
                    kind + struct.pack("!I", len(payload) + 4) + payload
                )
                await writer.drain()

        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                self.host, self.port
            )
            self._writers.add(upstream_writer)
            pumps = [
                asyncio.create_task(frontend(upstream_writer)),
                asyncio.create_task(backend(upstream_reader)),
            ]
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            for pump in pumps:
                pump.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            for stream in (writer, upstream_writer):
                if stream is not None:
                    stream.close()
                    try:
                        await stream.wait_closed()
                    except ConnectionError:
                        pass
                    self._writers.discard(stream)
            self._tasks.discard(task)
