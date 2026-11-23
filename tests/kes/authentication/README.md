# 认证与 MAC 上传专项

本目录对应第七个模块“用户认证与 MAC 信息上传”，与六个适配模块一起验收。
使用真实 KES 实例和真实认证协议，不以模拟服务器的握手成功代替数据库登录成功。
实测环境、结果及限制见 [认证验证记录](../../../docs/kes-testing/AUTHENTICATION_RESULTS.md)。

## 测试内容

| 文件 | 覆盖内容 |
| --- | --- |
| `test_authentication.py` | SCRAM、MD5、Cleartext、trust、拒绝规则、错误/缺失/空密码、回调、密码文件、连接池重新认证、SCRAM 签名/nonce/机制篡改拒绝 |
| `test_external_authentication.py` | LDAP/RADIUS 正误密码、cert 证书身份、peer/ident 身份 |
| `test_mac.py` | HBA MAC 匹配放行、不匹配拒绝，同时记录实际上传值和后续 SCRAM 握手 |
| `test_mac_whitelist.py` | 使用内置 sso 调用 `src_restrict.add_rules(..., limited_info)`，匹配放行、错误 MAC/密码拒绝 |
| `test_mac_address.py` | 实际 Linux 出站网卡发现；回环上传与匹配由真实 HBA／SSO 用例覆盖 |

MAC 是客户端信息上传，不是独立的密码认证算法。白名单测试没有早于测试规则的
宽泛 TCP allow 规则，防止未匹配 MAC 却通过其他规则登录的假阳性。
回环连接应上传 `00:00:00:00:00:00`，不应伪装为其他物理网卡地址。

## 现有实例专项

只在本机测试实例上运行，不应指向生产实例。需要可创建角色、读取密码存储前缀、
读取/修改 HBA 文件、重载配置的测试管理员权限。
配置入口仍是 `tests/kes/support/config.py` 的 `ASYNCKB_KES_*` 环境变量。

```bash
ASYNCKB_KES_PASSWORD='<测试实例密码>' PYTHONPATH=. \
python3 -m pytest -q --assert=rewrite \
  tests/kes/authentication/test_authentication.py \
  tests/kes/authentication/test_mac_address.py \
  --kes-auth-configure-server -o junit_family=legacy
```

此命令为三模式创建唯一临时测试角色和仅限这些角色的 HBA 规则；密码存储设置
仅作用于管理会话。HBA 会先备份并加文件锁，正常退出/断言失败时仅移除本次规则，
保留其他修改并删除临时角色，不改变已有用户密码。不要强制 kill -9 测试进程。
若异常断电，检查 pytest 临时目录的受限备份和 `# BEGIN asynckb auth test` 标记，
人工移除对应规则、重载并清理相应临时角色。
代理只记录认证请求编号、SASL 机制和 MAC，不记录密码、密码散列或 SCRAM 证明。

## 隔离外部认证专项

需要本机 Linux、可用的用户/网络命名空间、`unshare`、`iproute2` 及三模式 KES
安装文件。服务仅绑定隔离网络内的回环地址；不修改 `/etc/pam.d`、宿主机低端口
策略或现有数据库配置。不需要现成 LDAP/RADIUS/ident 服务或业务证书。

```bash
python3 -m pip install -r tests/kes/authentication/requirements.txt
PYTHONPATH=. python3 -m tests.kes.authentication.run_isolated \
  --junitxml=docs/_static/kes-testing/authentication-isolated-results.xml \
  -o junit_family=legacy
```

运行器在新网络命名空间内开放 ident 的 113 端口，再切换非 root 身份执行 initdb。
通过 `--kes-mode mysql` 等参数可只测一种模式。若系统禁止用户命名空间，
可在具有 113 端口权限的专用测试容器中直接执行上述三个测试文件并传入
`--kes-auth-isolated`；否则 ident 明确跳过，不可列为已验证。

默认安装路径见 `isolated.py`，可用 `ASYNCKB_KES_MYSQL_BIN`、
`ASYNCKB_KES_ORACLE_BIN`、`ASYNCKB_KES_SQLSERVER_BIN` 指定对应 `bin` 目录。
每种模式创建独立临时数据目录、随机端口、测试账号和有效期一天的临时证书，
退出时停止实例。Oracle 加载该构建启动所必需的 `plsql`，白名单专用实例另加载
`src_restrict`。sso 仅使用这些新建实例自带的安全管理员身份，通过临时实例本地
trust socket 登录，不需要也不修改现有实例的 sso 密码。

LDAP 使用 `ldapserver` 提供实际 Bind 协议端点；RADIUS 使用 `pyrad` 提供实际
UDP Access-Request/Accept/Reject 服务。外部服务密码故意与数据库密码不同，
同时核对服务端实际接到的请求，避免误走数据库密码认证。
它们用于协议兼容测试，不代表企业 LDAP 目录、RADIUS 集群或生产证书的完整验收。

三套 KES 均在解析 HBA 时报告不支持 PAM，已从当前测试集删除 PAM 正误密码
登录用例（原编号 `KB-AUTH-014`，三模式共 6 项），不再保留无法执行的跳过项。
PAM／BSD 的环境可用性检查也已退出活动测试清单，不把配置拒绝当作登录通过。
当前 Linux 构建不具备这些登录场景的验证条件，未列为已支持认证能力。

2026-11-19 精简后认证模块保留 15 个测试点、187 个参数化节点，全部实际执行通过。
其中独立命名空间执行 48 项，其他 139 项随现有实例批次执行。

## 默认与清理

普通 `python3 -m pytest tests/kes` 不会修改 HBA 或启动新实例；相关专项默认跳过。
MAC 上传仅实现 Linux 接口发现，其他操作系统目前明确报错；Unix peer 测试使用
完整 `.s.KINGBASE.<port>` 路径，不把目录路径当成已实现的 KES socket 自动探测。
临时数据和证书留在权限受限的 pytest 临时目录供诊断，不用于生产。
