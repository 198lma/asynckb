# asynckb KES 功能覆盖矩阵

2026-11-19：160 个功能测试点、669 个参数化节点。
逐项源码和编号以 [测试点索引](TEST_CASE_INDEX.md)及 manifest 为准。
验证拒绝或限制的测试通过，不代表受限功能可用。

| 模块 | 点/节点 | 主要保留内容 |
| --- | --- | --- |
| CONN 连接与兼容模式 | 8/12 | 模式识别、service/passfile、DSN 优先级、模式校验、独立包及方言身份 |
| PROTO 协议与异步调度 | 28/100 | 占位符、保护文本、绑定接口、COPY 往返与失败恢复、通知、超时取消 |
| TYPE 类型/OID/Codec | 34/87 | 真实类型目录、动态 OID、原生类型、自定义/重置 codec、复杂类型及边界 |
| EXEC 查询/事务/语句资源 | 42/200 | CRUD、批量、Cursor、事务/保存点、隔离、缓存失效、语句回收、过程/函数/OUT、多语句 |
| POOL 连接池 | 13/43 | 容量、获取超时、初始化/归还失败清理、断链重建、取消及并发事务 |
| SA SQLAlchemy 方言 | 20/40 | 统一 URL、类型编译/反射、CRUD、事务、缓存及 pre-ping |
| AUTH 认证与 MAC | 15/187 | SCRAM/MD5/Cleartext/trust、拒绝规则、密码来源、cert/peer/LDAP/RADIUS/ident、HBA/SSO MAC |

本轮 663 通过，6 个 OUT/INOUT 与多结果集组合为已知限制预期失败，
无跳过、无非预期失败。不等于所有公共 API 边界均已穷举。

MySQL 保留整数/无符号、枚举/集合、二进制、JSON、TIME duration 等原生类型；
Oracle 保留 NUMBER、日期时间/间隔、ROWID/UROWID、BFILE/BLOB、CALL 和匿名块
DML 输出；SQL Server 保留数值/金额、字符、日期时间、UNIQUEIDENTIFIER、
VARBINARY、ROWVERSION 及 ZIP 的两个多语句写法。

性能另计 7 场景、三模式 21 组，见 [性能结果](PERFORMANCE_RESULTS.md)。
120 秒持续负载不是 24 小时长稳或生产容量保证。

精简删除 71 点，包括重复冒烟、部分通用工具边界及非核心框架场景。
Alembic、部分流式/跨 schema 反射、多主机回退和 PAM/BSD 环境检查不再单列验收。
删除原因和部分关联保留项见 [删减清单](CASE_REDUCTION.json)，不能据关联项
推定被删断言全部仍有覆盖。Druid/JDBC 监控 Servlet、SQL 防火墙、XA 等不是
asynckb 驱动必测功能。

国密、全平台/补丁矩阵、真实主备切换、网络故障注入、长稳及生产外部认证设施
不在本轮验收范围。PAM/BSD 登录未验证，MAC 不等于密码认证算法。
