# asyncpg KES MySQL/Oracle/SQL Server 三模式适配架构总结

## 1. 文档目的

本文档总结当前项目对 KingbaseES（KES）MySQL、Oracle 和 SQL Server
三种兼容模式的适配方案，说明：

- 原 asyncpg 框架的主体结构。
- KES 模式进入 asyncpg 的调用链路。
- PostgreSQL Wire Protocol 的复用方式和协议自解析流程。
- KES 类型动态发现和 Codec 注册机制。
- MySQL/Oracle/SQL Server 事务、PreparedStatement、COPY、Pool 等功能的适配方式。
- SQLAlchemy 异步方言的实现方式。
- 已完成的功能、测试结果和当前边界。

本文档对应当前源码实现。Oracle 风格 OUT bind 不属于 asyncpg API，当前通过普通和批量 RETURNING 提供 KES 支持的 DML 结果返回路径。

## 2. 设计结论

本次适配没有重新实现一个 KCI/libkci 驱动，也没有另建一套 `asynckes` 连接框架，而是在 asyncpg 原有异步驱动上增加 KES 兼容层：

```text
asyncpg 原有异步协议、连接池、事务、游标、COPY
                         +
              KES 模式识别和类型 Codec
                         +
          MySQL/Oracle/SQL Server 事务语法分派
                         +
        SQLAlchemy MySQL/Oracle/SQL Server 方言与反射
```

这种方案的核心优点是保留 asyncpg 已有的异步标准能力，适配代码集中在数据库差异位置，不改变 PostgreSQL 模式的默认行为。

## 3. 总体分层架构

```mermaid
flowchart TD
    A[业务代码] --> B[asyncpg.connect / create_pool]
    A --> C[SQLAlchemy AsyncEngine]

    B --> D[connect_utils.py]
    C --> E[KES SQLAlchemy Dialect]
    E --> F[SQLAlchemy asyncpg DBAPI Adapter]
    F --> D

    D --> G[Connection]
    G --> H[asyncpg Protocol Cython 层]
    H --> I[PostgreSQL Wire Protocol]
    I --> J[KingbaseES MySQL 模式]
    I --> K[KingbaseES Oracle 模式]
    I --> T[KingbaseES SQL Server 模式]

    G --> L[kes.py]
    L --> M[类型 OID 发现]
    L --> N[Codec 注册]
    L --> O[事务语句生成]

    E --> P[KESMySQLDialect_asyncpg]
    E --> Q[KESOracleDialect_asyncpg]
    E --> U[KESSQLServerDialect_asyncpg]
    P --> R[MySQL SQL 编译与目录反射]
    Q --> S[Oracle SQL 编译与目录反射]
    U --> V[SQL Server SQL 编译与目录反射]
```

### 3.1 分层职责

| 层次 | 主要文件 | 主要职责 |
| --- | --- | --- |
| API 层 | `asyncpg/connection.py`、`asyncpg/pool.py` | 提供连接、查询、事务、池、COPY、通知接口 |
| 连接参数层 | `asyncpg/connect_utils.py` | 解析 `kes_mode`、DSN、连接参数和初始化流程 |
| 模式适配层 | `asyncpg/kes.py` | 模式校验、类型发现、Codec、事务 SQL、DEALLOCATE 识别 |
| 协议层 | `asyncpg/protocol/protocol.pyx` | 异步 Wire Protocol 消息收发和解析 |
| 类型层 | `asyncpg/kes.py`、协议 Settings | 按 KES 类型 OID 注册 Python 编解码器 |
| 资源层 | `prepared_stmt.py`、`cursor.py`、`transaction.py` | PreparedStatement、游标、事务和保存点生命周期 |
| ORM/方言层 | `asyncpg/sa_dialect.py` | SQLAlchemy 编译、执行上下文、类型和元数据反射 |
| 测试层 | `tests/kes` | 仓库内三模式单元、集成、异步工作流和框架回归验证 |

## 4. 连接初始化流程

### 4.1 连接参数

支持的连接形式：

```python
import asyncpg

con = await asyncpg.connect(
    host="127.0.0.1",
    port=54321,
    user="system",
    password="your-password",
    database="test",
    kes_mode="mysql",
    ssl=False,
)
```

Oracle 模式只需更换端口和模式：

```python
con = await asyncpg.connect(
    host="127.0.0.1",
    port=54322,
    user="system",
    password="your-password",
    database="test",
    kes_mode="oracle",
    ssl=False,
)
```

DSN 形式：

```text
postgresql://system:your-password@127.0.0.1:54321/test?kes_mode=mysql&sslmode=disable
```

### 4.2 初始化时序

```mermaid
sequenceDiagram
    participant App as 应用
    participant Utils as connect_utils.py
    participant Conn as Connection
    participant Proto as Protocol
    participant KES as KingbaseES

    App->>Utils: connect() 使用原 asyncpg 参数
    Utils->>Utils: normalize_mode()
    Utils->>Proto: 建立异步 TCP 连接
    Proto->>KES: PostgreSQL StartupMessage
    KES-->>Proto: Authentication/ParameterStatus
    Proto-->>Conn: 连接建立
    Conn->>KES: SHOW DATABASE_MODE
    KES-->>Conn: MYSQL/ORACLE/MSSQL
    Conn->>KES: TYPE_LOOKUP_QUERY
    KES-->>Conn: type_oid/schema/type_name
    Conn->>Conn: register_codecs()
    Conn->>Conn: 清理初始化查询缓存
    Conn-->>App: 返回可用连接
```

实现入口：

- `asyncpg/connect_utils.py:863`：解析 `kes_mode`。
- `asyncpg/connect_utils.py:1157`：连接建立后执行 KES 初始化。
- `asyncpg/connection.py:127`：执行类型发现和 Codec 注册。

如果初始化失败，连接会关闭，不会将未完成 Codec 注册的连接返回给调用方。

## 5. 协议复用与自解析流程

### 5.1 协议层没有重写

KES 三个兼容模式仍然使用 PostgreSQL Wire Protocol，因此保留 asyncpg 原有的 Cython 协议层，继续解析：

```text
Authentication
ParameterStatus
RowDescription
DataRow
CommandComplete
ReadyForQuery
NotificationResponse
CopyInResponse
CopyOutResponse
```

查询过程如下：

```mermaid
sequenceDiagram
    participant App as asyncpg API
    participant Conn as Connection
    participant Proto as Cython Protocol
    participant KES as KingbaseES

    App->>Conn: fetch(query, args)
    Conn->>Proto: prepare/bind/execute
    Proto->>KES: Parse + Bind + Execute
    KES-->>Proto: RowDescription
    KES-->>Proto: DataRow
    KES-->>Proto: CommandComplete
    KES-->>Proto: ReadyForQuery
    Proto->>Proto: 解析消息和字段 OID
    Proto->>Proto: 根据 OID 查找 Codec
    Proto->>Proto: DataRow 转换为 Python 对象
    Proto-->>Conn: Record 列表
    Conn-->>App: 返回 Record
```

### 5.2 为什么协议复用可行

协议层关心的是：

```text
消息类型、长度、字段数量、字段 OID、字段数据、状态码
```

而不是 SQL 的具体方言。KES 兼容模式已经可以通过 PostgreSQL 协议返回这些消息，因此：

- 查询协议可以复用。
- PreparedStatement 协议可以复用。
- Cursor Portal 可以复用。
- COPY 协议可以复用。
- LISTEN/NOTIFY 可以复用。
- Cancellation 可以复用。

真正需要模式化处理的是 SQL 语法、目录查询和类型 Codec。

## 6. 动态类型发现与 Codec 注册

### 6.1 为什么需要动态发现

asyncpg 不是简单地根据字符串类型名转换结果，而是根据协议中的类型 OID 找到 Codec：

```text
RowDescription.type_oid
        |
        v
Protocol Settings Codec Map
        |
        v
Python encoder/decoder
```

KES 中部分类型的 schema、名称和 OID 与标准 PostgreSQL 不完全相同，因此不能直接使用 PostgreSQL 固定 OID。

### 6.2 类型查询

`asyncpg/kes.py:25` 定义了类型查询：

```sql
SELECT
    t.oid,
    n.nspname AS schema_name,
    t.typname AS type_name,
    t.typtype AS type_kind,
    base_ns.nspname AS base_schema_name,
    base.typname AS base_type_name
FROM pg_catalog.pg_type AS t
JOIN pg_catalog.pg_namespace AS n ON n.oid = t.typnamespace
LEFT JOIN pg_catalog.pg_type AS base ON base.oid = t.typbasetype
LEFT JOIN pg_catalog.pg_namespace AS base_ns
    ON base_ns.oid = base.typnamespace
WHERE n.nspname IN ('pg_catalog', 'sys')
  AND t.typname IN (
      'binary', 'varbinary', 'tinyint', 'uint4', 'uint8',
      'bpcharbyte', 'varcharbyte', 'bit', 'json', 'mysql_json',
      'date', 'time', 'datetime', 'timestamp',
      'datetime2', 'smalldatetime', 'uniqueidentifier',
      'money', 'smallmoney', 'nchar', 'nvarchar', 'rowversion',
      'dsinterval', 'yminterval', 'rowid', 'urowid', 'bfile'
  )
```

### 6.3 模式标志

```python
_MODE_MARKERS = {
    'mysql': {('sys', 'json'), ('sys', 'mysql_json')},
    'oracle': {('sys', 'dsinterval')},
    'sqlserver': {('sys', 'uniqueidentifier')},
}
```

连接到数据库后会校验模式标志：

```text
配置 kes_mode=mysql/oracle/sqlserver
    |
    +-- 优先校验服务端 compatdb_mode
    |
    +-- 服务端未提供该参数时校验对应类型标志
    |
    +-- 不匹配 -> 抛出 ClientConfigurationError
```

这可以防止错误模式连接成功后，直到业务查询时才出现难以定位的类型错误。

### 6.4 MySQL Codec

| KES 类型 | Python 类型 | 传输格式 |
| --- | --- | --- |
| `binary` | `bytes` | binary |
| `varbinary` | `bytes` | binary |
| `tinyint` | `int` | text |
| `uint4` | `int` | text |
| `uint8` | `int` | text |
| `bit` | `bytes`/字符串 | text |
| `json` / `mysql_json` | `str` | text |
| `date` | `datetime.date` | text |
| `time` | `datetime.time`/`timedelta` | text |
| `datetime` | `datetime.datetime` | text |
| `timestamp` | `datetime.datetime` | text |

MySQL `TIME` 允许超过 24 小时和负数，例如：

```text
25:01:02.123   -> datetime.timedelta
-25:01:02.123  -> -datetime.timedelta
```

MySQL 类型位置不是固定常量：驱动按连接发现结果兼容旧布局
`pg_catalog.tinyint` / `sys.mysql_json` 和当前布局
`sys.tinyint` / `sys.json`。当 `sys.json` 是 domain 时，自定义 codec
同时注册到 domain 输入 OID 和其基础输出 OID。

### 6.5 Oracle Codec

| KES 类型 | Python 类型 |
| --- | --- |
| `dsinterval` | `str` |
| `yminterval` | `str` |
| `rowid` | `str` |
| `urowid` | `str` |
| `bfile` | `str` |

Oracle 的 `NUMBER`、`DATE`、`TIMESTAMP`、`CLOB`、`BLOB`、`VARCHAR2`
等基础类型主要复用 asyncpg 已有基础 Codec，并通过 SQLAlchemy 反射层
映射为 Oracle 类型对象。当前测试实例不提供 `VARBINARY`，二进制数据使用
`BLOB` 或 `BYTEA`。

## 7. 事务适配

事务语句由 `asyncpg/kes.py` 统一生成，再由 `transaction.py` 调用。

### 7.1 MySQL 模式

```sql
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;
START TRANSACTION;
```

只读事务：

```sql
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;
START TRANSACTION READ ONLY;
```

保存点：

```sql
SAVEPOINT name;
ROLLBACK TO SAVEPOINT name;
RELEASE SAVEPOINT name;
```

支持：

```text
READ COMMITTED
READ UNCOMMITTED
REPEATABLE READ
SERIALIZABLE
```

不支持 `DEFERRABLE`。

### 7.2 Oracle 模式

```sql
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
START TRANSACTION;
```

只读事务：

```sql
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY;
START TRANSACTION;
```

保存点：

```sql
SAVEPOINT name;
ROLLBACK TO name;
```

Oracle 模式不发送：

```sql
RELEASE SAVEPOINT name;
```

嵌套事务提交时只保留外层事务状态。

Oracle 当前支持：

```text
READ COMMITTED
SERIALIZABLE
```

不支持：

```text
READ UNCOMMITTED
REPEATABLE READ
DEFERRABLE
```

## 8. PreparedStatement 生命周期

### 8.1 管理原因

KES 模式下用户可能直接执行：

```sql
DEALLOCATE statement_name;
DEALLOCATE ALL;
```

如果 asyncpg 本地状态不更新，会造成：

- 本地 statement 可用但服务端已删除。
- 同名 statement 无法重新创建。
- 旧对象回收时误关闭新对象。
- LRU 淘汰后服务端 statement 泄漏。

### 8.2 当前实现

连接对象维护：

```python
self._named_statements = {}
```

所有实际命名的 statement 都会登记，包括 asyncpg 自动生成的缓存名称。

LRU 流程：

```mermaid
flowchart LR
    A[创建 Statement] --> B[登记实际名称]
    B --> C[进入本地 Statement Cache]
    C --> D[LRU 淘汰]
    D --> E[加入待关闭队列]
    E --> F[发送 Close Statement]
    F --> G[移除本地名称]
```

手工 DEALLOCATE 会被 `kes.deallocated_statement()` 识别，并同步本地状态。

## 9. COPY、通知、游标和连接池

这些功能继续使用 asyncpg 原有协议层：

```text
COPY text
COPY CSV
COPY binary
LISTEN/NOTIFY
Cursor Portal
Connection Pool
Timeout
Cancellation
```

COPY 输入额外区分 bytes 内容和文件路径：

```python
await con.copy_to_table(
    'table_name',
    source=b'1\talpha\n',
)
```

bytes、bytearray、memoryview 会被作为 COPY 数据内容，不再被误判为文件路径。

## 10. SQLAlchemy 适配

### 10.1 SQLAlchemy 调用链路

```mermaid
sequenceDiagram
    participant App as SQLAlchemy 应用
    participant Engine as AsyncEngine
    participant Dialect as KES Dialect
    participant DBAPI as asyncpg DBAPI Adapter
    participant Conn as asyncpg Connection
    participant KES as KingbaseES

    App->>Engine: execute(statement)
    Engine->>Dialect: 编译 SQL
    Dialect->>Dialect: 选择 MySQL 或 Oracle 语法
    Dialect->>DBAPI: 执行 SQL
    DBAPI->>Conn: asyncpg 调用
    Conn->>KES: PostgreSQL Wire Protocol
    KES-->>Conn: DataRow/CommandComplete
    Conn-->>DBAPI: Record
    DBAPI-->>App: SQLAlchemy Result
```

### 10.2 MySQL 方言

类：

```python
KESMySQLDialect_asyncpg
```

继承：

```python
_KESAsyncpgDialectMixin
MySQLDialect
```

支持：

- MySQL SQL 编译。
- `AUTO_INCREMENT`。
- `LIMIT/OFFSET`。
- `ON DUPLICATE KEY UPDATE`。
- `LAST_INSERT_ID()`。
- MySQL 类型、ENUM、SET、BIT 反射。
- Generated Column 反射。
- 主键、唯一约束、外键、索引、表注释反射。
- server-side cursor。

### 10.3 Oracle 方言

类：

```python
KESOracleDialect_asyncpg
```

继承：

```python
_KESAsyncpgDialectMixin
OracleDialect
```

支持：

- Oracle SQL 编译。
- Oracle 类型映射。
- Identity。
- Computed/Generated Column。
- Sequence。
- 主键、唯一约束、外键、CHECK、索引反射。
- 列注释、表注释反射。
- 流式查询和 server-side cursor。
- 单行 INSERT/UPDATE/DELETE RETURNING。

Oracle 反射使用：

```text
ALL_TAB_COLUMNS
ALL_CONSTRAINTS
ALL_CONS_COLUMNS
ALL_INDEXES
ALL_IND_COLUMNS
ALL_SEQUENCES
ALL_TAB_COMMENTS
```

### 10.4 Oracle RETURNING

KES Oracle 模式支持普通结果集形式：

```sql
INSERT INTO users(name) VALUES ($1) RETURNING id;
```

不支持：

```sql
INSERT INTO users(name) VALUES ($1) RETURNING id INTO $2;
```

因此 `_KESOracleCompiler` 会去掉 Oracle 原生编译器生成的 `INTO` 绑定形式，保留普通 RETURNING 结果集。

SQLAlchemy 示例：

```python
result = await connection.execute(
    users.insert().values(name='alpha').returning(users.c.id)
)
new_id = result.scalar_one()
```

多个参数集可以直接使用 asyncpg：

```python
rows = await con.fetchmany(
    'INSERT INTO users(name) VALUES ($1) RETURNING id',
    [('alpha',), ('beta',)],
)
```

SQLAlchemy 批量 RETURNING 会在 DBAPI 适配层转换为
`PreparedStatement.fetchmany()`：

```python
result = await connection.execute(
    users.insert().returning(users.c.id),
    [{'name': 'alpha'}, {'name': 'beta'}],
)
ids = result.scalars().all()
```

## 11. 目录反射表达式清洗

KES 目录中的部分默认值、生成列表达式和 CHECK 条件会带 PostgreSQL 风格类型转换：

```text
(amount * 2::numeric)
CHECK ((amount >= (0)::numeric))
```

Oracle SQLAlchemy 方言增加 `_kes_oracle_expression()`，将其清理为可复用表达式：

```text
(amount * 2)
(amount >= (0))
```

实现位置：

```text
asyncpg/sa_dialect.py:34
asyncpg/sa_dialect.py:245
asyncpg/sa_dialect.py:654
```

## 12. 典型使用场景

### 12.1 asyncpg MySQL 模式

```python
con = await asyncpg.connect(
    host='127.0.0.1',
    port=54321,
    user='system',
    password='your-password',
    database='test',
    kes_mode='mysql',
    ssl=False,
)

try:
    async with con.transaction(isolation='read_committed'):
        await con.execute(
            'CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(40))')
        await con.execute(
            'INSERT INTO users VALUES ($1, $2)', 1, 'alpha')
finally:
    await con.close()
```

### 12.2 asyncpg Oracle 模式

```python
con = await asyncpg.connect(
    host='127.0.0.1',
    port=54322,
    user='system',
    password='your-password',
    database='test',
    kes_mode='oracle',
    ssl=False,
)

try:
    row = await con.fetchrow(
        'SELECT id, name FROM users WHERE id = $1', 1)
finally:
    await con.close()
```

### 12.3 SQLAlchemy Oracle 模式

```python
from sqlalchemy import Column, Identity, Integer, MetaData, String, Table
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    'kingbase_oracle+asyncpg://system:your-password@127.0.0.1:54322/test')

metadata = MetaData()
users = Table(
    'users', metadata,
    Column('id', Integer, Identity(), primary_key=True),
    Column('name', String(40), nullable=False),
)

async with engine.begin() as connection:
    await connection.run_sync(metadata.create_all)
    result = await connection.execute(
        users.insert().values(name='alpha').returning(users.c.id))
    print(result.scalar_one())
```

## 13. 测试验证结果

KES 专项测试位于本仓库：

```text
tests/kes
```

覆盖：

- 模式校验和 DSN。
- 动态 Codec 注册。
- MySQL TIME、BIT、二进制类型。
- Oracle NUMBER、INTERVAL、BLOB/BYTEA、Identity。
- PreparedStatement 和 LRU 回收。
- 手工 DEALLOCATE。
- Cursor。
- Transaction 和 Nested Transaction。
- Timeout 和 Cancellation。
- Pool。
- COPY text/CSV/binary 导入导出往返。
- LISTEN/NOTIFY。
- SQLAlchemy CRUD、RETURNING、流式查询和反射。
- MySQL/Oracle/SQL Server 常用类型矩阵。
- Oracle 跨 owner 反射。
- SQLAlchemy `executemany + RETURNING`。
- Alembic autogenerate、upgrade 和 downgrade。
- 多地址故障回退和 TLS prefer 协商回退。

当前仓库内验收测试结果：

```text
三模式源码完整测试：355 passed
严格 asyncio 资源测试：355 passed
隔离 wheel 测试：355 passed
flake8：passed
compileall：passed
```

当前发布版本为 `0.31.0.post12`。发布工作流会为每次正式
发布重新生成 wheel 和 `SHA256SUMS`，不在源码文档中固定记录
某个本地构建产物的摘要。

上述测试由 `tests/kes` 直接连接 KES 三模式执行，不依赖
`pg_config` 或 `initdb`。测试集覆盖 executemany、PreparedStatement、
Cursor、COPY、Pool、类型、事务、SQLAlchemy 和 Alembic；需要自建 PostgreSQL
集群或断言 PostgreSQL 专属语义的测试不纳入 KES 验收集。

## 14. 已知边界

当前实现的明确边界如下：

1. asyncpg 不自动翻译 SQL，业务 SQL 必须使用当前 KES 模式语法。
2. 三种兼容模式的数据库语义不会被伪装成 PostgreSQL 语义。
3. Oracle 风格 OUT bind 不属于 asyncpg API，当前 KES 实例也拒绝
   `RETURNING INTO`；已支持普通和批量 `RETURNING`。
4. 当前 Oracle 模式拒绝 `CALL` 的扩展协议 IN 参数，字面量 `CALL` 可用。
5. 当前 Oracle 模式不提供 `VARBINARY`，二进制数据使用 `BLOB`/`BYTEA`。
6. 当前 SQL Server 模式不支持已测试的计算列语法。
7. MySQL 模式无法推断部分未定型参数时，需要显式 `CAST`。
8. 已验证多地址故障回退，但本地无 KES 主备集群，未验证真实节点切换。
9. 已验证 `ssl=prefer` 在服务端未开启 TLS 时的协商回退；三个本地 KES
   实例均未启用 TLS，因此未验证证书和加密链路。

## 15. 文件修改关系

```text
asyncpg/connect_utils.py
    添加 kes_mode 参数、DSN 解析和连接初始化入口

asyncpg/connection.py
    添加 KES 初始化、动态 Codec 注册、DEALLOCATE 同步、Statement 生命周期管理

asyncpg/kes.py
    添加 KES 模式、类型查询、Codec、事务 SQL 和时间类型处理

asyncpg/transaction.py
    根据 MySQL/Oracle/SQL Server 模式生成事务和保存点语句

asyncpg/protocol/protocol.pyx
    保持原协议解析，仅补充 KES 初始化所需的超时和查询计数处理

asyncpg/prepared_stmt.py
    补充 MySQL 模式 PreparedStatement 行限制

asyncpg/introspection.py
    修复 KES 递归类型查询中的整数类型推导问题

asyncpg/sa_dialect.py
    添加 MySQL/Oracle/SQL Server SQLAlchemy 异步方言、编译器、执行上下文和目录反射

tests/kes
    与驱动源码同仓维护三模式单元、集成和框架测试
```

## 16. 总结

当前适配的核心不是重写 asyncpg，而是把 KES 的差异集中到适配边界：

```text
连接参数差异       -> connect_utils.py
类型和 OID 差异    -> kes.py
事务语法差异       -> transaction.py + kes.py
Statement 生命周期 -> connection.py
SQLAlchemy 方言差异 -> sa_dialect.py
协议通信           -> 继续复用 asyncpg protocol.pyx
```

因此，当前框架可以继续使用原 asyncpg 的异步 API 连接对应 KingbaseES 实例，驱动会在认证后自动识别 MySQL、Oracle 或 SQL Server 兼容模式，并使用主要的连接、查询、事务、游标、连接池、COPY、通知和 SQLAlchemy 功能。`kes_mode` 仍可作为可选的显式模式校验参数。
