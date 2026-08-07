# asyncpg KES 功能覆盖矩阵

## 1. 目的和判定口径

本矩阵参考以下资料，并将 Druid/JDBC 能力映射到 asyncpg 的实际公共接口：

- 内部 `Druid-test` 测试方案
- 内部 `测试方案.docx`
- 内部 `完整 Druid 连接池配置体系.xmind`
- asyncpg 0.31.0 的 Connection、Pool、PreparedStatement、Cursor、Transaction
  和 Record 公共接口

状态含义：

| 状态 | 含义 |
| --- | --- |
| 已覆盖 | 三模式自动化测试包含明确返回值、异常或数据库状态断言 |
| 分模式覆盖 | 仅在支持该能力的 KES 模式执行，并验证不支持模式的明确行为 |
| 机制替代 | asyncpg 使用不同机制，测试对应的 Python 异步驱动合同 |
| 不适用 | Druid/JDBC 或服务端管理专属能力，asyncpg 没有该接口 |
| 待基础设施 | 驱动支持入口存在，但当前本地环境不能完成有效验收 |

“已覆盖”表示当前三套 `V009R001C010` 本地实例和本文记录的范围内通过，
不表示所有 KES 补丁版本、网络拓扑和操作系统组合均已验证。

## 2. Druid 配置体系映射

### 2.1 连接参数和会话

| Druid/XMind 测试点 | asyncpg KES 对应能力 | 状态 | 主要自动化场景 |
| --- | --- | --- | --- |
| `dbType` | `kes_mode` 解析、握手后模式核验 | 已覆盖 | 模式归一化、正确/错误模式连接 |
| `driverClassName` | asyncpg KES 包、版本和 C 扩展加载 | 机制替代 | 源码及隔离 wheel 回归 |
| `url` | DSN、百分号编码、多主机 | 已覆盖 | DSN、service、失效首地址回退 |
| `username/password` | KES 登录认证 | 已覆盖 | 正确凭证、错误用户名、错误密码 |
| `passwordCallback` | 同步/异步密码 callable | 已覆盖 | 两类回调建连和查询 |
| `connectProperties` | `server_settings`、DSN 查询参数 | 已覆盖 | `application_name` 透传与读取 |
| `connectionProperties` | `connect()` 关键字参数 | 机制替代 | SSL 模式、缓存、超时、目标会话属性 |
| `defaultAutoCommit` | asyncpg 显式事务；SQLAlchemy autocommit | 机制替代 | 手动事务、上下文事务、方言 autocommit |
| `defaultReadOnly` | `transaction(readonly=True)` | 已覆盖 | 三模式只读写入拒绝及连接恢复 |
| `defaultTransactionIsolation` | `transaction(isolation=...)` | 分模式覆盖 | 支持级别、嵌套事务及不支持选项 |
| `defaultCatalog/defaultSchema` | database、schema、限定对象名 | 已覆盖 | `test` 库、`asynckes` 和跨 owner 反射 |
| `Name` | `application_name` | 已覆盖 | 启动参数、DSN 和 Pool 重连参数 |
| `queryTimeout` | `command_timeout`、单次 `timeout` | 已覆盖 | 慢查询超时、连续超时、并发冲突及恢复 |
| `loginTimeout/connectTimeout` | `connect(timeout=...)` | 已覆盖 | 失效端点及多主机回退 |
| `ConnectionInitSqls` | Pool `init`/`setup` 回调 | 已覆盖 | 回调顺序、模式保持、失败清理 |

### 2.2 Pool 容量、缓存和生命周期

| Druid/XMind 测试点 | asyncpg KES 对应能力 | 状态 | 主要自动化场景 |
| --- | --- | --- | --- |
| `initialSize` | `min_size` 初始化物理连接 | 已覆盖 | 初始 size/idle 统计 |
| `maxActive` | `max_size` | 已覆盖 | 容量占满、等待超时、并发任务 |
| `minIdle` | `min_size` 预连接 | 机制替代 | 初始化下限和回收后按需重建 |
| `maxIdle` | 无独立上限，最多为 `max_size` | 不适用 | size/idle 上界及关闭归零 |
| `maxWait` | `acquire(timeout=...)` | 已覆盖 | 池满超时、等待取消、关闭期拒绝 |
| `poolPreparedStatements` | Connection statement cache | 机制替代 | 重复查询、named statement 和缓存复用 |
| `maxOpenPreparedStatements` | `statement_cache_size` | 已覆盖 | LRU 淘汰、禁用缓存及超长 SQL 排除 |
| 单连接 PS 缓存上限 | 每个物理 Connection 独立缓存 | 已覆盖 | Pool 重用、过期和 `DEALLOCATE ALL` |
| `phyMaxUseCount` | `max_queries` | 已覆盖 | 达到查询数后更换 PID 并重载 codec |
| `phyTimeoutMillis` | `max_inactive_connection_lifetime` | 已覆盖 | 空闲超时后更换 PID |
| `testOnBorrow` | Pool `setup` 或 SQLAlchemy `pool_pre_ping` | 机制替代 | setup、pre-ping 和真实终止恢复 |
| `testOnReturn` | Pool `reset` | 已覆盖 | 回滚事务、重置回调、release/查询取消保护 |
| `validationQuery` | 普通异步查询或 `pool_pre_ping` | 机制替代 | 三模式基础查询和失效连接替换 |
| `keepAlive` | 无 Druid 式后台探活线程 | 机制替代 | 空闲连接服务端终止后按需重建 |
| eviction 扫描参数 | 每连接定时器，不做批量扫描 | 机制替代 | 空闲生命周期和查询次数回收 |
| `removeAbandoned` | 不强制回收仍被业务持有的代理 | 不适用 | `async with`、等待取消和关闭等待 |
| `failFast` | `min_size > 0` 初始化即建连 | 机制替代 | 部分初始化、init 失败时全部清理 |
| 连接错误重试参数 | 无内置无限重试策略 | 机制替代 | 多主机回退、失败后由调用方重试 |
| `exceptionSorter` | 协议断连状态和异常分类 | 机制替代 | 服务端终止、异常映射和新连接替换 |
| `asyncCloseConnectionEnable` | 异步 `close()`、同步 `terminate()` | 已覆盖 | 正常关闭、活动命令中断、等待归还、强制终止 |
| `maxWaitThreadCount` | asyncio waiter 队列 | 机制替代 | 并发等待、取消后容量恢复 |

### 2.3 插件、监控和安全

| Druid/XMind 测试点 | asyncpg KES 对应能力 | 状态 | 说明 |
| --- | --- | --- | --- |
| WallFilter | 无客户端 SQL 防火墙 | 不适用 | 应由应用、网关或数据库权限策略实现 |
| StatFilter/监控页面 | 无 Druid 统计 Servlet | 不适用 | query logger 和服务端视图可供外部监控接入 |
| Log4jFilter | Python logging/query logger | 机制替代 | 成功和失败查询日志、监听器增删已覆盖 |
| ConfigFilter | DSN、环境、service、passfile | 机制替代 | 配置解析和密码回调已覆盖 |
| ResetStatFilter | 无驱动内建统计账本 | 不适用 | 不制造无实际产品接口的测试 |
| Parser/mergeSql | asyncpg 不提供 SQL AST 合并器 | 不适用 | 参数占位符和多语句边界由协议验证 |
| XAUtil | asyncpg 无 JDBC XA 接口 | 不适用 | 本地、嵌套和显式事务已覆盖 |
| SQL 注入 | `$n` 扩展协议参数绑定 | 已覆盖 | 注入载荷按原字符串落库，表保持完整 |
| SSL/TLS | `ssl`、`direct_tls` 参数入口 | 待基础设施 | 当前实例未提供可验证证书链 |
| RESTful API | 应用层 HTTP 能力 | 不适用 | 本项目验证数据库驱动，不构建 Web API |

## 3. asyncpg 公共 API 覆盖

| API 组 | 已覆盖接口和行为 | 主要测试模块 |
| --- | --- | --- |
| Connection 生命周期 | connect、close、terminate、reset、is_closed、活动命令中断、关闭后拒绝使用 | `integration/connection` |
| Connection 查询 | execute、executemany、fetch、fetchval、fetchrow、fetchmany、并发冲突 | `integration/api`、`integration/connection` |
| Connection 元数据 | settings、server PID/version、KES mode、reset query | `integration/api`、`integration/protocol` |
| 回调和通知 | LISTEN/NOTIFY、log/query/termination listener 增删 | `integration/api`、`integration/protocol` |
| PreparedStatement | 元数据、空结果、fetch、fetchval、fetchrow、fetchmany、executemany、cursor、explain/analyze | `integration/api`、`integration/connection` |
| Cursor | await cursor、fetch、fetchrow、forward、异步迭代、prefetch 边界 | `integration/api`、`integration/connection` |
| Transaction | 上下文、提交/回滚、非法状态、嵌套、只读、隔离、异常和取消恢复 | `integration/connection`、`integration/types`、`integration/workflows` |
| Record | 自定义类、索引、名称、映射、迭代、切片、比较、哈希 | `integration/api`、`integration/connection` |
| Pool 查询代理 | 六类查询方法和四类 COPY 方法 | `integration/api` |
| Pool 生命周期 | init/setup/reset、acquire/release、expire、close、terminate、上下文 | `integration/api`、`integration/pool` |
| Pool 韧性 | 容量、等待/查询/归还取消、失效代理、远端终止、回收、并发一致性 | `integration/api`、`integration/pool`、`integration/workflows` |
| 异步 CRUD | 原生 async test、DML 状态、fetch 系列、并发任务、异常和取消回滚 | `integration/workflows` |
| COPY | records、CSV、TEXT、BINARY、路径、异步 source/sink、失败竞态 | `integration/protocol` |
| Codec/类型 | 内建、自定义、tuple、domain、enum、array、composite、range | `integration/types` |
| Statement 生命周期 | cache 禁用/容量/长度/lifetime、named、DEALLOCATE、GC、schema 失效 | `integration/connection` |
| SQLAlchemy | 连接、fallback、Pool、事务、CRUD、RETURNING、反射、不存在对象异常、模式方言 | `framework/test_sqlalchemy.py` |
| Alembic | autogenerate、升级、降级和对象清理 | `framework/test_alembic.py` |

`asyncpg.cluster` 用于调用本机 PostgreSQL 的 `initdb`、`pg_ctl` 等二进制管理
测试集群，不是远程 KES 驱动适配能力，因此不纳入三模式测试。私有协议方法不作为
公共 API 逐项验收目标，但通过查询、COPY、取消、缓存和异常恢复场景间接覆盖。

## 4. 三模式专项覆盖

| 模式 | 专项能力 |
| --- | --- |
| MySQL | TINYINT、UNSIGNED、ENUM、SET、BIT、JSON、TIME duration、VARBINARY、事务语法、存储函数/过程、反射 |
| Oracle | NUMBER、DATE/TIMESTAMP、INTERVAL、ROWID/UROWID、BFILE、BLOB、identity、sequence、RETURNING、owner 反射、CALL 边界 |
| SQL Server | 整数/浮点/金额、字符、日期时间、UNIQUEIDENTIFIER、VARBINARY、事务/保存点、identity、TOP/OFFSET 和反射 |
| 三模式共同 | 连接、Pool、PreparedStatement、Cursor、Record、事务、COPY、通知、错误恢复、schema、SQLAlchemy、Alembic |

## 5. 当前明确未覆盖的基础设施场景

- 真实主备切换、读写角色变化和跨节点负载均衡。
- TLS 证书链、双向认证、GSSAPI/Kerberos 和 Unix socket。
- 断网、丢包、半开 socket、网络延迟注入；服务端主动终止会话已经覆盖。
- 长时间压力、吞吐/延迟基准和资源增长趋势；当前只有 24 任务并发正确性冒烟。
- 多 KES 补丁版本、多 Python 版本、多操作系统和不同 CPU 架构矩阵。
- 必须依赖 KES 服务端能力但当前版本不支持的语法，详见 `TEST_PLAN.md`。

上述项目不能由本地单机功能回归推断为通过，生产上线前应由对应环境专项验收。
