# asyncpg KES 适配测试方案

## 1. 测试目标

验证适配版 asyncpg 在 KingbaseES MySQL、Oracle 和 SQL Server 三种兼容模式下
能够正确使用原 asyncpg 公共能力，并正确处理各模式的语法、类型和事务差异。

本方案只验证 KES 兼容模式，不连接 PostgreSQL、官方 MySQL、官方 Oracle
或官方 Microsoft SQL Server。

## 2. 参考方案

内部参考资料 `Druid-test`、`测试方案.docx` 和
`完整 Druid 连接池配置体系.xmind` 按参数行为、边界、组合场景、插件和安全
场景组织测试。本项目沿用其分层思路，并针对异步驱动做以下映射；这些内部资料
不属于本仓库交付物：

| Druid 分类 | asyncpg KES 对应内容 |
| --- | --- |
| 参数行为 | DSN、service、passfile、连接参数、Pool 参数 |
| 边界 | Pool 容量、等待超时、缓存大小、类型及行数边界 |
| 场景 | COPY、事务、取消、竞态、断连恢复、资源清理 |
| 插件/框架 | SQLAlchemy、Alembic |
| 安全和错误 | 错误模式拦截、参数绑定、权限、异常映射 |

测试成功必须由返回值、异常类型、数据库状态和资源状态断言得出，不依赖控制台
文本判断。

Druid 配置项、asyncpg 公共 API、三模式专项能力和不适用项的逐项结果见
[功能覆盖矩阵](COVERAGE_MATRIX.md)。

## 3. 测试范围

### 3.1 范围内

- KES 模式解析、连接握手、DSN 和连接选项。
- Connection、Record、PreparedStatement、Cursor、Transaction API。
- Pool 创建、获取、释放、重连、容量、超时、回调、取消、并发和关闭。
- asyncpg 标准类型、数组、网络类型和 KES 三模式专有类型。
- 自定义 codec、schema cache 重载和 codec 重置。
- 普通、嵌套、只读、隔离级别事务及失败恢复。
- named statement、DEALLOCATE、GC 和 statement cache 生命周期。
- COPY records、CSV、TEXT、BINARY、异步 source/sink 及失败原子性。
- LISTEN/NOTIFY、查询超时、任务取消、认证失败和服务端异常映射。
- 错误凭证、关闭后使用、参数绑定安全和批处理失败原子性。
- 活动查询关闭/终止、连接并发冲突、客户端批处理失败和事务非法状态。
- 服务端终止空闲连接后的原生 Pool 重建和并发事务资源归还。
- 已有 `asynckes` schema 下的建表、写入、查询和清理。
- 原生 `async def` CRUD、连接池并发、异常回滚和任务取消工作流。
- SQLAlchemy 异步方言和 Alembic 迁移。
- SQLAlchemy 空目录、不存在对象和列反射异常契约。

### 3.2 当前环境不覆盖

- PostgreSQL、官方 MySQL、官方 Oracle。
- 多节点主备切换、负载均衡和真实故障转移。
- 双向 TLS、证书校验、GSSAPI/Kerberos 和 Unix socket。
- 长时间压力、性能基准及网络故障注入。
- 多 KES 补丁版本、Python 版本和操作系统组合矩阵。
- KES SQL Server V009R001C010 服务端不支持的计算列语法。
- KES Oracle 模式扩展协议参数不能用于 `CALL` 的 IN 参数；字面量 `CALL`
  正常，DML 返回值使用普通或批量 `RETURNING`。
- 当前 KES Oracle 实例不提供 `VARBINARY`，二进制场景使用 `BLOB`/`BYTEA`。
- KES MySQL 某些表达式会把未定型参数推断为 `text`，测试在此类位置使用
  `CAST($1 AS INT)` 明确参数类型。

这些能力需要对应基础设施后单独验证，不能由当前单机结果推断为已通过。

## 4. 测试结构

| 层级 | 目录 | 逻辑场景 | 参数化执行用例 |
| --- | --- | ---: | ---: |
| 单元 | `tests/kes/unit` | 23 | 31 |
| KES 核心集成 | `tests/kes/integration` | 107 | 276 |
| 框架集成 | `tests/kes/framework` | 20 | 48 |
| 合计 | `tests/kes` | 150 | 355 |

逻辑场景按测试函数统计；执行用例按 pytest 参数化展开后的节点统计。

| 模块 | 逻辑场景 | 执行用例 | 主要测试点 |
| --- | ---: | ---: | --- |
| `unit/test_driver_internals.py` | 23 | 31 | 模式、DSN、建连超时、Pool 边界、事务 SQL、codec 极值、方言输入与反射处理 |
| `integration/connection/test_connection_options.py` | 3 | 9 | service、passfile、密码回调、超时、多候选连接清理 |
| `integration/connection/test_connection_contracts.py` | 11 | 33 | 认证、Record、Cursor、中断/并发、事务状态、批处理原子性、安全绑定 |
| `integration/connection/test_statement_lifecycle.py` | 12 | 26 | statement、脚本、函数、过程 |
| `integration/api/test_public_api.py` | 16 | 46 | Connection、Record、Pool、资源清理 |
| `integration/pool/test_pool_resilience.py` | 8 | 24 | Pool 等待/查询/归还取消、关闭、断连重建、并发资源归还 |
| `integration/protocol/test_protocol_and_copy.py` | 22 | 62 | 握手、COPY、路径探测回退、通知、缓存、竞态 |
| `integration/schema/test_schema_objects.py` | 1 | 3 | 三模式 `asynckes` schema 建表 |
| `integration/types/test_types_and_transactions.py` | 25 | 46 | 类型矩阵、codec、domain/base 同步、事务、错误恢复 |
| `integration/types/test_advanced_types.py` | 4 | 12 | ENUM、DOMAIN、COMPOSITE、RANGE |
| `integration/workflows/test_async_crud.py` | 5 | 15 | 原生异步 CRUD、默认 schema、并发 Pool、异常和取消回滚 |
| `framework/test_sqlalchemy.py` | 19 | 45 | 方言、CRUD、fallback、批处理恢复、连接池、反射边界 |
| `framework/test_alembic.py` | 1 | 3 | 三模式迁移闭环 |

每个测试函数使用以“测试点：”开头的文档字符串说明验收行为。pytest 节点
ID 是唯一执行标识：

```text
<测试文件>::<测试函数>[mysql|oracle|sqlserver|参数ID]
```

完整清单始终从代码收集，避免文档与参数化用例失去同步：

```bash
ASYNCPG_KES_PASSWORD='<password>' ./run_kes_tests.sh all --collect-only -q
```

## 5. 环境矩阵

| 模式 | 地址 | 端口 | 用户 | 数据库 | 必需 schema |
| --- | --- | ---: | --- | --- | --- |
| KES MySQL | `127.0.0.1` | 54321 | `system` | `test` | `asynckes` |
| KES Oracle | `127.0.0.1` | 54322 | `system` | `test` | `asynckes` |
| KES SQL Server | `127.0.0.1` | 54323 | `system` | `test` | `asynckes` |

密码仅通过 `ASYNCPG_KES_PASSWORD` 注入。

| 环境变量 | 默认值 |
| --- | --- |
| `ASYNCPG_KES_HOST` | `127.0.0.1` |
| `ASYNCPG_KES_MYSQL_PORT` | `54321` |
| `ASYNCPG_KES_ORACLE_PORT` | `54322` |
| `ASYNCPG_KES_SQLSERVER_PORT` | `54323` |
| `ASYNCPG_KES_USER` | `system` |
| `ASYNCPG_KES_DATABASE` | `test` |

前置条件：

1. 三个 KES 实例可访问，端口对应的兼容模式正确。
2. `system` 可连接 `test`，并能创建和删除测试对象。
3. 三个 `test` 库都已存在 `asynckes` schema，且 `system` 可在其中建表。
4. 跨用户反射场景所需的 `CREATE USER` 权限已授予。
5. 当前源码树的 asyncpg C 扩展已编译，pytest、SQLAlchemy、
   Alembic 和 flake8 已安装。

## 6. 数据隔离和清理

- 动态对象统一由 `unique_object_name()` 生成，以 `apg_` 开头，包含模式和
  随机后缀。
- 每个场景使用 `try/finally` 关闭 Connection、Pool 和 Engine。
- 表、类型、过程、序列和测试用户由创建它们的场景负责删除。
- `asynckes` schema 是环境前置对象，测试只删除其中的测试表，不删除 schema。
- 失败恢复场景额外断言连接可继续查询，或旧服务端会话已经消失。
- 测试不得删除非 `apg_` 前缀对象。

## 7. 执行流程

### 7.1 静态检查和单元测试

```bash
cd <asyncpg-kes-repository>
./run_kes_tests.sh unit -q
flake8 tests/kes
python3 -m compileall -q tests/kes
```

预期：31 个单元执行用例通过，静态检查无错误。

### 7.2 分模式核心集成

先分别运行，以便定位模式差异：

```bash
ASYNCPG_KES_PASSWORD='<password>' ./run_kes_tests.sh integration --kes-mode mysql -q
ASYNCPG_KES_PASSWORD='<password>' ./run_kes_tests.sh integration --kes-mode oracle -q
ASYNCPG_KES_PASSWORD='<password>' ./run_kes_tests.sh integration --kes-mode sqlserver -q
ASYNCPG_KES_PASSWORD='<password>' ./run_kes_tests.sh integration -q
```

### 7.3 框架集成

```bash
ASYNCPG_KES_PASSWORD='<password>' ./run_kes_tests.sh framework -q
```

SQLAlchemy 和 Alembic 依赖缺失导致的 skip 在发布验证中视为失败。

### 7.4 完整回归

```bash
ASYNCPG_KES_PASSWORD='<password>' ./run_kes_tests.sh all -q
```

预期：355 个执行用例全部通过。

### 7.5 严格异步资源检查

```bash
PYTHONASYNCIODEBUG=1 ASYNCPG_KES_PASSWORD='<password>' \
python3 -X dev -W error::ResourceWarning -W error::RuntimeWarning \
-m pytest -q
```

预期：无未关闭连接、未等待协程、ResourceWarning 或 RuntimeWarning。

### 7.6 wheel 隔离验证

在干净虚拟环境或独立 target 目录中安装待发布 wheel。从源码树之外
执行 `tests/kes`，并将 wheel 安装目录放在 `PYTHONPATH` 最前，避免当前源码
遮蔽 wheel。记录 wheel 文件名、版本和 SHA256；源码与 wheel 结果必须一致。

### 7.7 数据库残留检查

在三个实例中检查名称以 `apg_` 开头的：

- `pg_class` 表、视图、序列和索引。
- `pg_type` 类型和 domain。
- `pg_proc` 函数和过程。
- `pg_roles` 测试用户。
- `pg_prepared_statements` 预编译语句。
- `pg_stat_activity` 测试会话。

完整回归后残留数量必须全部为 0。

## 8. 准入和退出标准

准入标准：

- 待测源码或 wheel 版本已经确定。
- 三套 KES 环境、兼容模式、权限和 `asynckes` schema 准备完成。
- 上轮遗留的 `apg_` 对象已经清理。

退出标准：

- 355 个执行用例全部通过，失败、错误、跳过均为 0。
- MySQL、Oracle、SQL Server 分模式运行均通过。
- 严格异步资源检查、静态检查和编译检查通过。
- 源码与隔离 wheel 测试结果一致。
- 三套 KES 测试资源残留均为 0。
- 当前环境不覆盖项已明确记录，不写成已验证。

## 9. 缺陷流程

1. 使用完整 pytest 节点 ID 固化复现命令。
2. 记录模式、版本、SQL、异常和服务端状态。
3. 按 `$diagnose` 先定位根因。
4. 按 `$tdd` 先增加稳定失败的最小回归用例，再修改驱动。
5. 依次执行单文件、单模式、三模式和完整回归。
6. 更新方案中的测试规模和未覆盖项。

## 10. 结果记录

每次发布至少记录日期、驱动版本、源码标识、wheel SHA256、KES 版本、执行
命令、通过/失败/跳过数量、耗时、资源检查结果、残留检查结果和未覆盖能力。

### 2026-07-30 验证记录

| 项目 | 结果 |
| --- | --- |
| 驱动版本 | `0.31.0.post12` |
| KES 版本 | 三模式均为 `V009R001C010` |
| 源码严格回归 | `340 passed in 34.67s` |
| wheel 严格回归 | `340 passed in 34.20s` |
| 适配 Python 变更行审计 | 三模式适用行 `1214/1214`；原始口径 `1214/1234` |
| `asyncpg/kes.py` 分支覆盖 | 语句和分支 `100%` |
| flake8 / compileall | 通过 |
| `apg*` 数据库残留 | 三模式均为 0 |
| wheel | `asyncpg_kes-0.31.0.post12-cp310-cp310-linux_x86_64.whl` |
| SHA256 | `ab1cee6f13b705950415de71c56a8b5c11cac4200211b9005f04e75bae724f95` |

变更行审计将 KES 版与官方 asyncpg 0.31.0 逐文件对比，再与三模式
Python 分支覆盖数据交叉。原始口径未命中的 20 行为 `kes_mode=None`
时的 PostgreSQL 原逻辑和被三模式前置返回挡住的方言兜底，不属于 KES
三模式验收路径。Cython 编译扩展不能用普通 Python coverage 精确记录，
通过 COPY 完成/活动期异常、超时、取消、服务端错误竞态及 Pool `max_queries`
行为间接验证。

### 2026-08-04 仓库内迁移验证

| 项目 | 结果 |
| --- | --- |
| 测试位置 | `asyncpg-0.31.0-kes/tests/kes` |
| pytest 默认收集 | 仅 KES 三模式，`355 tests collected` |
| 仓库内完整回归 | `355 passed in 29.40s` |
| 显式 `pytest tests` 回归 | `355 passed in 30.33s` |
| 严格异步资源回归 | `355 passed in 37.22s` |
| 单元测试 | `31 passed in 0.33s` |
| flake8 / compileall | 通过 |
| `apg_` / `APGDIR*` 残留 | 三模式均为 0 |

原 PostgreSQL 专用测试及其证书夹具已经删除；仓库 `tests` 目录中的可执行
测试全部面向 KES MySQL、Oracle 和 SQL Server 三种兼容模式。
