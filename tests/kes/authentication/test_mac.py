("""Client MAC upload is an auxiliary server request, """
 """not a password algorithm.""")

import asyncio

import asynckb
import pytest

from tests.kes.authentication.wire import AuthenticationProxy


@pytest.mark.case_id("KB-AUTH-017")
@pytest.mark.integration
@pytest.mark.parametrize("matches", (True, False), ids=("allow", "deny"))
def test_server_validates_uploaded_loopback_mac(isolated_kes, matches):
    """测试点：服务端验证实际上传的本地接口 MAC，匹配放行、不匹配拒绝。"""
    async def scenario():
        instance = isolated_kes
        mac = "00:00:00:00:00:00" if matches else "02:00:00:00:00:01"
        rule = (
            f'host "{instance.config.database}" {instance.role} '
            f"127.0.0.1/32 scram-sha-256 mac={mac}"
        )
        reject = (
            f'host "{instance.config.database}" {instance.role} '
            "127.0.0.1/32 reject"
        )
        async with instance.rules(rule, reject):
            async with AuthenticationProxy(
                instance.config.host, instance.config.port
            ) as proxy:
                options = instance.options(
                    port=proxy.local_port, password=instance.password,
                )
                if matches:
                    con = await asynckb.connect(**options)
                    try:
                        assert await con.fetchval(
                            instance.config.select_one
                        ) == 1
                        assert proxy.exchanges == [[19, 10, 11, 12, 0]]
                    finally:
                        await con.close()
                else:
                    with pytest.raises(
                        asynckb.InvalidAuthorizationSpecificationError
                    ):
                        con = await asynckb.connect(**options)
                        await con.close()
                    assert 0 not in proxy.exchanges[0]
                assert proxy.client_macs == [b"00:00:00:00:00:00"]
    asyncio.run(scenario())
