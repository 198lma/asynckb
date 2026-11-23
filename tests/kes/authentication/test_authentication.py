"""Real KES authentication, including actual challenge/response selection."""

from __future__ import annotations

import asyncio

import asynckb
import pytest

from tests.kes.authentication.conftest import POLICIES
from tests.kes.authentication.wire import AuthenticationProxy


PASSWORD_POLICIES = (
    "scram", "md5", "md5_scram", "password_md5", "password_scram",
)
SUCCESS_POLICIES = (*PASSWORD_POLICIES, "trust")


def assert_exchange(proxy, expected, *, count=1):
    assert proxy.exchanges == [expected] * count
    if 10 in expected:
        assert proxy.mechanisms == [b"SCRAM-SHA-256"] * count
    else:
        assert proxy.mechanisms == []


@pytest.mark.case_id("KB-AUTH-002")
@pytest.mark.integration
@pytest.mark.parametrize("policy", SUCCESS_POLICIES)
def test_password_method_and_repeat_connection(auth_lab, policy):
    """测试点：实际算法与 HBA/密码存储组合一致，重复登录和查询正常。"""
    async def scenario():
        async with AuthenticationProxy(
            auth_lab.config.host, auth_lab.config.port
        ) as proxy:
            for _ in range(2):
                con = await asynckb.connect(**auth_lab.options(policy, proxy))
                try:
                    assert await con.fetchval("SELECT current_user") == (
                        auth_lab.roles[policy]
                    )
                    assert await con.fetchval(auth_lab.config.select_one) == 1
                    assert con.get_kes_mode() == auth_lab.config.mode
                finally:
                    await con.close()
            assert_exchange(proxy, POLICIES[policy][2], count=2)
    asyncio.run(scenario())


@pytest.mark.case_id("KB-AUTH-003")
@pytest.mark.integration
@pytest.mark.parametrize("policy", PASSWORD_POLICIES)
@pytest.mark.parametrize("credential", ("wrong", "missing", "empty"))
def test_password_methods_reject_invalid_credentials(
    auth_lab, policy, credential, monkeypatch,
):
    """测试点：错误、缺失和空密码不能绕过真实密码校验。"""
    monkeypatch.delenv("PGPASSWORD", raising=False)

    async def scenario():
        async with AuthenticationProxy(
            auth_lab.config.host, auth_lab.config.port
        ) as proxy:
            password = {
                "wrong": "not-the-test-password", "missing": None, "empty": "",
            }[credential]
            with pytest.raises(asynckb.InvalidPasswordError) as exc:
                con = await asynckb.connect(**auth_lab.options(
                    policy, proxy, password=password,
                ))
                await con.close()
            assert exc.value.sqlstate == "28P01"
            assert 0 not in proxy.exchanges[0]
            assert proxy.exchanges[0][0] == POLICIES[policy][2][0]
    asyncio.run(scenario())


@pytest.mark.case_id("KB-AUTH-004")
@pytest.mark.integration
def test_reject_rule_refuses_valid_password(auth_lab):
    """测试点：HBA reject 规则优先于正确凭证，不能建立会话。"""
    async def scenario():
        async with AuthenticationProxy(
            auth_lab.config.host, auth_lab.config.port
        ) as proxy:
            with pytest.raises(asynckb.InvalidAuthorizationSpecificationError):
                con = await asynckb.connect(
                    **auth_lab.options("reject", proxy)
                )
                await con.close()
            assert_exchange(proxy, [])
    asyncio.run(scenario())


@pytest.mark.case_id("KB-AUTH-005")
@pytest.mark.integration
def test_trust_does_not_request_password(auth_lab):
    """测试点：明确配置的 trust 不发送密码挑战，不误计为密码认证成功。"""
    async def scenario():
        async with AuthenticationProxy(
            auth_lab.config.host, auth_lab.config.port
        ) as proxy:
            con = await asynckb.connect(**auth_lab.options(
                "trust", proxy, password="intentionally-wrong",
            ))
            try:
                assert await con.fetchval(auth_lab.config.select_one) == 1
                assert_exchange(proxy, [0])
            finally:
                await con.close()
    asyncio.run(scenario())


@pytest.mark.case_id("KB-AUTH-006")
@pytest.mark.integration
@pytest.mark.parametrize("policy", PASSWORD_POLICIES)
@pytest.mark.parametrize("asynchronous", (False, True), ids=("sync", "async"))
def test_password_callback(auth_lab, policy, asynchronous):
    """测试点：同步/异步密码回调参与真实认证且每条连接调用一次。"""
    async def scenario():
        calls = []

        def sync_password():
            calls.append(1)
            return auth_lab.password

        async def async_password():
            calls.append(1)
            return auth_lab.password
        async with AuthenticationProxy(
            auth_lab.config.host, auth_lab.config.port
        ) as proxy:
            callback = async_password if asynchronous else sync_password
            con = await asynckb.connect(**auth_lab.options(
                policy, proxy, password=callback,
            ))
            try:
                assert await con.fetchval(auth_lab.config.select_one) == 1
                assert calls == [1]
                assert_exchange(proxy, POLICIES[policy][2])
            finally:
                await con.close()
    asyncio.run(scenario())


@pytest.mark.case_id("KB-AUTH-007")
@pytest.mark.integration
@pytest.mark.parametrize("policy", PASSWORD_POLICIES)
def test_password_file(auth_lab, policy, tmp_path, monkeypatch):
    """测试点：密码文件转义后的特殊字符/Unicode 密码仍能通过认证。"""
    monkeypatch.delenv("PGPASSWORD", raising=False)

    async def scenario():
        async with AuthenticationProxy(
            auth_lab.config.host, auth_lab.config.port
        ) as proxy:
            passfile = tmp_path / "pgpass"
            escaped = auth_lab.password.replace(
                "\\", "\\\\").replace(":", "\\:")
            passfile.write_text(
                f"127.0.0.1:{proxy.local_port}:{auth_lab.config.database}:"
                f"{auth_lab.roles[policy]}:{escaped}\n", encoding="utf-8",
            )
            passfile.chmod(0o600)
            con = await asynckb.connect(**auth_lab.options(
                policy, proxy, password=None, passfile=passfile,
            ))
            try:
                assert await con.fetchval(auth_lab.config.select_one) == 1
                assert_exchange(proxy, POLICIES[policy][2])
            finally:
                await con.close()
    asyncio.run(scenario())


@pytest.mark.case_id("KB-AUTH-008")
@pytest.mark.integration
@pytest.mark.parametrize("policy", PASSWORD_POLICIES)
def test_pool_reauthenticates_new_connections(auth_lab, policy):
    """测试点：并发池连接及过期后的新连接分别完成真实身份认证。"""
    async def scenario():
        async with AuthenticationProxy(
            auth_lab.config.host, auth_lab.config.port
        ) as proxy:
            async with asynckb.create_pool(
                **auth_lab.options(policy, proxy), min_size=0, max_size=2,
            ) as pool:
                async with pool.acquire() as first, pool.acquire() as second:
                    assert first.get_server_pid() != second.get_server_pid()
                    for con in (first, second):
                        assert await con.fetchval(
                            auth_lab.config.select_one
                        ) == 1
                await pool.expire_connections()
                async with pool.acquire() as con:
                    assert await con.fetchval(auth_lab.config.select_one) == 1
                assert_exchange(proxy, POLICIES[policy][2], count=3)
    asyncio.run(scenario())


@pytest.mark.case_id("KB-AUTH-009")
@pytest.mark.integration
@pytest.mark.parametrize("tamper, error, message",
                         (("signature",
                           asynckb.InterfaceError,
                           "could not verify server signature"),
                          ("nonce",
                           asynckb.InternalClientError,
                           "nonce"),
                             ("mechanism",
                              asynckb.InterfaceError,
                              "unsupported SASL Authentication methods"),
                          ))
def test_scram_refuses_invalid_server_authentication(
    kes_config, tamper, error, message,
):
    """测试点：真实 KES 交换中的伪造签名、错误 nonce 和未知机制被拒绝。"""
    async def scenario():
        async with AuthenticationProxy(
            kes_config.host, kes_config.port, tamper=tamper,
        ) as proxy:
            with pytest.raises(error, match=message):
                con = await asynckb.connect(**kes_config.connection_kwargs(
                    host="127.0.0.1", port=proxy.local_port,
                ))
                await con.close()
    asyncio.run(scenario())
