"""Real KES integration with disposable LDAP/RADIUS/OS/TLS services."""

import asyncio
from contextlib import contextmanager
import io
import os
import pwd
import socketserver
import ssl
import threading

import asynckb
import pytest

from tests.kes.authentication.wire import AuthenticationProxy


@contextmanager
def ldap_service(username, password):
    ldapserver = pytest.importorskip("ldapserver")
    attempts = []
    class Handler(ldapserver.LDAPRequestHandler):
        def do_bind_simple_authenticated(self, dn, supplied):
            valid = dn == f"uid={username},dc=kes,dc=test" and (
                supplied.decode() == password
            )
            attempts.append((dn, valid))
            if not valid:
                raise ldapserver.exceptions.LDAPInvalidCredentials()
            return dn
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], attempts
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def radius_service(username, password):
    packet = pytest.importorskip("pyrad.packet")
    dictionary = pytest.importorskip("pyrad.dictionary")
    definitions = dictionary.Dictionary(io.StringIO(
        "ATTRIBUTE User-Name 1 string\nATTRIBUTE User-Password 2 octets\n"
        "ATTRIBUTE NAS-Identifier 32 string\n"
    ))
    secret = b"kes-test-radius-shared-secret"
    attempts = []
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            data, sock = self.request
            request = packet.AuthPacket(
                secret=secret, dict=definitions, packet=data,
            )
            valid = request["User-Name"] == [username] and (
                request.PwDecrypt(request["User-Password"][0]) == password
            )
            attempts.append((request["User-Name"][0], valid))
            response = request.CreateReply()
            response.code = packet.AccessAccept if valid else packet.AccessReject
            sock.sendto(response.ReplyPacket(), self.client_address)
    server = socketserver.UDPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], secret.decode(), attempts
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.case_id("KB-AUTH-010")
@pytest.mark.integration
@pytest.mark.parametrize("valid", (True, False), ids=("valid", "wrong-password"))
@pytest.mark.parametrize("method", ("ldap", "radius"))
def test_external_password_service(isolated_kes, method, valid):
    """测试点：真实 KES 转发密码至本机 LDAP/RADIUS，正确放行、错误拒绝。"""
    instance = isolated_kes
    async def scenario():
        if method == "ldap":
            service = ldap_service(instance.role, instance.external_password)
        else:
            service = radius_service(instance.role, instance.external_password)
        with service as backend:
            port, *rest = backend
            attempts = rest[-1]
            if method == "ldap":
                options = (
                    f'ldapserver=127.0.0.1 ldapport={port} '
                    'ldapprefix="uid=" ldapsuffix=",dc=kes,dc=test"'
                )
            else:
                options = (
                    f'radiusservers=127.0.0.1 radiusports={port} '
                    f'radiussecrets="{rest[0]}"'
                )
            rule = f"host test {instance.role} 127.0.0.1/32 {method} {options}"
            async with instance.rules(rule):
                async with AuthenticationProxy("127.0.0.1", instance.port) as proxy:
                    kwargs = instance.options(port=proxy.local_port)
                    if not valid:
                        kwargs["password"] = "wrong-password"
                        with pytest.raises(asynckb.InvalidAuthorizationSpecificationError):
                            con = await asynckb.connect(**kwargs)
                            await con.close()
                        assert proxy.exchanges == [[3]]
                    else:
                        con = await asynckb.connect(**kwargs)
                        try:
                            assert await con.fetchval(instance.config.select_one) == 1
                            assert proxy.exchanges == [[3, 0]]
                        finally:
                            await con.close()
                    assert len(attempts) == 1
                    assert attempts[0][1] is valid
    asyncio.run(scenario())


@pytest.mark.case_id("KB-AUTH-011")
@pytest.mark.integration
@pytest.mark.parametrize("identity", ("valid", "wrong", "missing"))
def test_certificate_identity(isolated_kes, identity):
    """测试点：TLS CA/CN 校验通过后 cert 登录成功，缺证书/错误身份拒绝。"""
    instance = isolated_kes
    context = ssl.create_default_context(cafile=instance.directory / "ca.crt")
    if identity != "missing":
        name = instance.role if identity == "valid" else "wrong_identity"
        context.load_cert_chain(
            instance.directory / f"{name}.crt", instance.directory / f"{name}.key"
        )
    async def scenario():
        async with instance.rules(
            f"hostssl test {instance.role} 127.0.0.1/32 cert"
        ):
            kwargs = instance.options(ssl=context)
            if identity == "valid":
                con = await asynckb.connect(**kwargs)
                try:
                    assert await con.fetchval(instance.config.select_one) == 1
                    assert con._protocol.is_ssl
                finally:
                    await con.close()
            else:
                with pytest.raises(asynckb.InvalidAuthorizationSpecificationError):
                    con = await asynckb.connect(**kwargs)
                    await con.close()
    asyncio.run(scenario())


@pytest.mark.case_id("KB-AUTH-012")
@pytest.mark.integration
@pytest.mark.parametrize("matches", (True, False), ids=("same-os-user", "wrong-os-user"))
def test_peer_identity(isolated_kes, matches):
    """测试点：Unix socket 使用操作系统身份校验，不依赖数据库密码。"""
    instance = isolated_kes
    username = pwd.getpwuid(os.geteuid()).pw_name
    async def scenario():
        admin = await asynckb.connect(**instance.config.connection_kwargs())
        try:
            from asynckb.utils import _quote_ident
            await admin.execute(f"CREATE ROLE {_quote_ident(username)} LOGIN")
        except asynckb.DuplicateObjectError:
            pass
        finally:
            await admin.close()
        role = username if matches else instance.role
        async with instance.rules(f"local test {role} peer"):
            # Explicit full socket path is accepted by the existing API.
            kwargs = instance.config.connection_kwargs(
                host=str(instance.socket_dir / f".s.KINGBASE.{instance.port}"),
                user=role, password="intentionally-wrong",
            )
            if matches:
                con = await asynckb.connect(**kwargs)
                try:
                    assert await con.fetchval("SELECT current_user") == username
                finally:
                    await con.close()
            else:
                with pytest.raises(asynckb.InvalidAuthorizationSpecificationError):
                    con = await asynckb.connect(**kwargs)
                    await con.close()
    asyncio.run(scenario())




@pytest.mark.case_id("KB-AUTH-015")
@pytest.mark.integration
@pytest.mark.parametrize("matches", (True, False), ids=("matching-ident", "wrong-ident"))
def test_ident_server(isolated_kes, matches):
    """测试点：真实 TCP ident 服务返回身份，匹配放行，不匹配拒绝。"""
    instance = isolated_kes
    async def scenario():
        attempts = []
        async def identify(reader, writer):
            try:
                ports = (await reader.readline()).strip()
                attempts.append(ports)
                name = instance.role if matches else "wrong_ident"
                writer.write(ports + f" : USERID : UNIX : {name}\r\n".encode())
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        try:
            server = await asyncio.start_server(identify, "127.0.0.1", 113)
        except PermissionError:
            pytest.skip("ident requires port 113; run in the documented network namespace")
        try:
            async with instance.rules(
                f"host test {instance.role} 127.0.0.1/32 ident"
            ):
                if matches:
                    con = await asynckb.connect(**instance.options())
                    try:
                        assert await con.fetchval(instance.config.select_one) == 1
                    finally:
                        await con.close()
                else:
                    with pytest.raises(asynckb.InvalidAuthorizationSpecificationError):
                        con = await asynckb.connect(**instance.options())
                        await con.close()
                assert len(attempts) == 1
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(scenario())


