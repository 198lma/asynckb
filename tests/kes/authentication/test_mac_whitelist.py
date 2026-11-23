"""Exercise the documented SSO whitelist API, not a permissive fallback."""

import asyncio

import asynckb
import pytest

from tests.kes.authentication.conftest import _reload
from tests.kes.authentication.wire import AuthenticationProxy


@pytest.mark.case_id("KB-AUTH-023")
@pytest.mark.integration
@pytest.mark.parametrize('case', ('allow', 'wrong-mac', 'wrong-password'))
def test_limited_info_mac_whitelist(isolated_whitelist_kes, case):
    """测试点：sso MAC 白名单匹配才放行，且不能绕过后续密码认证。"""
    instance = isolated_whitelist_kes

    async def scenario():
        admin = await asynckb.connect(**instance.config.connection_kwargs())
        sso = None
        original = instance.hba.read_bytes()
        added = False
        mac = '02:00:00:00:00:01' if case == 'wrong-mac' else '00:00:00:00:00:00'
        limited_info = f'mac={mac}'
        try:
            # The API appends rules. No earlier TCP allow rule may mask it.
            instance.hba.write_text(
                'local all all trust\n'
                'host all system 127.0.0.1/32 scram-sha-256\n',
                encoding='ascii',
            )
            await _reload(admin)
            sso = await asynckb.connect(**instance.config.connection_kwargs(
                host=str(instance.socket_dir / f'.s.KINGBASE.{instance.port}'),
                user='sso', password=None,
            ))
            assert await sso.fetchval('SELECT current_user') == 'sso'
            assert await sso.fetchval(
                "SELECT src_restrict.add_rules(0, $1, '127.0.0.1', NULL, $2)",
                instance.role, limited_info,
            )
            added = True
            await _reload(admin)
            async with AuthenticationProxy('127.0.0.1', instance.port) as proxy:
                options = instance.options(
                    port=proxy.local_port,
                    password='wrong-password' if case == 'wrong-password' else instance.password,
                )
                if case == 'allow':
                    con = await asynckb.connect(**options)
                    try:
                        assert await con.fetchval(instance.config.select_one) == 1
                        assert proxy.exchanges == [[19, 10, 11, 12, 0]]
                    finally:
                        await con.close()
                else:
                    error = (
                        asynckb.InvalidPasswordError if case == 'wrong-password'
                        else asynckb.InvalidAuthorizationSpecificationError
                    )
                    with pytest.raises(error):
                        con = await asynckb.connect(**options)
                        await con.close()
                    expected = [19, 10, 11] if case == 'wrong-password' else [19]
                    assert proxy.exchanges == [expected]
                assert proxy.client_macs == [b'00:00:00:00:00:00']
        finally:
            try:
                if sso is not None:
                    try:
                        if added:
                            assert await sso.fetchval(
                                "SELECT src_restrict.remove_rules(0, $1, '127.0.0.1', $2)",
                                instance.role, limited_info,
                            )
                    finally:
                        await sso.close()
            finally:
                try:
                    instance.hba.write_bytes(original)
                    await _reload(admin)
                finally:
                    await admin.close()

    asyncio.run(scenario())
