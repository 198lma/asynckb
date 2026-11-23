from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import fcntl
import ipaddress
import os
from pathlib import Path
import secrets
import uuid

import asynckb
from asynckb.utils import _quote_ident, _quote_literal
import pytest

from tests.kes.support.config import KESConfig


POLICIES = {
    "scram": ("scram-sha-256", "scram-sha-256", [10, 11, 12, 0]),
    "md5": ("md5", "md5", [5, 0]),
    "md5_scram": ("md5", "scram-sha-256", [10, 11, 12, 0]),
    "password_md5": ("password", "md5", [3, 0]),
    "password_scram": ("password", "scram-sha-256", [3, 0]),
    "trust": ("trust", "scram-sha-256", [0]),
    "reject": ("reject", "scram-sha-256", []),
}


async def _reload(admin):
    before = await admin.fetchval("SELECT pg_catalog.pg_conf_load_time()")
    assert await admin.fetchval("SELECT pg_catalog.pg_reload_conf()")
    async def wait_for_reload():
        while await admin.fetchval(
            "SELECT pg_catalog.pg_conf_load_time()"
        ) <= before:
            await asyncio.sleep(0.02)
    await asyncio.wait_for(wait_for_reload(), timeout=5)


class AuthenticationLab:
    def __init__(self, config, backup_dir):
        self.config = config
        self.backup_dir = backup_dir
        self.token = uuid.uuid4().hex[:12]
        self.roles = {}
        self.password = secrets.token_urlsafe(24) + "-密'码:\\!"
        self._hba = None
        self._block = b""

    def options(self, policy, proxy, **overrides):
        options = self.config.connection_kwargs(
            host="127.0.0.1", port=proxy.local_port,
            user=self.roles[policy], password=self.password,
            passfile=self.backup_dir / "nonexistent-pgpass",
        )
        options.update(overrides)
        return options

    async def setup(self):
        if not ipaddress.ip_address(self.config.host).is_loopback:
            raise RuntimeError("HBA configuration requires a local KES instance")
        admin = await asynckb.connect(**self.config.connection_kwargs())
        try:
            hba_path = Path(await admin.fetchval("SHOW hba_file"))
            self._hba = hba_path.open("r+b")
            fcntl.flock(self._hba, fcntl.LOCK_EX | fcntl.LOCK_NB)
            original = self._hba.read()
            backup = self.backup_dir / f"{self.config.mode}-sys_hba.conf"
            backup.touch(mode=0o600, exist_ok=False)
            backup.write_bytes(original)
            rules = []
            for policy, (method, encryption, _) in POLICIES.items():
                role = f"apg_auth_{self.token}_{policy}"
                await admin.execute(
                    f"SET password_encryption = {_quote_literal(encryption)}"
                )
                await admin.execute(
                    f"CREATE ROLE {_quote_ident(role)} LOGIN PASSWORD "
                    f"{_quote_literal(self.password)}"
                )
                self.roles[policy] = role
                prefix = await admin.fetchval(
                    "SELECT left(rolpassword, 3) FROM pg_catalog.pg_authid "
                    "WHERE rolname = $1", role,
                )
                assert prefix == ("md5" if encryption == "md5" else "SCR")
                rules.append(
                    f"host {_quote_ident(self.config.database)} {role} "
                    f"127.0.0.1/32 {method}\n"
                )
            self._block = (
                f"# BEGIN asynckb auth test {self.token}\n"
                + "".join(rules)
                + f"# END asynckb auth test {self.token}\n"
            ).encode("utf-8")
            self._write_hba(self._block + original)
            errors = await admin.fetch(
                "SELECT line_number, error FROM pg_catalog.pg_hba_file_rules "
                "WHERE error IS NOT NULL"
            )
            assert not errors, errors
            await _reload(admin)
        finally:
            await admin.close()

    def _write_hba(self, data):
        self._hba.seek(0)
        self._hba.write(data)
        self._hba.truncate()
        self._hba.flush()
        os.fsync(self._hba.fileno())

    @asynccontextmanager
    async def rules(self, lines, *, reload=True):
        admin = await asynckb.connect(**self.config.connection_kwargs())
        marker = uuid.uuid4().hex
        block = (
            f"# BEGIN auth scenario {marker}\n" + "\n".join(lines)
            + f"\n# END auth scenario {marker}\n"
        ).encode("utf-8")
        self._hba.seek(0)
        current = self._hba.read()
        try:
            self._write_hba(block + current)
            if reload:
                errors = await admin.fetch(
                    "SELECT error FROM pg_catalog.pg_hba_file_rules "
                    "WHERE error IS NOT NULL"
                )
                assert not errors, errors
                await _reload(admin)
            yield admin
        finally:
            try:
                self._hba.seek(0)
                self._write_hba(self._hba.read().replace(block, b"", 1))
                if reload:
                    await _reload(admin)
            finally:
                await admin.close()

    async def cleanup(self):
        try:
            admin = await asynckb.connect(**self.config.connection_kwargs())
            try:
                if self._hba is not None and self._block:
                    self._hba.seek(0)
                    current = self._hba.read()
                    if self._block in current:
                        self._write_hba(current.replace(self._block, b"", 1))
                        await _reload(admin)
                for role in self.roles.values():
                    await admin.execute(f"DROP ROLE {_quote_ident(role)}")
            finally:
                await admin.close()
        finally:
            if self._hba is not None:
                self._hba.close()


@pytest.fixture(scope="session", params=("mysql", "oracle", "sqlserver"))
def auth_lab(request, tmp_path_factory):
    if not request.config.getoption("--kes-auth-configure-server"):
        pytest.skip("use --kes-auth-configure-server for the local HBA matrix")
    selected = request.config.getoption("--kes-mode")
    if selected not in ("all", request.param):
        pytest.skip(f"{request.param} excluded by --kes-mode={selected}")
    if not os.environ.get("ASYNCKB_KES_PASSWORD"):
        pytest.skip("set ASYNCKB_KES_PASSWORD")
    lab = AuthenticationLab(
        KESConfig.from_env(request.param), tmp_path_factory.mktemp("kes-auth")
    )
    try:
        asyncio.run(lab.setup())
        yield lab
    finally:
        asyncio.run(lab.cleanup())


@pytest.fixture(scope="session", params=("mysql", "oracle", "sqlserver"))
def isolated_kes(request, tmp_path_factory):
    yield from _isolated_instance(request, tmp_path_factory)


@pytest.fixture(scope="session", params=("mysql", "oracle", "sqlserver"))
def isolated_whitelist_kes(request, tmp_path_factory):
    yield from _isolated_instance(
        request, tmp_path_factory, preload=("src_restrict",),
    )


def _isolated_instance(request, tmp_path_factory, *, preload=()):
    if not request.config.getoption("--kes-auth-isolated"):
        pytest.skip("use --kes-auth-isolated for disposable KES instances")
    selected = request.config.getoption("--kes-mode")
    if selected not in ("all", request.param):
        pytest.skip(f"{request.param} excluded by --kes-mode={selected}")
    from tests.kes.authentication.isolated import IsolatedKES
    instance = IsolatedKES(
        request.param, tmp_path_factory.mktemp(f"kes-auth-{request.param}"),
        preload=preload,
    )
    try:
        instance.start()
        asyncio.run(instance.initialize())
        yield instance
    finally:
        instance.stop()
