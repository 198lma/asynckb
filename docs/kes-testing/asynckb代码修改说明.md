# asynckb 代码修改说明

## 1. 对比范围与总体结论

本说明以官方 `asyncpg 0.31.0` 为代码基线，对比当前独立发行项目 `asynckb`。内容聚焦驱动源码、打包入口和三模式适配实现，不把 SQLAlchemy/Alembic 框架本身描述为驱动改造。

本次改造保留 asyncpg 的 asyncio 连接、PostgreSQL Wire Protocol、Parse/Bind/Execute、异步调度、连接池和基础 Codec 架构；新增 KES 模式识别及模式化差异处理，并将发行名、Python 导入名和 SQLAlchemy URL 调整为 `asynckb`。

```text
asynckb 原有异步驱动内核
        + KES 三模式检测、OID/Codec 和 SQL 适配
        + 连接、事务、预编译语句及协议边界修正
        + KingbaseES SQLAlchemy 异步方言
```

KES MySQL、Oracle 和 SQL Server 模式仍使用 PostgreSQL Wire Protocol。驱动没有另写一套网络协议或连接池，也不会自动把任意用户 SQL 翻译成目标模式语法。

## 2. 源码变化概览

| 类别 | 修改内容 | 主要位置 |
| --- | --- | --- |
| 独立包与命名空间 | 将 Python 包、Cython 扩展、构建入口、测试环境变量和方言入口统一为 `asynckb` | `asynckb/`、`setup.py`、`pyproject.toml`、CI 配置 |
| KES 差异规则 | 集中管理模式名、自动识别、占位符、类型/OID、Codec、事务 SQL 和语句释放识别 | `asynckb/kes.py` |
| 连接与语句生命周期 | 初始化模式检测和类型注册；同步 DEALLOCATE 与本地命名语句状态；支持参数方向元数据 | `connect_utils.py`、`connection.py`、`prepared_stmt.py` |
| 协议和执行边界 | 保留协议主流程，补充 KES 初始化计数、超时、参数描述和多返回结果错误处理 | `protocol/`、`protocol/codecs/`、`exceptions/` |
| 事务 | 按模式生成开始事务、隔离级别和保存点 SQL | `transaction.py`、`kes.py` |
| SQLAlchemy 方言 | 增加统一入口和 MySQL、Oracle、SQL Server 三种具体方言 | `asynckb/sa_dialect.py`、`setup.py` |
| 许可与交付 | 保留上游声明，加入独立发行说明、依赖许可文本、CI 和发布配置 | `LICENSE`、`NOTICE`、`LICENSES/`、`.github/` |

包目录由 `asyncpg/` 更名为 `asynckb/`，因此逐文件差异统计会把命名空间和上游修改标记计入大量文件。功能改造量应以本说明列出的行为差异为准，不应将所有重命名行数解释为新增驱动逻辑。

## 3. 连接初始化与模式识别

连接入口保留 asyncpg 的 `connect()`、`create_pool()`、DSN 和连接参数解析流程，增加可选 `kes_mode` 配置。未显式指定时，认证完成后由连接执行 `SHOW DATABASE_MODE`；显式指定时则校验实际服务端模式。识别为 KES 后，再查询当前连接可见的类型目录并按实际 OID 注册 Codec。初始化失败时连接会被关闭，不会以半初始化状态返回。

```python
async def _initialize_kes(self):
    if self._kes_mode is None:
        self._kes_mode = await self._detect_kes_mode()
        if self._kes_mode is None:
            self._drop_local_statement_cache()
            self._protocol.reset_queries_count()
            return

    rows = await self.fetch(
        kes.TYPE_LOOKUP_QUERY, timeout=protocol.NO_TIMEOUT)
    self._kes_codec_aliases, self._kes_codec_mirrors = \
        kes.register_codecs(
            self._protocol.get_settings(), rows, self._kes_mode)
```

模式和连接本地 OID 状态保存在物理连接中，避免连接池内不同服务端实例之间共享不正确的类型映射。SQL Server 模式的内省查询将 OID 数组等 PostgreSQL 类型名称调整为该模式可识别的目录类型。

## 4. 查询占位符、协议与类型处理

### 4.1 占位符和参数绑定

业务代码仍可使用 asyncpg 的 `$1`、`$2` 参数位置。KES 模式在 Parse 前将占位符转换为对应模式的绑定形式：MySQL `?`、Oracle `:1`、SQL Server `@p1`。词法扫描会忽略字符串、标识符、注释和 dollar-quoted 内容，避免把其中的 `$1` 当作绑定参数；SQL Server 已声明局部变量也不会被当作客户端参数改写。参数值仍通过原有 Bind 流程传递，不拼接进 SQL 文本。

```python
async def fetch_by_id(con, row_id):
    # 应用仍使用统一的 asyncpg 风格接口
    return await con.fetchrow(
        "SELECT id, name FROM demo WHERE id = $1", row_id)
```

模式化占位符处理集中在 `kes.rewrite_query()`，参数类型推导、编码、异步发送及结果读取继续由原查询执行路径负责。SQLAlchemy 方言对已知类型的绑定值补充适当的类型表达式，避免服务端将缺少类型上下文的绑定参数推导为不兼容类型。

### 4.2 动态 OID 与 Codec

KES 类型 OID 不能按 PostgreSQL 固定常量假设。连接初始化从当前服务端目录读取类型 OID、schema、类型名和基础类型信息，再注册模式对应的 Codec。已有 asyncpg 内建类型、复合类型、数组及自定义 Codec 流程继续复用；KES 特殊类型按服务端实际目录处理。

| 模式 | 代表差异 | 驱动处理 |
| --- | --- | --- |
| MySQL | `tinyint`、无符号整数、`bit`、`json`、较长或负值 `time` | 按连接发现的 OID 注册文本/二进制 Codec；时间值按 `time` 或 `timedelta` 编解码 |
| Oracle | `dsinterval`、`yminterval`、`rowid`、`urowid`、`bfile` | 注册 KES 实际存在的类型；标准日期时间和数值类型继续使用既有 Codec |
| SQL Server | `rowversion`、`money`、`smallmoney`、`uniqueidentifier`、字符及日期时间类型 | 使用实际 OID 注册 Codec；按其 wire format 转为 Python `bytes`、`Decimal`、`UUID`、日期时间等 |

未知类型不会无条件转成字符串；是否可编码仍取决于服务端返回的 OID 和已有类型内省结果。

## 5. 查询执行、参数方向与语句资源

### 5.1 查询接口与返回行数

`execute()`、`fetch()`、`fetchrow()`、`fetchval()`、`fetchmany()`、`executemany()`、`prepare()` 和 `PreparedStatement` 继续走 asyncpg 原有查询、参数绑定和结果解码流程。针对 KES MySQL 预编译执行中服务端返回行数超过内部 limit 的情况，驱动在返回前按接口 limit 截取，保持 `fetchrow()`、`fetchval()` 等调用的既有语义。

### 5.2 参数方向

KES 连接的 `prepare()` 增加可选 `parameter_modes`，按 `$1` 等绑定位置声明 `in`、`out` 或 `inout`。该信息在 Parse 阶段编码进参数 OID 元数据，业务值仍由 Bind 传递；参数类型由服务端解析。Oracle `CALL` 的自动识别只覆盖驱动能识别的调用形式，不意味着能从任意 SQL 自动推断输出方向。Oracle DML `RETURNING INTO` 同样通过显式输出方向进行绑定。

```python
stmt = await con.prepare(
    "CALL demo_proc($1, $2, $3)",
    parameter_modes=("in", "inout", "out"),
)
row = await stmt.fetchrow(2, 5, None)
```

测试覆盖三模式基础 `CALL` 输入/输出参数、Oracle 匿名块 DML `RETURNING INTO`。OUT/IN OUT 与过程多组查询结果同时返回的组合仍会出现 `ProtocolError`，不是已支持能力；SQL Server 函数的标量返回值应使用 `SELECT function(...)`，`CALL function(...)` 不作为取得标量结果的方式。

### 5.3 命名语句生命周期

KES 模式维护命名语句与当前 Python 语句对象之间的映射。成功执行 `DEALLOCATE name` 或 `DEALLOCATE ALL` 后同步本地对象及缓存状态；准备已跟踪的同名语句时检查服务端状态。延迟垃圾回收旧对象时还会核对对象身份，避免旧对象关闭后来创建的新语句。

## 6. 事务、连接池和异步协议边界

用户继续调用 `con.transaction()`；事务对象状态、提交、异常回滚和嵌套事务管理沿用 asyncpg。`kes.py` 根据当前模式生成内部 SQL：

| 操作 | MySQL | Oracle | SQL Server |
| --- | --- | --- | --- |
| 开启 | `START TRANSACTION` | 设置所需选项后 `START TRANSACTION` | `BEGIN TRANSACTION` |
| 创建保存点 | `SAVEPOINT name` | `SAVEPOINT name` | `SAVE TRANSACTION name` |
| 回滚到保存点 | `ROLLBACK TO SAVEPOINT name` | `ROLLBACK TO name` | `ROLLBACK TRANSACTION name` |
| 嵌套提交 | `RELEASE SAVEPOINT name` | 不发送释放命令 | 不发送释放命令 |

协议层仍通过 PostgreSQL Wire Protocol 处理认证、Parse、Bind、Execute、Sync、通知、COPY、超时和取消。局部修改主要修正 KES 初始化查询计数、无超时标记、COPY 异常/取消边界和参数类型描述；没有替换协议状态机。连接池仍复用原 `Pool` 和连接代理，补充初始化失败、异步取消和资源回收路径的清理。

## 7. SQLAlchemy 异步方言

源 asyncpg 没有 KES 三模式 SQLAlchemy 方言。本项目新增 `asynckb/sa_dialect.py`：统一入口在连接后读取驱动识别的模式，再使用 MySQL、Oracle 或 SQL Server 对应编译器、执行上下文、类型映射和目录反射逻辑。异步 DBAPI 适配器仍调用 `asynckb` Connection，不另建数据库连接实现。

```text
kingbase+asynckb://user:password@host:port/database
```

方言适配包括 KES SQL/DDL 编译、类型化绑定、事务隔离级别、RETURNING 行读取、连接池兼容及系统目录反射。任意原生 SQL 仍由应用按当前模式编写；驱动不会对 `Connection.execute()` 收到的 SQL 做通用 SQL 方言翻译。

## 8. 独立发行与许可证处理

发行名和 Python 导入名为 `asynckb`，SQLAlchemy URL 为 `kingbase+asynckb`。`setup.py`、构建配置、Cython 扩展模块名、CI、测试变量和文档示例均同步使用新名称，最低 Python 版本为 3.9。上游 asyncpg 的版权声明和许可证文本保留；新增 `NOTICE`、`UPSTREAM.md` 及第三方许可文本，用于说明派生来源和分组件许可证。

包改名不等于重新许可或删除上游归属。发布前仍需按 `docs/DELIVERY.md` 审查每个修改/改名的上游文件、源码归属声明及最终构建产物。

## 9. 测试对应关系与能力边界

当前测试代码按七个驱动模块组织：连接初始化、协议与异步调度、类型与 Codec、查询/事务/语句资源、连接池、SQLAlchemy 方言、认证。测试编号与源码用例一一对应，详见 `tests/kes/case_manifest.json` 和 `docs/kes-testing/TEST_CASE_INDEX.md`。

存储过程和多结果集测试用于确认明确场景及限制，不表示驱动实现了完整的过程语言或多结果集迭代 API。当前接口不提供 `nextset()`，OUT/IN OUT 与多结果集组合保留为已知限制测试。认证适配复用既有 PostgreSQL Wire Protocol 认证机制；仅对当前测试环境实际执行的认证方式得出通过结论，不从机制复用推断 LDAP、PAM、BSD 等所有服务端认证配置均可用。

完整三模式回归报告见 `docs/kes-testing/asynckb驱动兼容性测试报告.docx`。测试结论仅适用于报告记录的 KES 版本、Python 版本、操作系统和测试环境。

## 附录 A. 关键源码阅读索引

| 文件 | 阅读内容 |
| --- | --- |
| `asynckb/kes.py` | 模式识别/归一化、占位符扫描、类型发现与 Codec、事务 SQL、语句释放识别 |
| `asynckb/connect_utils.py` | `kes_mode` 参数从 connect、DSN 和 service 配置传入连接的过程 |
| `asynckb/connection.py` | 连接初始化、`parameter_modes`、查询执行、命名语句跟踪和 Codec API |
| `asynckb/transaction.py` | 原事务对象对模式化事务 SQL 的分派 |
| `asynckb/prepared_stmt.py` | 预编译查询结果行数保护和 PreparedStatement API |
| `asynckb/protocol/protocol.pyx` | 异步协议、超时、取消、COPY 和查询计数边界 |
| `asynckb/sa_dialect.py` | SQLAlchemy DBAPI 适配、统一入口和三模式方言 |
| `setup.py`、`pyproject.toml` | 发行名、包发现、扩展模块、方言入口和构建配置 |
