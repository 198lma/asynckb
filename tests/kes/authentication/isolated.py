"""Disposable real KES instances; no production HBA, TLS or PAM changes."""

from __future__ import annotations

from contextlib import asynccontextmanager
import datetime
import os
from pathlib import Path
import secrets
import socket
import subprocess

import asynckb
from asynckb.utils import _quote_literal

from tests.kes.authentication.conftest import _reload
from tests.kes.support.config import KESConfig


DEFAULT_BINARIES = {
    "mysql": "/home/rootdba/kingbase-mysql/KESRealPro/V009R003C018/Server/bin",
    "oracle": (
        "/home/rootdba/kingbase-sqlserver/KESRealPro/"
        "V009R002C016/Server/bin"
    ),
    "sqlserver": (
        "/home/rootdba/kingbase-oracle/KESRealPro/"
        "V009R004C019/Server/bin"
    ),
}


def issue_certificates(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "KES test CA")])
    ca = (
        x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .sign(ca_key, hashes.SHA256())
    )
    (directory / "ca.crt").write_bytes(
        ca.public_bytes(serialization.Encoding.PEM)
    )
    for name in ("server", "apg_external", "wrong_identity"):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        builder = (
            x509.CertificateBuilder().subject_name(subject).issuer_name(
                ca_name
            ).public_key(key.public_key()).serial_number(
                x509.random_serial_number()
            )
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None), True
            )
        )
        if name == "server":
            import ipaddress
            builder = builder.add_extension(x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.DNSName("localhost"),
            ]), False)
            usage = ExtendedKeyUsageOID.SERVER_AUTH
        else:
            usage = ExtendedKeyUsageOID.CLIENT_AUTH
        cert = builder.add_extension(
            x509.ExtendedKeyUsage(
                [usage]), False).sign(
            ca_key, hashes.SHA256())
        key_path = directory / f"{name}.key"
        key_path.touch(mode=0o600)
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
        (directory / f"{name}.crt").write_bytes(
            cert.public_bytes(serialization.Encoding.PEM)
        )


class IsolatedKES:
    def __init__(self, mode, directory, *, preload=()):
        self.mode = mode
        self.preload = preload
        self.directory = directory
        self.data = directory / "data"
        self.socket_dir = directory / "socket"
        self.socket_dir.mkdir()
        self.bin = Path(os.environ.get(
            f"ASYNCKB_KES_{mode.upper()}_BIN", DEFAULT_BINARIES[mode]
        ))
        self.password = secrets.token_urlsafe(24)
        self.role = "apg_external"
        self.external_password = "KES-External-Password-42"
        with socket.socket() as port:
            port.bind(("127.0.0.1", 0))
            self.port = port.getsockname()[1]
        self.config = KESConfig(
            mode, "127.0.0.1", self.port, "system", self.password, "test",
        )
        self.started = False

    def run(self, *args, **kwargs):
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=90, **kwargs,
        )
        if result.returncode:
            raise RuntimeError(
                f"{Path(args[0]).name} failed: "
                f"{result.stdout}\n{result.stderr}"
            )
        return result

    def start(self):
        preload = ','.join(
            (('plsql',) if self.mode == 'oracle' else ()) + self.preload)
        password_file = self.directory / "init-password"
        password_file.touch(mode=0o600)
        password_file.write_text(self.password, encoding="ascii")
        self.run(
            str(self.bin / "initdb"), "-D", str(self.data), "-U", "system",
            "--pwfile", str(password_file), "--auth-host=scram-sha-256",
            "--auth-local=trust", "--no-locale", "-E", "UTF8", "-N",
        )
        issue_certificates(self.directory)
        (self.data / "kingbase.conf").write_text(
            f"port={self.port}\nlisten_addresses='127.0.0.1'\n"
            f"unix_socket_directories='{self.socket_dir}'\n"
            f"shared_preload_libraries='{preload}'\n"
            "max_connections=20\n"
            "shared_buffers='16MB'\nlogging_collector=off\n"
            "fsync=off\nssl=on\n"
            f"ssl_cert_file='{self.directory / 'server.crt'}'\n"
            f"ssl_key_file='{self.directory / 'server.key'}'\n"
            f"ssl_ca_file='{self.directory / 'ca.crt'}'\n",
            encoding="utf-8",
        )
        self.hba = self.data / "sys_hba.conf"
        self.hba.write_text(
            "local all all trust\nhost all all 127.0.0.1/32 scram-sha-256\n",
            encoding="ascii",
        )
        env = dict(os.environ)
        self.run(
            str(self.bin / "sys_ctl"), "-D", str(self.data), "-l",
            str(self.directory / "server.log"), "-w", "start", env=env,
        )
        self.started = True

    async def initialize(self):
        con = await asynckb.connect(
            **self.config.connection_kwargs(database="template1")
        )
        try:
            if not await con.fetchval(
                "SELECT 1 FROM pg_catalog.pg_database WHERE datname='test'"
            ):
                await con.execute("CREATE DATABASE test")
            await con.execute("SET password_encryption='scram-sha-256'")
            await con.execute(
                f"CREATE ROLE {self.role} LOGIN PASSWORD "
                f"{_quote_literal(self.password)}"
            )
        finally:
            await con.close()

    def stop(self):
        if self.started:
            self.run(
                str(self.bin / "sys_ctl"), "-D", str(self.data), "-m", "fast",
                "-w", "stop",
            )
            self.started = False

    def options(self, **overrides):
        options = dict(user=self.role, password=self.external_password)
        options.update(overrides)
        return self.config.connection_kwargs(**options)

    @asynccontextmanager
    async def rules(self, *lines):
        admin = await asynckb.connect(**self.config.connection_kwargs())
        original = self.hba.read_bytes()
        try:
            self.hba.write_bytes(("\n".join(lines) + "\n").encode() + original)
            errors = await admin.fetch(
                "SELECT error FROM pg_catalog.pg_hba_file_rules "
                "WHERE error IS NOT NULL"
            )
            assert not errors, errors
            await _reload(admin)
            yield admin
        finally:
            try:
                self.hba.write_bytes(original)
                await _reload(admin)
            finally:
                await admin.close()
