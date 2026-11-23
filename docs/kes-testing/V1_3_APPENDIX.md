# 10 V1.3 补充验收与交付基线

## 10.1 修订说明

本章记录的提交和 Wheel 摘要保留为 2026-09-20 历史评审基线，不代表后续源码改动已进入该 Wheel。测试现已按需求模块重组为六个目录；当前用例数量以 `./run_kes_tests.sh all --collect-only -q` 的实时收集结果为准。

当前 SQLAlchemy 只发布统一入口 `kingbase+asynckb`。驱动连接认证后执行 `SHOW DATABASE_MODE`，统一方言读取 `get_kes_mode()` 并切换到 MySQL、Oracle 或 SQL Server 内部方言；不再注册 `kingbase_mysql+asynckb`、`kingbase_oracle+asynckb`、`kingbase_sqlserver+asynckb` 三个旧入口，也不由 URL 固定注入 `kes_mode`。

| 项目 | V1.3 当前基线 |
|---|---|
| 驱动版本 | `0.31.0.post12` |
| 源码提交 | `bac557c4be9106925defffbfa6c60da48e77ee01` |
| 测试目录 | `tests/kes` |
| 测试结构 | 6 个模块目录、6 个 `test_*.py` 文件 |
| 逻辑用例 | 165 个 `test_*` 函数 |
| 执行节点 | 当前收集 389 个节点 |
| 测试源码清单 SHA256 | `ba2dfed74bdb977608865480e66a141271d1ecf2305a86f5fee3679dbcfd75a5` |
| 交付 Wheel | `asynckb-0.31.0.post12-cp310-cp310-linux_x86_64.whl` |
| Wheel SHA256 | `ef58e0596ee8e2b87c03dcfc9218ff4f32920e1fa06ddb13f8a7c0f65ce4552e` |

## 10.2 测试规模与模块增量

| 需求模块 | 逻辑用例 | 执行节点 | 测试文件 |
|---|---:|---:|---|
| 连接与模式初始化 | 7 | 15 | `connection_initialization/test_connection_initialization.py` |
| 协议自解析与异步调度 | 23 | 71 | `protocol_and_async/test_protocol_and_async.py` |
| 类型 OID 与 Codec | 40 | 69 | `types_and_codecs/test_types_and_codecs.py` |
| 查询执行、事务与语句资源 | 38 | 89 | `execution_transactions_statements/test_execution_transactions_statements.py` |
| 连接池 | 25 | 77 | `pool/test_pool.py` |
| SQLAlchemy 异步方言与 Alembic | 32 | 68 | `sqlalchemy_dialect/test_sqlalchemy_dialect.py` |
| 合计 | 165 | 389 | 发布验收要求依赖齐全且 skipped=0 |

2026-09-20 的 160/373 是历史执行基线；当前目录结构和数量以六模块实时收集结果为准。pytest 节点 ID 是稳定标识，源码行号可能随维护变化。下表保留的是当时相对旧测试集的增量记录，不作为当前模块清单。

| 编号 | 源码测试函数 | 文件及当前行 | 节点 | 测试场景与明确预期 |
|---|---|---|---:|---|
| UT-DI-024（修订） | `test_oracle_call_detection` | `test_protocol_and_async.py` | 9 | 识别 Oracle CALL 与前置注释，为参数方向扩展选择正确解析路径；不误处理其他模式或普通查询。 |
| UT-DI-025 | `test_sqlserver_datetime2_default_precision_decodes_to_microseconds` | `test_types_and_codecs.py` | 1 | SQL Server DATETIME2 默认 7 位小数秒按 Python 6 位微秒精度稳定解码。 |
| UT-DI-026 | `test_sqlserver_smallmoney_uses_discovered_oid_and_decimal_codec` | `test_types_and_codecs.py` | 1 | SMALLMONEY 使用动态发现的真实 OID 和 Decimal Codec，不依赖错误的固定 OID。 |
| UT-DI-027 | `test_sqlalchemy_unified_connection_url_leaves_mode_for_driver_detection` | `test_sqlalchemy_dialect.py` | 1 | 统一 `kingbase+asynckb` URL 不注入固定模式，模式由驱动连接后识别。 |
| UT-DI-028 | `test_sqlalchemy_legacy_mode_url_entries_are_not_registered` | `test_sqlalchemy_dialect.py` | 3 | 三个旧显式 URL entry point 均不可加载，防止业务继续依赖已删除入口。 |
| UT-DI-029 | `test_sqlalchemy_unified_dialect_selects_detected_mode` | `test_sqlalchemy_dialect.py` | 3 | 统一方言根据驱动探测结果选择三个具体方言类。 |
| UT-DI-030 | `test_sqlalchemy_unified_dialect_rebuilds_mode_specific_components` | `test_sqlalchemy_dialect.py` | 3 | 切换后重建编译器、类型编译器和绑定 CAST，不能残留 PostgreSQL 占位组件。 |
| IT-OPT-005 | `test_connection_detects_kes_mode_without_explicit_option` | `test_connection_initialization.py` | 3 | 三模式省略 `kes_mode` 后均能通过服务端自动识别并执行基础查询。 |
| IT-TYP-027 | `test_sqlserver_money_round_trips_as_decimal` | `test_types_and_codecs.py` | 1 | SQL Server MONEY/SMALLMONEY 往返保持 Decimal 类型和值。 |
| FW-SA-021 | `test_sqlalchemy_unified_url_detects_and_loads_mode_dialect` | `test_sqlalchemy_dialect.py` | 3 | 同一 `kingbase+asynckb` URL 在三个端口上自动切换到 mysql/oracle/mssql 方言。 |

## 10.3 存储过程、OUT 与 INOUT 验收矩阵

asynckb 公共 API 采用位置参数和查询结果返回值，不提供 JDBC `CallableStatement` 式 OUT 参数注册接口。因此不能把“没有 OUT bind API”写成驱动缺陷，也不能把未验证的服务端行为写成已支持。验收必须区分字面量 CALL、扩展协议绑定、函数查询、结果集和 DML RETURNING。

| 模式 | 当前自动化覆盖 | 当前结论 | 补充验收要求 | 状态/优先级 |
|---|---|---|---|---|
| MySQL | 参数化存储函数、无参存储过程 | 已支持当前测试路径 | 增加带 IN 参数过程以及 OUT/INOUT 的服务端可用写法；若只能通过会话变量或结果集获取，明确示例和事务边界 | 待补，P0 |
| Oracle | 参数化 CALL 的 IN、纯 OUT、混合 IN/OUT/IN OUT；预编译、批量调用、缓存开关、NULL、事务恢复、多结果集和 SYS_REFCURSOR | Parse 扩展报文携带参数方向；驱动以查询结果行返回 OUT 值。没有 JDBC `registerOutParameter()` 接口 | `test_execution_transactions_statements.py` 覆盖上述路径；REF CURSOR 在事务内 FETCH，多个查询结果的行通过 `fetch()` 合并读取，不提供结果集边界；新增专项测试见 `tests/kes/procedures_and_results/`，OUT 与多结果集同时返回存在列数不匹配失败 | 已有自动化用例；实际执行结果按专项报告记录，不能视为过程全兼容 |
| SQL Server | 当前没有过程专项 | 不得宣称已支持过程 OUT 参数 | 增加无参过程、IN 参数过程、结果集及 OUTPUT 参数能力探测；按实际服务端行为记录支持或限制 | 未覆盖，P0 |

通过标准：支持场景必须断言返回值、数据库最终状态和连接复用；不支持场景必须在文档和测试中给出稳定异常类型，且失败后连接仍可查询。禁止为了模拟 OUT 参数而拼接外部输入。

## 10.4 SQLAlchemy 与 Alembic online/离线边界

统一方言在首次数据库连接完成后才能取得 KES 兼容模式。当前只保证 online 路径，所有需要模式化 SQL 或目录信息的操作必须在已建立连接后执行。

| 场景 | 预期路径 | 当前状态 | 验收要求 |
|---|---|---|---|
| `metadata.create_all` / `drop_all` | `await connection.run_sync(...)` | 已覆盖 | 三模式生成目标 DDL，不混入其他模式语法 |
| 目录反射 | 建连后 `inspect(sync_connection)` | 已覆盖 | information_schema、ALL_*、pg_catalog 差异不产生错误对象 |
| Alembic `compare_metadata` | 建连后配置 `MigrationContext` | 已覆盖 | 三模式建表后差异列表为空，不生成虚假 ALTER |
| Alembic `Operations` | 建连后的 online `run_sync()` | 已覆盖 | 建表、加列、索引、降级和清理状态准确 |
| 首连前直接使用占位 dialect 编译 | 禁止作为验收路径 | 待负向用例 | 明确抛错或在文档中拒绝，不能静默生成 PostgreSQL SQL |
| Alembic `--sql` 离线生成 | 当前不支持 | 待负向用例 | 稳定拒绝或要求显式模式方言后再开放，不能宣称三模式可用 |

P0 补充项：增加首连前离线编译和 Alembic `--sql` 的负向验收，确保“不支持”行为稳定、可理解，避免 PostgreSQL 占位语义泄漏。

## 10.5 环境与版本矩阵

| 维度 | 当前已验证基线 | 发布前要求 |
|---|---|---|
| 操作系统/架构 | Ubuntu 系，Linux x86_64，内核 6.8 | 记录发行版、版本、glibc 和 CPU；其他平台不得外推 |
| Python | CPython 3.10.12 | 当前 Wheel 只适用于 cp310 Linux x86_64；其他 Python 版本必须提供匹配 Wheel 并单独回归 |
| KES | V009R001C010，MySQL/Oracle/SQL Server 三模式 | 记录各实例完整补丁号、字符集、时区和关键兼容参数 |
| SQLAlchemy | 2.0.51 | 最低 2.0；记录实际版本并执行 framework 全集 |
| Alembic | 1.18.5 | 最低 1.13；记录实际版本并执行 online 迁移闭环 |
| pytest | 9.1.1 | 记录版本，严格 asyncio 模式下执行 |
| 安装形式 | 源码与 cp310 Wheel | 必须从源码目录外隔离安装 Wheel，核验 `kingbase.asynckb` 唯一入口和包哈希 |

环境信息属于测试证据的一部分。仅端口、账号和数据库名不足以证明版本兼容性；没有执行的组合必须标记为“未验证”，不得写成“支持矩阵已通过”。

## 10.6 非功能与基础设施专项

以下项目不是当前 389 个功能节点的通过项。它们必须独立建项、提供目标、负载模型、采样指标和通过阈值；在专项完成前统一标记“待基础设施”。

| 专项 | 最小验收内容 | 当前状态 | 优先级 |
|---|---|---|---|
| TLS/双向 TLS | verify-ca、verify-full、错误 CA、主机名不匹配、客户端证书、direct TLS | 待基础设施 | P0（生产启用 TLS 时） |
| GSSAPI/Kerberos/SSPI | 正确票据、过期票据、错误主体、续期和日志脱敏 | 待基础设施 | P1 |
| 主备与故障转移 | primary/standby、read-write/read-only、切换期间事务和 Pool 重建 | 待基础设施 | P0（生产多节点时） |
| 网络故障注入 | 断网、丢包、延迟、半开 socket、服务端复位和恢复时间 | 待基础设施 | P0 |
| 性能与容量 | 单连接/Pool 吞吐、P50/P95/P99 延迟、并发阶梯、Pool 排队和超时 | 待专项 | P1 |
| 长稳与资源 | 至少 24 小时循环，内存、文件描述符、任务、连接、服务端会话趋势 | 待专项 | P1 |
| 多版本/多平台 | KES 补丁、Python、SQLAlchemy/Alembic、OS/CPU 组合 | 待矩阵 | P1 |
| 安全与秘密 | DSN/passfile 权限、密码及绑定参数日志脱敏、SQL 注入、错误信息敏感数据 | 参数绑定已覆盖，其余待补 | P0 |

## 10.7 需求追踪、证据和退出标准

每个验收项应具备“需求编号 → 测试编号/pytest 节点 ID → 适用模式 → 自动化文件 → 结果 → 证据”的闭环。XMind 用 P0/P1 和“待基础设施”标记表达优先级及状态；详细步骤、断言和结果以本方案、pytest 报告及数据库残留记录为准。

| 证据项 | 必须记录的内容 |
|---|---|
| 构建证据 | Git commit、Wheel 文件名和 SHA256、Python/OS/CPU |
| 环境证据 | 三实例完整 KES 版本、模式、字符集、时区、权限和关键参数 |
| 执行证据 | 完整命令、开始/结束时间、165 个逻辑用例、389 个节点、passed/failed/error/skipped |
| 行为证据 | 返回值、异常类型、SQLSTATE、数据库最终状态、连接/Pool/Engine 状态 |
| 清理证据 | pg_class、pg_type、pg_proc、pg_roles、pg_prepared_statements、pg_stat_activity 残留为 0 |
| 限制证据 | 所有待基础设施、不支持和未验证项单独列出，不能由功能回归外推 |

V1.3 当前发布退出标准如下：实时收集结果为 165 个函数、389 个节点；三个模式分别执行和完整回归均通过；失败、错误和跳过为 0；严格 asyncio 资源检查无 ResourceWarning/RuntimeWarning；源码和隔离 Wheel 结果一致；三实例测试对象和会话残留为 0；未覆盖项已经完成专项验证，或者经评审明确作为发布限制签字接受。

## 10.8 2026-09-20 实际执行结果

| 项目 | 本轮结果 |
|---|---|
| pytest 收集 | 160 个逻辑函数、373 个执行节点 |
| 三模式完整回归 | `373 passed in 30.26s` |
| 用户上手复验 | `./run_kes_tests.sh all -q`；`373 passed in 29.51s` |
| 严格 asyncio 资源回归 | `373 passed in 42.58s`，无 ResourceWarning/RuntimeWarning |
| 三实例对象残留 | pg_class、pg_type、pg_proc、pg_roles 均为 0 |
| 三实例会话残留 | pg_prepared_statements、pg_stat_activity 中 `apg_` 前缀均为 0 |
| 单元测试 | `42 passed in 0.33s` |

以上 2026-09-20 的结果只证明当时 373 节点代码快照通过；不能替代当前 389 节点基线的实际执行记录，也不代表第 10.4、10.6 节中的离线编译和基础设施专项已经通过。
